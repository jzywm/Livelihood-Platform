package com.msz.acc.config;

import com.msz.acc.application.BindFlow;
import com.msz.acc.application.CloseFlow;
import com.msz.acc.application.FundsAuditService;
import com.msz.acc.application.InlineReconcileExecutor;
import com.msz.acc.application.RecordFlowService;
import com.msz.acc.application.ReconcileFlow;
import com.msz.acc.application.RealnameCallbackFlow;
import com.msz.acc.application.RegisterFlow;
import com.msz.acc.application.SessionFlow;
import com.msz.acc.application.WalletFlowQueryService;
import com.msz.acc.application.port.CaptchaPort;
import com.msz.acc.application.port.ChannelStatementSource;
import com.msz.acc.application.port.FlowStatementReader;
import com.msz.acc.application.port.PaymentChannelPort;
import com.msz.acc.application.port.RealnameChannelPort;
import com.msz.acc.application.port.ReconcileExecutor;
import com.msz.acc.application.port.SessionStore;
import com.msz.acc.application.port.SignatureVerifier;
import com.msz.acc.application.support.HmacFingerprint;
import com.msz.acc.controller.AuthController;
import com.msz.acc.controller.SessionCookie;
import com.msz.acc.controller.SessionViewMapper;
import com.msz.acc.domain.service.AmountPolicy;
import com.msz.acc.domain.service.HashChainService;
import com.msz.acc.domain.service.MaskingPolicy;
import com.msz.acc.domain.service.ReconcileDecision;
import com.msz.acc.domain.service.RealnameStatusMachine;
import com.msz.acc.domain.service.ShardingRouter;
import com.msz.acc.infrastructure.auth.JwtCodec;
import com.msz.acc.infrastructure.auth.OriginValidator;
import com.msz.acc.infrastructure.auth.TrustedHeaderAuthFilter;
import com.msz.acc.infrastructure.auth.session.AccessTokenIssuer;
import com.msz.acc.infrastructure.auth.session.InMemorySessionStore;
import com.msz.acc.infrastructure.auth.session.RedisSessionStore;
import com.msz.acc.infrastructure.auth.session.RefreshTokenStore;
import com.msz.acc.infrastructure.captcha.CaptchaService;
import com.msz.acc.infrastructure.crypto.AesGcmCipher;
import com.msz.acc.infrastructure.crypto.FixedKeyProvider;
import com.msz.acc.infrastructure.crypto.HmacSignatureVerifier;
import com.msz.acc.infrastructure.crypto.KeyProvider;
import com.msz.acc.infrastructure.gateway.HttpChannelClient;
import com.msz.acc.infrastructure.gateway.HttpChannelStatementSource;
import com.msz.acc.infrastructure.gateway.MapperFlowStatementReader;
import com.msz.acc.infrastructure.gateway.PaymentChannelGateway;
import com.msz.acc.infrastructure.gateway.RealnameChannelGateway;
import com.msz.acc.infrastructure.logging.LogMasker;
import com.msz.acc.infrastructure.redis.AccLettuceStringRedisOps;
import com.msz.acc.infrastructure.redis.HashTailStore;
import com.msz.acc.infrastructure.redis.InMemoryStringRedisOps;
import com.msz.acc.infrastructure.redis.RedisHashTailStore;
import com.msz.acc.infrastructure.tx.TransactionBoundaryFilter;
import com.msz.acc.infrastructure.tx.TransactionalMapperProxy;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.DaoSupport;
import com.msz.acc.repository.IdempotencyRecordMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import com.msz.acc.repository.ReconcileTaskMapper;
import com.msz.acc.repository.RequestSqlSessionHolder;
import com.msz.acc.repository.WalletBindingMapper;
import com.msz.acc.repository.WalletFlowMapper;
import com.msz.common.idgen.DefaultIdGenMetrics;
import com.msz.common.idgen.IdGenerator;
import com.msz.common.idgen.IdGenException;
import com.msz.common.idgen.SnowflakeIdGenerator;
import com.msz.common.redis.StringRedisOps;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.session.SqlSessionFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import javax.sql.DataSource;
import java.io.PrintWriter;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.time.Clock;
import java.util.Map;
import java.util.Set;
import java.util.function.LongSupplier;

/**
 * ACC 接口层装配（S5）：端口适配（Captcha/实名通道/支付通道/账单/验签）、
 * 数据层（DaoSupport.SqlSessionFactory + 事务感知 Mapper 代理）、各 Flow、
 * 鉴权 Filter（order 1，/acc/*）与事务边界 Filter（order 2，/acc/*）。
 *
 * <p>测试凭据口径：KeyProvider/JWT/回调验签/指纹均为固定测试凭据（生产经 KMS/配置注入）；
 * Redis 用 {@link InMemoryStringRedisOps} 兜底（M1 无 Redis 部署）；数据源为占位实现
 * （M1 模块化单体，真实 DataSource 由部署环境注入，本模块任何会话级 DB 调用将明确失败）。</p>
 */
@Configuration
@EnableConfigurationProperties(AccProperties.class)
public class AccConfiguration {

    /**
     * JWT 白名单路径（无 token 放行；callback/internal 由内部 Token 鉴权；会话登录/换发为
     * 「无短 token 时的必经入口」）。**不含 {@code /acc/auth/logout}**——登出需要有效短 token
     * 或有效长 token Cookie，白名单化只会削弱保护。匹配走**路径段边界**
     * （{@link AuthPathMatcher}），{@code /acc/auth/loginAny} 之类的近似路径不得放行。
     */
    public static final Set<String> NO_AUTH_PATHS = Set.of(
            "/acc/captcha", "/acc/register", "/acc/realname/status",
            "/acc/realname/callback", "/acc/internal",
            "/acc/auth/login", "/acc/auth/refresh");

    private static final String KEY_ID = "k1";
    private static final String FINGERPRINT_SECRET = "acc-fingerprint-test-secret";

    private static final Logger log = LoggerFactory.getLogger(AccConfiguration.class);

    // ---------- 加密 ----------

    @Bean
    public KeyProvider keyProvider() {
        return new FixedKeyProvider(Map.of(KEY_ID, testKey()));
    }

    @Bean
    public AesGcmCipher aesGcmCipher(KeyProvider keyProvider) {
        return new AesGcmCipher(keyProvider);
    }

    private static SecretKey testKey() {
        byte[] bytes = new byte[32];
        for (int i = 0; i < bytes.length; i++) {
            bytes[i] = (byte) (i + 1);
        }
        return new SecretKeySpec(bytes, "AES");
    }

    // ---------- 数据层 ----------

    @Bean
    public DaoSupport daoSupport(AesGcmCipher cipher) {
        return new DaoSupport(cipher, KEY_ID);
    }

    /** M1 占位数据源：真实 DataSource 由部署环境注入；工厂/映射器创建不触连，任何 DB 调用即明确失败。 */
    @Bean
    public DataSource accDataSource() {
        return new PlaceholderDataSource();
    }

    @Bean
    public SqlSessionFactory sqlSessionFactory(DaoSupport daoSupport, DataSource dataSource) {
        return daoSupport.factory(dataSource);
    }

    /** 请求级会话持有器：ThreadLocal 绑定 + 首次触库惰性开启 + 无请求上下文降级（design D2/D4/D7）。 */
    @Bean
    public RequestSqlSessionHolder requestSqlSessionHolder(SqlSessionFactory factory) {
        return new RequestSqlSessionHolder(factory);
    }

    /** Mapper 事务感知代理工厂：每次调用转发到当前请求会话的 Mapper（design D3）。 */
    @Bean
    public TransactionalMapperProxy transactionalMapperProxy(RequestSqlSessionHolder holder) {
        return new TransactionalMapperProxy(holder);
    }

    @Bean
    public AccountMapper accountMapper(TransactionalMapperProxy mapperProxy) {
        return mapper(mapperProxy, AccountMapper.class);
    }

    @Bean
    public RealnameRecordMapper realnameRecordMapper(TransactionalMapperProxy mapperProxy) {
        return mapper(mapperProxy, RealnameRecordMapper.class);
    }

    @Bean
    public WalletFlowMapper walletFlowMapper(TransactionalMapperProxy mapperProxy) {
        return mapper(mapperProxy, WalletFlowMapper.class);
    }

    @Bean
    public WalletBindingMapper walletBindingMapper(TransactionalMapperProxy mapperProxy) {
        return mapper(mapperProxy, WalletBindingMapper.class);
    }

    @Bean
    public ReconcileTaskMapper reconcileTaskMapper(TransactionalMapperProxy mapperProxy) {
        return mapper(mapperProxy, ReconcileTaskMapper.class);
    }

    @Bean
    public IdempotencyRecordMapper idempotencyRecordMapper(TransactionalMapperProxy mapperProxy) {
        return mapper(mapperProxy, IdempotencyRecordMapper.class);
    }

    /**
     * Mapper 装配：**事务感知动态代理**（{@link TransactionalMapperProxy}，design D3）。
     *
     * <p>每个 Mapper Bean 仍是单例（名称/返回类型/全部构造注入点不变），但不再持有固定会话：
     * 每次方法调用向 {@link RequestSqlSessionHolder} 索取**当前请求会话**上的真实 Mapper，一个请求内
     * 的所有数据访问因此落在同一会话/连接上，由请求级事务边界统一提交或回滚
     * （{@link TransactionBoundaryFilter}：正常返回提交、未捕获异常回滚、{@code finally} 关闭会话并归还连接）。
     * 会话在请求**首次真正访问数据库**时才惰性开启，不触库的请求不占用连接；非 Web 调用路径
     * （测试夹具/脚本/将来的定时任务）退化为「单次自动提交会话 + 调用后关闭」。</p>
     *
     * <p><b>历史缺陷记录（2026-09-15 真机联调，任务组 10.2，不得改写）</b>：原实现为
     * {@code factory.openSession()}——会话长驻且 {@code autoCommit=false}、事务永不提交，真实库下出现
     * 「写不落库（接口返 200 但 {@code closed_at} 仍为 NULL）」与「读陈旧（外部已提交的变更查不到）」
     * 两个缺陷（控制器测试全 mock Mapper、DAO 测试用自动提交，装配层会话语义此前无覆盖）。
     * 当时以「自动提交 + 长驻会话」止血，残留跨表无原子性、无事务边界、并发共享会话三项风险；
     * 该三项已由本装配切换（{@code fix-acc-transaction-boundary}）收敛为请求级会话 + 请求级事务边界。</p>
     */
    private static <T> T mapper(TransactionalMapperProxy mapperProxy, Class<T> type) {
        return mapperProxy.create(type);
    }

    // ---------- 公共组件 ----------

    @Bean
    public IdGenerator idGenerator() {
        // M1 雪花轨：号段源 L3 fast-fail（无号段依赖部署）
        return new SnowflakeIdGenerator(1L, System::currentTimeMillis,
                bizTag -> {
                    throw new IdGenException("号段不可用（M1 未部署）");
                },
                (level, message) -> {
                },
                new DefaultIdGenMetrics(), new SnowflakeIdGenerator.Config());
    }

    @Bean
    public Clock clock() {
        return Clock.systemUTC();
    }

    /** 秒级时钟（毫秒）：会话 TTL / 宽限窗口判定用，与 {@link Clock} 分离以便测试注入固定时刻。 */
    @Bean
    public LongSupplier sessionEpochMillis(Clock clock) {
        return clock::millis;
    }

    /**
     * Redis 端口（S5 既有端口，**2026-09-15 扩展为「由配置决定实现」**）：配置了
     * {@code acc.redis.host} → {@link AccLettuceStringRedisOps}（生产，Lettuce 直接依赖 + 可选 AUTH +
     * 有界超时 2s/1s）；未配置 → {@link InMemoryStringRedisOps}（单测/演练兜底）。
     *
     * <p><b>口径（用户裁决 R-A6）</b>：不引 spring-data-redis 全家桶；生产**必须**配置 Redis 且与网关
     * 同实例，否则会话族与吊销名单不共享 ⇒ 登出/踢人失效——本端口同时服务验证码/哈希链尾，
     * 故仍按 {@code acc.redis.host} 择实现；而**会话存储**的择实现已改为显式开关
     * {@code acc.session.store}（L1/R-A8，缺 host 即启动失败），见 {@link #sessionStore}。</p>
     *
     * <p>销毁：不显式声明 {@code destroyMethod}——Spring 会按「返回类型可达的 public close()/shutdown()」
     * 自动推断（Lettuce 实现是 {@code AutoCloseable}，内存实现没有该方法，框架会自行跳过），
     * 显式写死 {@code close} 会在内存实现上校验失败（真实缺陷，2026-09-15 由全量测试发现）。</p>
     */
    @Bean
    public StringRedisOps stringRedisOps(AccProperties properties) {
        String host = properties.getRedis().getHost();
        if (host == null || host.isBlank()) {
            log.warn("acc.redis.host 未配置：会话存储使用进程内兜底实现——"
                    + "仅限单元测试/演练，生产部署必须配置 Redis（否则登出与踢人无效）");
            return new InMemoryStringRedisOps();
        }
        return new AccLettuceStringRedisOps(host.trim(), properties.getRedis().getPort(),
                properties.getRedis().getUsername(), properties.getRedis().getPassword());
    }

    /**
     * 会话存储端口（design D2/D3/D8 + L1 修复裁定 R-A8）：由**显式开关**
     * {@code acc.session.store=memory|redis}（默认 {@code memory}）决定实现。
     *
     * <ul>
     *   <li>{@code redis}：生产语义——{@link RedisSessionStore}（Lua 原子写入 + fail-closed），
     *       且**必须配置 {@code acc.redis.host}**；缺失即抛 {@link IllegalStateException} **启动失败**，
     *       不再静默退化为进程内存储（否则换发/登出写下的吊销名单与网关读的不是同一份，登出/踢人静默失效）。</li>
     *   <li>{@code memory}：{@link InMemorySessionStore}（仅单元测试/演练），**不触碰 Redis**。</li>
     *   <li>其它取值：拼错即启动失败（避免「写了 redis-xxx 却静默走内存」这类配置事故）。</li>
     * </ul>
     *
     * <p><b>L1 记录（2026-09-16 复评修复波）</b>：原实现以 {@code acc.redis.host} 是否为空隐式择实现，
     * 「未配置」与「显式选内存」不可区分——生产漏配 host 即失去吊销能力却照常启动，与 spec
     * `acc-session`「会话存储不可用时快速失败、绝不签发无法吊销的 token」相悖。现改为显式开关 +
     * 缺 host 启动失败，并把「生产必须设 {@code acc.session.store=redis}」写入部署件与服务基线。</p>
     *
     * <p>存储运行期不可用时实现抛 {@link SessionStoreUnavailableException}，经
     * {@link com.msz.acc.controller.GlobalExceptionHandler} 统一映射 **503 + 5003**：
     * 登录/换发/登出**快速失败**，绝不签发无法吊销的 token。</p>
     */
    @Bean
    public SessionStore sessionStore(AccProperties properties, StringRedisOps stringRedisOps,
                                     Clock clock) {
        String store = properties.getSession().getStore() == null
                ? "" : properties.getSession().getStore().trim().toLowerCase();
        LongSupplier sessionClock = clock::millis;
        if ("memory".equals(store)) {
            String host = properties.getRedis().getHost();
            if (host != null && !host.isBlank()) {
                log.warn("acc.session.store=memory 但 acc.redis.host 已配置：会话族与吊销名单仍只落在进程内——"
                        + "仅限单元测试/演练；生产必须设 acc.session.store=redis（否则登出/踢人失效）");
            }
            return new InMemorySessionStore(sessionClock);
        }
        if ("redis".equals(store)) {
            String host = properties.getRedis().getHost();
            if (host == null || host.isBlank()) {
                throw new IllegalStateException("acc.session.store=redis 需配置 acc.redis.host（生产会话存储）："
                        + "缺少 Redis 时会话族与吊销名单无法与网关共享 ⇒ 登出/踢人失效；"
                        + "本地/测试请显式设 acc.session.store=memory");
            }
            return new RedisSessionStore(stringRedisOps, sessionClock);
        }
        throw new IllegalStateException("acc.session.store=" + properties.getSession().getStore()
                + " 非法：仅支持 memory（测试/演练）| redis（生产，需配 acc.redis.host）");
    }

    @Bean
    public ShardingRouter shardingRouter() {
        return new ShardingRouter();
    }

    @Bean
    public HashChainService hashChainService() {
        return new HashChainService();
    }

    @Bean
    public HashTailStore hashTailStore(StringRedisOps ops, HashChainService chainService) {
        return new RedisHashTailStore(ops, chainService.genesisHash());
    }

    @Bean
    public AmountPolicy amountPolicy() {
        return new AmountPolicy();
    }

    @Bean
    public MaskingPolicy maskingPolicy() {
        return new MaskingPolicy();
    }

    @Bean
    public LogMasker logMasker() {
        return new LogMasker();
    }

    @Bean
    public RealnameStatusMachine realnameStatusMachine() {
        return new RealnameStatusMachine();
    }

    @Bean
    public ReconcileDecision reconcileDecision() {
        return new ReconcileDecision();
    }

    @Bean
    public HmacFingerprint hmacFingerprint() {
        return new HmacFingerprint(FINGERPRINT_SECRET);
    }

    // ---------- 端口适配（S4 接口的真实实现） ----------

    @Bean
    public CaptchaService captchaService(StringRedisOps ops, IdGenerator idGenerator, Clock clock) {
        return new CaptchaService(ops, idGenerator, clock);
    }

    @Bean
    public HttpChannelClient httpChannelClient() {
        return new HttpChannelClient();
    }

    @Bean
    public RealnameChannelPort realnameChannelPort(HttpChannelClient client, AccProperties properties,
                                                   ObjectMapper mapper) {
        return new RealnameChannelGateway(client, properties.getChannel().getRealnameBaseUrl(),
                properties.getRealnameAuthorizeUrlTemplate(), mapper);
    }

    @Bean
    public PaymentChannelPort paymentChannelPort(HttpChannelClient client, AccProperties properties,
                                                 ObjectMapper mapper) {
        return new PaymentChannelGateway(client, properties.getChannel().getPaymentBaseUrl(), mapper);
    }

    @Bean
    public ChannelStatementSource channelStatementSource(HttpChannelClient client, AccProperties properties,
                                                         ObjectMapper mapper) {
        return new HttpChannelStatementSource(client, properties.getChannel().getStatementBaseUrl(), mapper);
    }

    @Bean
    public FlowStatementReader flowStatementReader(WalletFlowMapper walletFlowMapper, ShardingRouter shardingRouter) {
        return new MapperFlowStatementReader(walletFlowMapper, shardingRouter);
    }

    @Bean
    public ReconcileExecutor reconcileExecutor(ChannelStatementSource channelStatementSource,
                                               FlowStatementReader flowStatementReader) {
        return new InlineReconcileExecutor(channelStatementSource, flowStatementReader);
    }

    @Bean
    public HmacSignatureVerifier signatureVerifier(AccProperties properties) {
        return new HmacSignatureVerifier(properties.getCallbackSecret());
    }

    // ---------- 应用层 ----------

    @Bean
    public RegisterFlow registerFlow(CaptchaPort captchaPort, RealnameChannelPort realnameChannelPort,
                                     AccountMapper accountMapper, RealnameRecordMapper realnameRecordMapper,
                                     IdGenerator idGenerator, HmacFingerprint hmacFingerprint, Clock clock) {
        return new RegisterFlow(captchaPort, realnameChannelPort, accountMapper, realnameRecordMapper,
                idGenerator, hmacFingerprint, clock);
    }

    @Bean
    public RealnameCallbackFlow realnameCallbackFlow(SignatureVerifier signatureVerifier,
                                                     RealnameRecordMapper realnameRecordMapper,
                                                     AccountMapper accountMapper, IdGenerator idGenerator,
                                                     RealnameStatusMachine statusMachine, Clock clock) {
        return new RealnameCallbackFlow(signatureVerifier, realnameRecordMapper, accountMapper,
                idGenerator, statusMachine, clock);
    }

    @Bean
    public WalletFlowQueryService walletFlowQueryService(WalletFlowMapper walletFlowMapper,
                                                         ShardingRouter shardingRouter, Clock clock) {
        return new WalletFlowQueryService(walletFlowMapper, shardingRouter, clock);
    }

    @Bean
    public RecordFlowService recordFlowService(WalletFlowMapper walletFlowMapper, HashChainService hashChainService,
                                               HashTailStore hashTailStore, AmountPolicy amountPolicy,
                                               IdGenerator idGenerator, ShardingRouter shardingRouter) {
        return new RecordFlowService(walletFlowMapper, hashChainService, hashTailStore,
                amountPolicy, idGenerator, shardingRouter);
    }

    @Bean
    public BindFlow bindFlow(AccountMapper accountMapper, WalletBindingMapper walletBindingMapper,
                             PaymentChannelPort paymentChannelPort, IdempotencyRecordMapper idempotencyRecordMapper,
                             IdGenerator idGenerator, Clock clock) {
        return new BindFlow(accountMapper, walletBindingMapper, paymentChannelPort,
                idempotencyRecordMapper, idGenerator, clock);
    }

    @Bean
    public ReconcileFlow reconcileFlow(ReconcileTaskMapper reconcileTaskMapper,
                                       IdempotencyRecordMapper idempotencyRecordMapper, IdGenerator idGenerator,
                                       ReconcileExecutor reconcileExecutor, ReconcileDecision reconcileDecision,
                                       Clock clock) {
        return new ReconcileFlow(reconcileTaskMapper, idempotencyRecordMapper, idGenerator,
                reconcileExecutor, reconcileDecision, clock);
    }

    @Bean
    public CloseFlow closeFlow(AccountMapper accountMapper, RealnameRecordMapper realnameRecordMapper, Clock clock) {
        return new CloseFlow(accountMapper, realnameRecordMapper, clock);
    }

    @Bean
    public FundsAuditService fundsAuditService(WalletFlowMapper walletFlowMapper,
                                               ReconcileTaskMapper reconcileTaskMapper,
                                               ShardingRouter shardingRouter, Clock clock) {
        return new FundsAuditService(walletFlowMapper, reconcileTaskMapper, shardingRouter, clock);
    }

    /** 会话凭据生命周期流程（登录签发 / 换发轮换 / 重用检测 / 登出吊销）。 */
    @Bean
    public SessionFlow sessionFlow(SessionStore sessionStore, AccountMapper accountMapper,
                                   CaptchaPort captchaPort, HmacFingerprint hmacFingerprint,
                                   AccessTokenIssuer accessTokenIssuer, RefreshTokenStore refreshTokenStore,
                                   Logger sessionAuditLogger) {
        return new SessionFlow(sessionStore, accountMapper, captchaPort, hmacFingerprint,
                accessTokenIssuer, refreshTokenStore, sessionAuditLogger);
    }

    // ---------- 鉴权与事务边界(2026-09-15:网关为唯一鉴权点,服务内改为信任网关透传的身份头) ----------

    /** JWT 编解码器:仍用于**签发**(登录/注册签发 token);验签职责已移交网关。 */
    @Bean
    public JwtCodec jwtCodec(Clock clock) {
        return new JwtCodec(clock);
    }

    /**
     * 短 token 签发器（任务 3.6）：有效期**常量 900s**（PDD v1.18 §8.4.1 定档），
     * 同时读取 {@code acc.session.access-token-ttl-seconds} 以便部署侧核对——
     * 配置值超过 15 分钟会启动即告警（网关按 15m+60s 上限拒绝，签了也没用）。
     */
    @Bean
    public AccessTokenIssuer accessTokenIssuer(JwtCodec jwtCodec, AccProperties properties, Clock clock) {
        long configured = properties.getSession().getAccessTokenTtlSeconds();
        if (configured > AccessTokenIssuer.ACCESS_TOKEN_TTL_SECONDS) {
            log.error("acc.session.access-token-ttl-seconds={} 超过网关上限 {}s："
                            + "网关会以「有效期超出上限」拒绝，实际仍按 {}s 签发（请改回 900）",
                    configured, AccessTokenIssuer.ACCESS_TOKEN_TTL_SECONDS,
                    AccessTokenIssuer.ACCESS_TOKEN_TTL_SECONDS);
        }
        return new AccessTokenIssuer(jwtCodec, properties.getJwtSecret(),
                AccessTokenIssuer.ACCESS_TOKEN_TTL_SECONDS, clock);
    }

    /** refresh 签发/判定/轮换（design D2/D6）：TTL 与宽限窗口来自 {@code acc.session.*}。 */
    @Bean
    public RefreshTokenStore refreshTokenStore(SessionStore sessionStore, JwtCodec jwtCodec,
                                               AccProperties properties, Clock clock) {
        return new RefreshTokenStore(sessionStore, jwtCodec, properties.getJwtSecret(),
                properties.getSession().getRefreshTokenTtlSeconds(),
                properties.getSession().getRotationGraceSeconds(),
                AccessTokenIssuer.ACCESS_TOKEN_TTL_SECONDS, clock::millis);
    }

    /** 安全审计日志（重放/登出事件）：独立 logger 名，便于接入安全告警与日志留存口径。 */
    @Bean
    public Logger sessionAuditLogger() {
        return LoggerFactory.getLogger("acc.session.audit");
    }

    /**
     * 会话端点 Cookie 口径（R-A7，design D6）：`HttpOnly; Secure; SameSite=<配置>;
     * Path=/api/v1/acc/auth`（**对外路径**，网关改写前口径，与 openapi 文档一致）；
     * Max-Age = refresh 有效期。
     */
    @Bean
    public SessionCookie sessionCookie(AccProperties properties) {
        return SessionCookie.forSessionEndpoints(properties.getSession().getCookieName(),
                properties.getSession().isCookieSecure(), properties.getSession().getCookieSameSite(),
                SessionCookie.SESSION_PATH, properties.getSession().getRefreshTokenTtlSeconds());
    }

    /** 换发/仅凭 Cookie 登出的来源校验（R-A3）：允许列表来自 {@code acc.session.allowed-origins}。 */
    @Bean
    public OriginValidator originValidator(AccProperties properties) {
        return new OriginValidator(properties.getSession().getAllowedOrigins());
    }

    /** 会话控制器（openapi v1.2.0 `/acc/auth/{login,refresh,logout}`）。 */
    @Bean
    public AuthController authController(SessionFlow sessionFlow, OriginValidator originValidator,
                                         SessionCookie sessionCookie, JwtCodec jwtCodec,
                                         AccProperties properties, Clock clock) {
        return new AuthController(sessionFlow, originValidator, sessionCookie, new SessionViewMapper(),
                jwtCodec, properties.getJwtSecret(), clock);
    }

    @Bean
    public TrustedHeaderAuthFilter trustedHeaderAuthFilter() {
        return new TrustedHeaderAuthFilter(NO_AUTH_PATHS);
    }

    @Bean
    public FilterRegistrationBean<TrustedHeaderAuthFilter> trustedHeaderAuthFilterRegistration(
            TrustedHeaderAuthFilter filter) {
        FilterRegistrationBean<TrustedHeaderAuthFilter> registration = new FilterRegistrationBean<>(filter);
        registration.setOrder(1);
        registration.addUrlPatterns("/acc/*");
        return registration;
    }

    @Bean
    public TransactionBoundaryFilter transactionBoundaryFilter(RequestSqlSessionHolder holder) {
        return new TransactionBoundaryFilter(holder);
    }

    /**
     * 事务边界过滤器注册（design D5）：order 2 —— 紧随鉴权过滤器（order 1）之后、控制器之前，
     * 同一个 {@code /acc/*} 口径；进入请求只标记作用域（不取连接），结束提交/回滚并关闭会话。
     */
    @Bean
    public FilterRegistrationBean<TransactionBoundaryFilter> transactionBoundaryFilterRegistration(
            TransactionBoundaryFilter filter) {
        FilterRegistrationBean<TransactionBoundaryFilter> registration = new FilterRegistrationBean<>(filter);
        registration.setOrder(2);
        registration.addUrlPatterns("/acc/*");
        return registration;
    }

    /** M1 占位数据源：任何会话级连接均明确失败（工厂/映射器创建不触连）。 */
    private static final class PlaceholderDataSource implements DataSource {

        @Override
        public Connection getConnection() {
            return unavailableConnection();
        }

        @Override
        public Connection getConnection(String username, String password) {
            return unavailableConnection();
        }

        private static Connection unavailableConnection() {
            return (Connection) Proxy.newProxyInstance(
                    Connection.class.getClassLoader(),
                    new Class<?>[]{Connection.class},
                    (proxy, method, args) -> {
                        throw new UnsupportedOperationException(
                                "ACC M1 未配置真实数据源（部署环境注入），数据库调用不可用");
                    });
        }

        @Override
        public PrintWriter getLogWriter() {
            return null;
        }

        @Override
        public void setLogWriter(PrintWriter out) {
            // no-op
        }

        @Override
        public void setLoginTimeout(int seconds) {
            // no-op
        }

        @Override
        public int getLoginTimeout() {
            return 0;
        }

        @Override
        public java.util.logging.Logger getParentLogger() throws SQLFeatureNotSupportedException {
            throw new SQLFeatureNotSupportedException("M1 占位数据源");
        }

        @Override
        public <T> T unwrap(Class<T> iface) throws SQLException {
            if (iface.isInstance(this)) {
                return iface.cast(this);
            }
            throw new SQLException("不支持 unwrap: " + iface);
        }

        @Override
        public boolean isWrapperFor(Class<?> iface) {
            return iface.isInstance(this);
        }
    }
}

package com.msz.acc.config;

import com.msz.acc.application.BindFlow;
import com.msz.acc.application.CloseFlow;
import com.msz.acc.application.FundsAuditService;
import com.msz.acc.application.InlineReconcileExecutor;
import com.msz.acc.application.RecordFlowService;
import com.msz.acc.application.ReconcileFlow;
import com.msz.acc.application.RealnameCallbackFlow;
import com.msz.acc.application.RegisterFlow;
import com.msz.acc.application.WalletFlowQueryService;
import com.msz.acc.application.port.CaptchaPort;
import com.msz.acc.application.port.ChannelStatementSource;
import com.msz.acc.application.port.FlowStatementReader;
import com.msz.acc.application.port.PaymentChannelPort;
import com.msz.acc.application.port.RealnameChannelPort;
import com.msz.acc.application.port.ReconcileExecutor;
import com.msz.acc.application.port.SignatureVerifier;
import com.msz.acc.application.support.HmacFingerprint;
import com.msz.acc.domain.service.AmountPolicy;
import com.msz.acc.domain.service.HashChainService;
import com.msz.acc.domain.service.MaskingPolicy;
import com.msz.acc.domain.service.ReconcileDecision;
import com.msz.acc.domain.service.RealnameStatusMachine;
import com.msz.acc.domain.service.ShardingRouter;
import com.msz.acc.infrastructure.auth.JwtCodec;
import com.msz.acc.infrastructure.auth.TrustedHeaderAuthFilter;
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
import com.msz.acc.infrastructure.redis.HashTailStore;
import com.msz.acc.infrastructure.redis.InMemoryStringRedisOps;
import com.msz.acc.infrastructure.redis.RedisHashTailStore;
import com.msz.acc.repository.AccountMapper;
import com.msz.acc.repository.DaoSupport;
import com.msz.acc.repository.IdempotencyRecordMapper;
import com.msz.acc.repository.RealnameRecordMapper;
import com.msz.acc.repository.ReconcileTaskMapper;
import com.msz.acc.repository.WalletBindingMapper;
import com.msz.acc.repository.WalletFlowMapper;
import com.msz.common.idgen.DefaultIdGenMetrics;
import com.msz.common.idgen.IdGenerator;
import com.msz.common.idgen.IdGenException;
import com.msz.common.idgen.SnowflakeIdGenerator;
import com.msz.common.redis.StringRedisOps;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.session.SqlSessionFactory;
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
import java.util.logging.Logger;

/**
 * ACC 接口层装配（S5）：端口适配（Captcha/实名通道/支付通道/账单/验签）、
 * 数据层（DaoSupport.SqlSessionFactory + 各 Mapper）、各 Flow、鉴权 Filter（order 1，/acc/**）。
 *
 * <p>测试凭据口径：KeyProvider/JWT/回调验签/指纹均为固定测试凭据（生产经 KMS/配置注入）；
 * Redis 用 {@link InMemoryStringRedisOps} 兜底（M1 无 Redis 部署）；数据源为占位实现
 * （M1 模块化单体，真实 DataSource 由部署环境注入，本模块任何会话级 DB 调用将明确失败）。</p>
 */
@Configuration
@EnableConfigurationProperties(AccProperties.class)
public class AccConfiguration {

    /** JWT 白名单路径（无 token 放行；callback/internal 由内部 Token 鉴权）。 */
    public static final Set<String> NO_AUTH_PATHS = Set.of(
            "/acc/captcha", "/acc/register", "/acc/realname/status",
            "/acc/realname/callback", "/acc/internal");

    private static final String KEY_ID = "k1";
    private static final String FINGERPRINT_SECRET = "acc-fingerprint-test-secret";

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

    @Bean
    public AccountMapper accountMapper(SqlSessionFactory factory) {
        return mapper(factory, AccountMapper.class);
    }

    @Bean
    public RealnameRecordMapper realnameRecordMapper(SqlSessionFactory factory) {
        return mapper(factory, RealnameRecordMapper.class);
    }

    @Bean
    public WalletFlowMapper walletFlowMapper(SqlSessionFactory factory) {
        return mapper(factory, WalletFlowMapper.class);
    }

    @Bean
    public WalletBindingMapper walletBindingMapper(SqlSessionFactory factory) {
        return mapper(factory, WalletBindingMapper.class);
    }

    @Bean
    public ReconcileTaskMapper reconcileTaskMapper(SqlSessionFactory factory) {
        return mapper(factory, ReconcileTaskMapper.class);
    }

    @Bean
    public IdempotencyRecordMapper idempotencyRecordMapper(SqlSessionFactory factory) {
        return mapper(factory, IdempotencyRecordMapper.class);
    }

    /**
     * Mapper 装配：**自动提交会话**（{@code openSession(true)}，与 {@code repository} 层 DAO 测试同口径）。
     *
     * <p>2026-09-15 真机联调（任务组 10.2）修正：原实现为 {@code openSession()}——会话长驻且
     * {@code autoCommit=false}、事务永不提交，真实库下出现「写不落库（接口返 200 但
     * {@code closed_at} 仍为 NULL）」与「读陈旧（外部已提交的变更查不到）」两个缺陷
     * （控制器测试全 mock Mapper、DAO 测试用自动提交，装配层会话语义此前无覆盖）。</p>
     *
     * <p><b>已知限制（登记待收敛）</b>：会话仍为长驻（非按请求），跨表写入无原子性；
     * M2 收敛为按请求会话 + 显式事务边界（见 {@code services/acc/docs/README.md} 已知限制）。</p>
     */
    private static <T> T mapper(SqlSessionFactory factory, Class<T> type) {
        return factory.openSession(true).getMapper(type);
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

    @Bean
    public StringRedisOps stringRedisOps() {
        return new InMemoryStringRedisOps();
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

    // ---------- 鉴权(2026-09-15:网关为唯一鉴权点,服务内改为信任网关透传的身份头) ----------

    /** JWT 编解码器:仍用于**签发**(登录/注册签发 token);验签职责已移交网关。 */
    @Bean
    public JwtCodec jwtCodec() {
        return new JwtCodec();
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
        public Logger getParentLogger() throws SQLFeatureNotSupportedException {
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

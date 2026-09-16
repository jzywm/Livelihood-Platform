package com.msz.acc.infrastructure.redis;

import com.msz.acc.infrastructure.auth.session.SessionStoreUnavailableException;
import com.msz.common.redis.StringRedisOps;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.ScriptOutputType;
import io.lettuce.core.SetArgs;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;

import java.time.Duration;
import java.util.List;

/**
 * ACC 侧 {@link StringRedisOps} 的 **Lettuce 直接实现**（R-A6，生产）：不引 spring-data-redis
 * 全家桶，只依赖 {@code io.lettuce:lettuce-core}（与网关所用 lettuce 同版本）。
 *
 * <p><b>超时有界</b>：命令 {@value #COMMAND_TIMEOUT_SECONDS} 秒、连接 1 秒——会话存储是登录/换发/登出
 * 的强依赖，必须在秒级内失败而不是把请求线程挂死（fail-closed 的前提是「快速」失败）。</p>
 *
 * <p><b>可选 AUTH</b>：{@code acc.redis.username}/{@code acc.redis.password} 均空白时连接不带 AUTH
 * （兼容无密码的本地/演练实例）；配置了就带上（Redis 6 ACL 支持 username + password）。</p>
 *
 * <p><b>故障映射</b>：所有 Lettuce 异常统一映射为 {@link SessionStoreUnavailableException}
 * （HTTP 503 + 5003）——调用方据此快速失败，**不签发无法吊销的 token**；异常消息只含键名/脚本标识，
 * 不含键值或凭据（日志脱敏口径）。</p>
 *
 * <p><b>连接生命周期</b>：构造即建连（启动期暴露配置错误），由 Spring 容器经 {@code close()} 关停。
 * Lettuce 自身对协议级 keepalive 与重连有保障，故不在本类内另设健康探测定时任务；
 * 请求期故障由每次命令的异常直接暴露。</p>
 */
public final class AccLettuceStringRedisOps implements StringRedisOps, AutoCloseable {

    /** 命令超时（秒）：会话端点的依赖预算上限。 */
    public static final long COMMAND_TIMEOUT_SECONDS = 2L;

    /** 连接超时（秒）：建连必须比命令更快失败，避免启动/首个请求长时间挂起。 */
    public static final long CONNECT_TIMEOUT_SECONDS = 1L;

    /** 命令超时。 */
    public static final Duration COMMAND_TIMEOUT = Duration.ofSeconds(COMMAND_TIMEOUT_SECONDS);

    /** 连接超时。 */
    public static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(CONNECT_TIMEOUT_SECONDS);

    private final RedisClient client;
    private final StatefulRedisConnection<String, String> connection;
    private final RedisCommands<String, String> sync;

    public AccLettuceStringRedisOps(String host, int port, String username, String password) {
        this.client = RedisClient.create(redisUri(host, port, username, password));
        try {
            this.connection = client.connect();
        } catch (RuntimeException e) {
            // 连接失败：释放客户端线程池，避免「构造抛错但资源泄漏」
            client.shutdown();
            throw new SessionStoreUnavailableException("会话存储连接失败（Redis 不可用）", e);
        }
        this.sync = connection.sync();
    }

    /** 构造连接 URI（纯函数，便于单测直接断言 AUTH 与超时）。 */
    public static RedisURI redisUri(String host, int port, String username, String password) {
        RedisURI.Builder builder = RedisURI.builder()
                .withHost(host)
                .withPort(port)
                .withTimeout(COMMAND_TIMEOUT);
        if (password != null && !password.isBlank()) {
            if (username != null && !username.isBlank()) {
                builder.withAuthentication(username, password.toCharArray());
            } else {
                builder.withPassword(password.toCharArray());
            }
        }
        return builder.build();
    }

    @Override
    public Long incr(String key) {
        return call(() -> sync.incr(key), key);
    }

    @Override
    public Boolean expire(String key, long seconds) {
        return call(() -> sync.expire(key, seconds), key);
    }

    @Override
    public String get(String key) {
        return call(() -> sync.get(key), key);
    }

    @Override
    public Boolean setNx(String key, String value, long ttlSeconds) {
        return call(() -> "OK".equals(sync.set(key, value, SetArgs.Builder.nx().ex(ttlSeconds))), key);
    }

    /**
     * 执行 Lua 脚本并按**整数回复**解码（返回 {@link Long}）。
     *
     * <p><b>为什么必须是 {@link ScriptOutputType#INTEGER}（真实缺陷记录，2026-09-16）</b>：
     * {@link com.msz.acc.infrastructure.auth.session.RedisSessionStore} 的 5 个脚本
     * （ISSUE/ROTATE/CONSUME/SET/REVOKE）一律 {@code return 1}，即 Redis 整数回复。
     * 原实现用 {@code VALUE}（{@code ValueOutput}）解码，真实 Redis 下抛
     * {@code UnsupportedOperationException: io.lettuce.core.output.ValueOutput does not support set(long)}，
     * 于是建族/轮换/单次使用/吊销**全部失效**——登录直接 503 + 5003，即「真实 Redis 不可用」。
     * 该缺陷由「双 token 会话闭环演练」（任务 7.2）在真实 Redis 上首次暴露：此前的单测用假客户端
     * 回放期望语义，从未真正执行过脚本。</p>
     *
     * <p><b>契约</b>：本端口只支持「返回整数的脚本」（会话脚本的既有形态）；如需字符串/数组回复的脚本，
     * 必须显式扩展本方法而不是改回 {@code VALUE}（否则整数脚本会再次崩）。</p>
     */
    @Override
    public Object eval(String script, List<String> keys, List<String> args) {
        String[] keyArray = keys.toArray(new String[0]);
        String[] argArray = args.toArray(new String[0]);
        return call(() -> sync.eval(script, ScriptOutputType.INTEGER, keyArray, argArray),
                String.join(",", keys));
    }

    @Override
    public void close() {
        try {
            connection.close();
        } finally {
            client.shutdown();
        }
    }

    /** 统一异常映射：(键/脚本标识) → {@link SessionStoreUnavailableException}（fail-closed）。 */
    private <T> T call(java.util.function.Supplier<T> action, String target) {
        try {
            return action.get();
        } catch (SessionStoreUnavailableException e) {
            throw e;
        } catch (RuntimeException e) {
            throw new SessionStoreUnavailableException("会话存储不可用（redis 操作失败："
                    + mask(target) + "）", e);
        }
    }

    /** 只保留键前缀用于排障（键值/凭据一律不进日志与异常消息）。 */
    private static String mask(String target) {
        int cut = target.indexOf('{');
        int colon = target.lastIndexOf(':', cut < 0 ? target.length() : cut);
        if (colon > 0) {
            return target.substring(0, colon + 1) + "{...}";
        }
        return target;
    }
}

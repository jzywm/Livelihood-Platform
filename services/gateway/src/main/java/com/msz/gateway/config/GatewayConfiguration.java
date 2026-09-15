package com.msz.gateway.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.msz.gateway.auth.InMemoryRevocationStore;
import com.msz.gateway.auth.JwtVerifier;
import com.msz.gateway.auth.RevocationStore;
import com.msz.gateway.error.GatewayErrorWebExceptionHandler;
import com.msz.gateway.filter.JwtAuthFilter;
import com.msz.gateway.filter.TraceIdFilter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;

import java.util.Set;

/**
 * 网关装配:配置绑定与启动校验,以及全局 Filter、错误处理器与存储实现注册。
 */
@Configuration
@EnableConfigurationProperties({GatewayProperties.class, GatewayOpsProperties.class})
public class GatewayConfiguration {

    /** 启动 fail-fast:REDIS 模式缺少 JWT 密钥直接拒绝启动(见 GatewayProperties.validate)。 */
    @Bean
    GatewayPropertiesValidator gatewayPropertiesValidator(GatewayProperties properties) {
        return new GatewayPropertiesValidator(properties);
    }

    /** traceId 注入(F5,order -10,鉴权链最前端)。 */
    @Bean
    TraceIdFilter traceIdFilter() {
        return new TraceIdFilter();
    }

    /** 前门净化(order -20,先于 traceId):无条件剥离伪造身份头 + 路径规范化(审查 C1/C2)。 */
    @Bean
    com.msz.gateway.filter.RequestSanitizerFilter requestSanitizerFilter(
            com.msz.gateway.error.EnvelopeResponses responses) {
        return new com.msz.gateway.filter.RequestSanitizerFilter(responses);
    }

    /** 统一 Envelope 错误输出(D10/F5),替代 Boot 默认 whitelabel。 */
    @Bean
    GatewayErrorWebExceptionHandler gatewayErrorWebExceptionHandler(ObjectMapper mapper) {
        return new GatewayErrorWebExceptionHandler(mapper);
    }

    /** 统一 Envelope 响应写出器:过滤器对客户端错误(401/404/429)直接短路写出。 */
    @Bean
    com.msz.gateway.error.EnvelopeResponses envelopeResponses(ObjectMapper mapper) {
        return new com.msz.gateway.error.EnvelopeResponses(mapper);
    }

    /** 统一鉴权链(F2,order 0):验签(含令牌策略)+ 吊销 + 四头透传。 */
    @Bean
    JwtAuthFilter jwtAuthFilter(GatewayProperties properties, RevocationStore revocationStore,
                                com.msz.gateway.error.EnvelopeResponses responses) {
        JwtVerifier verifier = new JwtVerifier(
                properties.auth().accessTokenMaxTtl(), properties.auth().clockSkew());
        return new JwtAuthFilter(verifier, properties.auth().jwtSecret(),
                revocationStore, Set.copyOf(properties.auth().whitelist()), responses);
    }

    /** 网关级限流(F3,order 10):IP/账号/接口三级固定窗口桶。 */
    @Bean
    com.msz.gateway.filter.RateLimitFilter rateLimitFilter(
            com.msz.gateway.ratelimit.RateLimiter rateLimiter, GatewayProperties properties,
            com.msz.gateway.error.EnvelopeResponses responses,
            @Value("${gateway.rate-limit.trust-forwarded-for:true}") boolean trustForwardedFor) {
        return new com.msz.gateway.filter.RateLimitFilter(rateLimiter, properties, responses, trustForwardedFor);
    }

    /** 路由级超时(F4,order 100):metadata.timeout 分级,超时 503+5002。 */
    @Bean
    com.msz.gateway.filter.TimeoutFilter timeoutFilter() {
        return new com.msz.gateway.filter.TimeoutFilter();
    }

    /** 内部接口守卫(order 5):x-external-interfaces 网关不可达(404+3006)。 */
    @Bean
    com.msz.gateway.filter.InternalPathGuardFilter internalPathGuardFilter(
            GatewayProperties properties, com.msz.gateway.error.EnvelopeResponses responses) {
        return new com.msz.gateway.filter.InternalPathGuardFilter(properties, responses);
    }

    // ---------- 存储实现(gateway.store=redis|memory) ----------

    /** 生产:Redis 吊销名单(fail-closed)。 */
    @Bean
    @ConditionalOnProperty(name = "gateway.store", havingValue = "redis")
    RevocationStore redisRevocationStore(com.msz.gateway.redis.GatewayRedisOps redis) {
        return new com.msz.gateway.auth.RedisRevocationStore(redis);
    }

    /** 开发兜底:内存吊销名单(M1 无 Redis 部署,同 acc 惯例)。 */
    @Bean
    @ConditionalOnProperty(name = "gateway.store", havingValue = "memory")
    RevocationStore inMemoryRevocationStore() {
        return new InMemoryRevocationStore();
    }

    // ---------- 限流实现(gateway.store=redis|memory) ----------

    /** 生产:Redis+Lua 限流器(脚本 classpath:lua/rate-limit.lua)。 */
    @Bean
    @ConditionalOnProperty(name = "gateway.store", havingValue = "redis")
    com.msz.gateway.ratelimit.RateLimiter redisLuaRateLimiter(com.msz.gateway.redis.GatewayRedisOps redis) {
        return new com.msz.gateway.ratelimit.RedisLuaRateLimiter(redis, loadRateLimitScript());
    }

    /** 开发兜底:内存限流器。 */
    @Bean
    @ConditionalOnProperty(name = "gateway.store", havingValue = "memory")
    com.msz.gateway.ratelimit.RateLimiter inMemoryRateLimiter() {
        return new com.msz.gateway.ratelimit.InMemoryRateLimiter();
    }

    private String loadRateLimitScript() {
        try (var in = getClass().getClassLoader().getResourceAsStream("lua/rate-limit.lua")) {
            if (in == null) {
                throw new IllegalStateException("classpath:lua/rate-limit.lua 缺失");
            }
            return new String(in.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        } catch (java.io.IOException e) {
            throw new IllegalStateException("lua/rate-limit.lua 读取失败", e);
        }
    }

    // ---------- Redis 基础设施(gateway.store=redis 时自建,不用 starter 自动装配) ----------

    /**
     * Redis 连接工厂(REDIS 模式自建):连接/命令超时有界 —— 依赖故障时快速 fail-closed(503+5003),
     * 而不是让请求长时间挂起(默认命令超时 60s 不可接受)。
     */
    @Bean
    @ConditionalOnProperty(name = "gateway.store", havingValue = "redis")
    LettuceConnectionFactory gatewayRedisConnectionFactory(
            @Value("${spring.data.redis.host:localhost}") String host,
            @Value("${spring.data.redis.port:6379}") int port,
            @Value("${spring.data.redis.username:}") String username,
            @Value("${spring.data.redis.password:}") String password,
            @Value("${spring.data.redis.timeout:2000ms}") java.time.Duration commandTimeout,
            @Value("${spring.data.redis.connect-timeout:1000ms}") java.time.Duration connectTimeout) {
        io.lettuce.core.ClientOptions clientOptions = io.lettuce.core.ClientOptions.builder()
                .socketOptions(io.lettuce.core.SocketOptions.builder()
                        .connectTimeout(connectTimeout)
                        .build())
                .build();
        org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration clientConfiguration =
                org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration.builder()
                        .commandTimeout(commandTimeout)
                        .clientOptions(clientOptions)
                        .build();
        org.springframework.data.redis.connection.RedisStandaloneConfiguration standalone =
                new org.springframework.data.redis.connection.RedisStandaloneConfiguration(host, port);
        // 生产 Redis 通常开启 AUTH(审查 I6):支持用户名(ACL)/密码
        if (username != null && !username.isBlank()) {
            standalone.setUsername(username);
        }
        if (password != null && !password.isBlank()) {
            standalone.setPassword(org.springframework.data.redis.connection.RedisPassword.of(password));
        }
        LettuceConnectionFactory factory = new LettuceConnectionFactory(standalone, clientConfiguration);
        factory.afterPropertiesSet();
        return factory;
    }

    @Bean
    @ConditionalOnProperty(name = "gateway.store", havingValue = "redis")
    ReactiveStringRedisTemplate gatewayReactiveStringRedisTemplate(LettuceConnectionFactory factory) {
        return new ReactiveStringRedisTemplate(factory);
    }

    @Bean
    @ConditionalOnProperty(name = "gateway.store", havingValue = "redis")
    com.msz.gateway.redis.GatewayRedisOps gatewayRedisOps(ReactiveStringRedisTemplate template) {
        return new com.msz.gateway.redis.LettuceGatewayRedisOps(template);
    }

    /** 校验器以 Bean 生命周期触发(InitializingBean),保证属性绑定完成后、对外服务前执行。 */
    public static final class GatewayPropertiesValidator implements org.springframework.beans.factory.InitializingBean {

        private final GatewayProperties properties;

        GatewayPropertiesValidator(GatewayProperties properties) {
            this.properties = properties;
        }

        @Override
        public void afterPropertiesSet() {
            GatewayProperties.validate(properties);
        }
    }
}

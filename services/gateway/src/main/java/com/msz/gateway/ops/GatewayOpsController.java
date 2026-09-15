package com.msz.gateway.ops;

import com.msz.gateway.config.GatewayProperties;
import com.msz.gateway.redis.GatewayRedisOps;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.handler.predicate.PredicateDefinition;
import org.springframework.cloud.gateway.route.RouteDefinition;
import org.springframework.cloud.gateway.route.RouteDefinitionLocator;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.net.InetAddress;
import java.net.URI;
import java.net.URISyntaxException;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 运维接口(F7/8.1/8.2):健康检查与路由状态查询(无业务数据)。
 *
 * <ul>
 *   <li>{@code GET /gateway/health}:status / redis / version / instanceId;Redis 不可用或依赖
 *       DOWN 时返回 HTTP 503(供 LB 摘除实例)。</li>
 *   <li>{@code GET /gateway/routes}:当前路由表摘要(id/order/uri 脱敏/predicates/timeout/weight),
 *       URI 中的账号口令(若有)一律脱敏,不输出内网明文凭据。</li>
 * </ul>
 */
@RestController
public class GatewayOpsController {

    public static final String HEALTH_PATH = "/gateway/health";
    public static final String ROUTES_PATH = "/gateway/routes";

    private static final Duration PING_TIMEOUT = Duration.ofMillis(500);

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(GatewayOpsController.class);

    private final GatewayProperties properties;
    private final Optional<GatewayRedisOps> redis;
    private final RouteDefinitionLocator routeDefinitionLocator;
    private final String version;
    private final String instanceId;
    private final List<String> allowedNetworks;

    /** Spring 装配:allowedNetworks 来自 `gateway.ops.allowed-networks`(审查 I8)。 */
    @org.springframework.beans.factory.annotation.Autowired
    public GatewayOpsController(GatewayProperties properties,
                                com.msz.gateway.config.GatewayOpsProperties opsProperties,
                                Optional<GatewayRedisOps> redis,
                                RouteDefinitionLocator routeDefinitionLocator,
                                @Value("${gateway.version:dev}") String version,
                                @Value("${gateway.instance-id:local}") String instanceId) {
        this(properties, redis, routeDefinitionLocator, version, instanceId,
                opsProperties.allowedNetworksOrDefault());
    }

    /** 单测便捷构造:allowedNetworks == null 时取默认内网网段。 */
    public GatewayOpsController(GatewayProperties properties,
                                Optional<GatewayRedisOps> redis,
                                RouteDefinitionLocator routeDefinitionLocator,
                                String version,
                                String instanceId,
                                List<String> allowedNetworks) {
        this.properties = properties;
        this.redis = redis;
        this.routeDefinitionLocator = routeDefinitionLocator;
        this.version = version;
        this.instanceId = instanceId;
        this.allowedNetworks = allowedNetworks != null
                ? List.copyOf(allowedNetworks)
                : com.msz.gateway.ops.Networks.defaultAllowedNetworks();
    }

    /** 来源不在允许网段 → 404(不暴露运维接口存在性)。 */
    private boolean callerAllowed(ServerWebExchange exchange) {
        InetAddress remote = exchange.getRequest().getRemoteAddress() == null
                ? null : exchange.getRequest().getRemoteAddress().getAddress();
        String ip = remote == null ? "" : remote.getHostAddress();
        if (ip.isEmpty()) {
            // 传输层地址由服务器填充,真实 HTTP 场景不会缺失;缺失(如内嵌/单测)视为不可判定,交由网络层保证
            return true;
        }
        boolean allowed = Networks.allowed(allowedNetworks, ip);
        if (!allowed) {
            log.warn("运维接口拒绝非内网来源访问 ip={} path={}", ip, exchange.getRequest().getPath().value());
        }
        return allowed;
    }

    @GetMapping(HEALTH_PATH)
    public Mono<ResponseEntity<Map<String, Object>>> health(ServerWebExchange exchange) {
        if (!callerAllowed(exchange)) {
            return Mono.just(ResponseEntity.status(HttpStatus.NOT_FOUND).body(body("UNKNOWN", "unknown")));
        }
        if (properties.store() == GatewayProperties.Store.MEMORY || redis.isEmpty()) {
            return Mono.just(ResponseEntity.ok(body("UP", "memory")));
        }
        return redis.get().ping()
                .timeout(PING_TIMEOUT)
                .map(pong -> ResponseEntity.ok(body("UP", "up")))
                .onErrorResume(e -> Mono.just(ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                        .body(body("DOWN", "down"))));
    }

    @GetMapping(ROUTES_PATH)
    public Mono<Map<String, Object>> routes(ServerWebExchange exchange) {
        if (!callerAllowed(exchange)) {
            return Mono.just(Map.of("routes", List.of()));
        }
        return routeDefinitionLocator.getRouteDefinitions()
                .map(this::summarize)
                .collectList()
                .map(list -> Map.of("routes", list));
    }

    private Map<String, Object> body(String status, String redisState) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", status);
        body.put("redis", redisState);
        body.put("version", version);
        body.put("instanceId", instanceId);
        return body;
    }

    private Map<String, Object> summarize(RouteDefinition definition) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("id", definition.getId());
        summary.put("order", definition.getOrder());
        summary.put("uri", sanitize(definition.getUri()));
        List<PredicateDefinition> predicates = definition.getPredicates();
        if (predicates != null && !predicates.isEmpty()) {
            summary.put("predicates", predicates.stream().map(this::describe).toList());
        }
        Map<String, Object> metadata = definition.getMetadata();
        if (metadata != null) {
            if (metadata.get("timeout") != null) {
                summary.put("timeout", metadata.get("timeout"));
            }
            if (metadata.get("weight") != null) {
                summary.put("weight", metadata.get("weight"));
            }
        }
        return summary;
    }

    /** 谓词摘要:单参数渲染为快捷式 {@code Path=/api/v1/acc/**},多参数渲染为 name + 参数表。 */
    private String describe(PredicateDefinition definition) {
        Map<String, String> args = definition.getArgs();
        if (args == null || args.isEmpty()) {
            return definition.getName();
        }
        if (args.size() == 1) {
            return definition.getName() + "=" + args.values().iterator().next();
        }
        return definition.getName() + args;
    }

    /** URI 脱敏:剥离 userInfo(账号口令),仅保留 scheme/host/port/path。 */
    private String sanitize(URI uri) {
        if (uri == null) {
            return null;
        }
        if (uri.getUserInfo() == null) {
            return uri.toString();
        }
        try {
            return new URI(uri.getScheme(), null, uri.getHost(), uri.getPort(),
                    uri.getPath(), uri.getQuery(), uri.getFragment()).toString();
        } catch (URISyntaxException e) {
            return uri.getScheme() + "://" + uri.getHost();
        }
    }
}

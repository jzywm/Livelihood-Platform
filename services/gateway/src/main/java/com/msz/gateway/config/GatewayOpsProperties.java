package com.msz.gateway.config;

import com.msz.gateway.ops.Networks;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;

/**
 * 运维接口配置(审查 I8):`gateway.ops.*`。
 *
 * <p>运维接口(`/gateway/health`、`/gateway/routes`)不经网关过滤器链(由网关自身 Controller 处理),
 * 因此访问控制在本配置中声明——默认仅回环 + 私有网段可达;对外入口 Nginx 亦不应暴露 `/gateway/**`。</p>
 */
@ConfigurationProperties(prefix = "gateway.ops")
public record GatewayOpsProperties(List<String> allowedNetworks) {

    /** 默认放行网段:回环 + 私有网段。 */
    public static GatewayOpsProperties defaults() {
        return new GatewayOpsProperties(Networks.defaultAllowedNetworks());
    }

    /** 未配置时取默认网段(留空列表 = 不限制,由网络层保证)。 */
    public List<String> allowedNetworksOrDefault() {
        return allowedNetworks != null ? allowedNetworks : Networks.defaultAllowedNetworks();
    }
}

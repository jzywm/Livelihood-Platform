package com.msz.gateway.ops;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 运维接口来源网段校验(审查 I8)。
 */
class NetworksTest {

    @Test
    void matchesIpv4Cidr() {
        assertThat(Networks.contains("10.0.0.0/8", "10.1.2.3")).isTrue();
        assertThat(Networks.contains("10.0.0.0/8", "11.1.2.3")).isFalse();
        assertThat(Networks.contains("192.168.0.0/16", "192.168.31.7")).isTrue();
        assertThat(Networks.contains("192.168.0.0/16", "192.169.0.1")).isFalse();
        assertThat(Networks.contains("172.16.0.0/12", "172.20.5.5")).isTrue();
        assertThat(Networks.contains("172.16.0.0/12", "172.32.5.5")).isFalse();
    }

    @Test
    void matchesExactIpAndLoopback() {
        assertThat(Networks.contains("127.0.0.1/32", "127.0.0.1")).isTrue();
        assertThat(Networks.contains("127.0.0.1/32", "127.0.0.2")).isFalse();
        assertThat(Networks.contains("203.0.113.5", "203.0.113.5")).isTrue();
        assertThat(Networks.contains("::1/128", "::1")).isTrue();
    }

    @Test
    void rejectsMalformedRulesAndInput() {
        assertThat(Networks.contains("10.0.0.0/abc", "10.0.0.1")).isFalse();
        assertThat(Networks.contains("10.0.0.0/33", "10.0.0.1")).isFalse();
        assertThat(Networks.contains(null, "10.0.0.1")).isFalse();
        assertThat(Networks.contains("10.0.0.0/8", null)).isFalse();
    }

    @Test
    void allowedListSemantics() {
        List<String> privateOnly = Networks.defaultAllowedNetworks();
        assertThat(Networks.allowed(privateOnly, "10.0.0.7")).isTrue();
        assertThat(Networks.allowed(privateOnly, "127.0.0.1")).isTrue();
        assertThat(Networks.allowed(privateOnly, "203.0.113.9")).isFalse();
        // 未配置 = 不限制(由网络层保证内网)
        assertThat(Networks.allowed(List.of(), "203.0.113.9")).isTrue();
    }

    @Test
    void defaultListCoversPrivateRanges() {
        assertThat(Networks.defaultAllowedNetworks())
                .contains("127.0.0.1/32", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16");
    }
}

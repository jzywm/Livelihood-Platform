package com.msz.gateway.ops;

import java.net.InetAddress;
import java.net.UnknownHostException;

/**
 * 运维接口来源网段校验(审查 I8):运维接口仅内网可达,支持 IPv4 CIDR / 精确 IP / IPv6 回环。
 *
 * <p>默认放行:127.0.0.1/32、::1/128、10.0.0.0/8、172.16.0.0/12、192.168.0.0/16
 * (内网与回环);对外入口 Nginx 亦不应暴露 `/gateway/**`。</p>
 */
public final class Networks {

    private Networks() {
    }

    /** 默认放行网段:回环 + 私有网段(生产建议显式配置为入口 Nginx / 运维网段)。 */
    public static java.util.List<String> defaultAllowedNetworks() {
        return java.util.List.of("127.0.0.1/32", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16");
    }

    /** 判断 {@code ip} 是否落在 {@code cidr}(如 {@code 10.0.0.0/8};也接受精确 IP 字面量)内。 */
    public static boolean contains(String cidr, String ip) {
        if (cidr == null || ip == null || cidr.isBlank() || ip.isBlank()) {
            return false;
        }
        String rule = cidr.trim();
        String candidate = ip.trim();
        int slash = rule.indexOf('/');
        if (slash < 0) {
            return normalize(rule).equals(normalize(candidate));
        }
        String network = rule.substring(0, slash);
        int prefix;
        try {
            prefix = Integer.parseInt(rule.substring(slash + 1).trim());
        } catch (NumberFormatException e) {
            return false;
        }
        byte[] networkBytes = toBytes(network);
        byte[] candidateBytes = toBytes(candidate);
        if (networkBytes == null || candidateBytes == null || networkBytes.length != candidateBytes.length) {
            return false;
        }
        int bits = networkBytes.length * 8;
        if (prefix < 0 || prefix > bits) {
            return false;
        }
        int fullBytes = prefix / 8;
        int remainderBits = prefix % 8;
        for (int i = 0; i < fullBytes; i++) {
            if (networkBytes[i] != candidateBytes[i]) {
                return false;
            }
        }
        if (remainderBits == 0) {
            return true;
        }
        int mask = 0xFF << (8 - remainderBits);
        return (networkBytes[fullBytes] & mask) == (candidateBytes[fullBytes] & mask);
    }

    /** 命中任一网段即放行;规则列表为空视为放行(未配置 = 不限制,由网络层保证)。 */
    public static boolean allowed(java.util.List<String> cidrs, String ip) {
        if (cidrs == null || cidrs.isEmpty()) {
            return true;
        }
        return cidrs.stream().anyMatch(cidr -> contains(cidr, ip));
    }

    private static String normalize(String ip) {
        byte[] bytes = toBytes(ip);
        if (bytes == null) {
            return ip;
        }
        try {
            return InetAddress.getByAddress(bytes).getHostAddress();
        } catch (UnknownHostException e) {
            return ip;
        }
    }

    private static byte[] toBytes(String ip) {
        String candidate = ip.contains("%") ? ip.substring(0, ip.indexOf('%')) : ip;
        try {
            return InetAddress.getByName(candidate).getAddress();
        } catch (UnknownHostException e) {
            return null;
        }
    }
}

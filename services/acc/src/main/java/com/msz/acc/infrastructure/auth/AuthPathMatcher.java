package com.msz.acc.infrastructure.auth;

import java.util.Set;

/**
 * 服务内白名单的**路径段边界**匹配（任务 4.2，与网关 {@code RequestPaths.matchesPrefix} 同语义）。
 *
 * <p>原实现用 {@code String.startsWith}：把会话端点加进白名单后，{@code /acc/auth/loginAny}
 * 会连带命中 {@code /acc/auth/login} 前缀——对「网关为唯一鉴权点」的信任模型来说，服务内白名单
 * 是**纵深防御**的一层，前缀匹配会把这一层变成绕过点。故改为段边界：命中白名单项本身或其子路径。</p>
 *
 * <p>与网关保持同语义（而非更严的「仅精确相等」）是刻意的：网关先按同一规则放行，服务内若更严，
 * 会出现「网关放行、服务内 401」的口径分裂。</p>
 *
 * <p><b>混淆路径</b>：WebFlux 的规范化在网关侧完成，但服务内不能假设「请求一定经过规范化」——
 * 本类另行拒绝含 {@code .}/{@code ..}/空段（{@code //}）/反斜杠的路径。动机：容器在匹配路由前
 * 会先解析 {@code ..}，而白名单判断用的是**原始** {@code getRequestURI()}，二者口径不一致时
 * {@code /acc/auth/login/../me} 会「按白名单放行、却路由到 /acc/me」——即绕过点（纵深防御要求拒绝）。</p>
 */
final class AuthPathMatcher {

    private AuthPathMatcher() {
    }

    /** 请求路径是否命中白名单集合中任一项（项本身或其段边界子路径）。 */
    static boolean matchesAny(String path, Set<String> prefixes) {
        if (path == null || isConfusing(path)) {
            return false;
        }
        for (String prefix : prefixes) {
            if (matchesPrefix(path, prefix)) {
                return true;
            }
        }
        return false;
    }

    /** 段边界前缀匹配：{@code /a/b} 命中 {@code /a/b} 与 {@code /a/b/c}，不命中 {@code /a/bc}。 */
    static boolean matchesPrefix(String path, String prefix) {
        if (path == null || prefix == null || prefix.isEmpty()) {
            return false;
        }
        String base = prefix.endsWith("/") ? prefix.substring(0, prefix.length() - 1) : prefix;
        if (base.isEmpty()) {
            return true;
        }
        return path.equals(base) || path.startsWith(base + "/");
    }

    /** 路径混淆判据：含 {@code .}/{@code ..} 段、空段（{@code //}）或反斜杠。 */
    static boolean isConfusing(String path) {
        if (path.indexOf('\\') >= 0) {
            return true;
        }
        String[] segments = path.split("/", -1);
        for (int i = 0; i < segments.length; i++) {
            String segment = segments[i];
            if (segment.isEmpty()) {
                // 允许首/尾斜杠（/acc/me/ 归一化），中间空段（//）视为混淆
                boolean leading = i == 0;
                boolean trailing = i == segments.length - 1;
                if (!leading && !trailing) {
                    return true;
                }
                continue;
            }
            if (".".equals(segment) || "..".equals(segment)) {
                return true;
            }
        }
        return false;
    }
}

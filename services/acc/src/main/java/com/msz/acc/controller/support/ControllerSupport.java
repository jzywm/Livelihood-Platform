package com.msz.acc.controller.support;

import com.msz.acc.domain.support.AccBusinessException;
import com.msz.acc.infrastructure.auth.AccessDeniedException;
import com.msz.acc.infrastructure.auth.AuthContext;
import com.msz.acc.infrastructure.auth.AuthException;
import com.msz.acc.infrastructure.auth.FundsGuard;
import jakarta.servlet.http.HttpServletRequest;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.Set;

/**
 * 控制器公共校验（S5）：鉴权上下文/账户 ID、监管角色二次鉴权、内部 Token、日期解析、枚举口径。
 */
public final class ControllerSupport {

    public static final String INTERNAL_TOKEN_HEADER = "X-Internal-Token";
    public static final String ATTR_AUTH_CONTEXT = "authContext";

    public static final Set<String> ROLES =
            Set.of("CONSUMER", "MERCHANT", "SUPPLIER", "WORKER", "REGULATOR", "OPERATOR");
    public static final Set<String> FLOW_TYPES = Set.of("PAYROLL", "SERVICE_FEE", "SPLIT", "REFUND", "OTHER");
    public static final Set<String> CHANNELS = Set.of("WECHAT", "ALIPAY");
    public static final Set<String> DIRECTIONS = Set.of("IN", "OUT");

    private ControllerSupport() {
    }

    public static AuthContext requireAuth(HttpServletRequest request) {
        Object value = request.getAttribute(ATTR_AUTH_CONTEXT);
        if (!(value instanceof AuthContext ctx)) {
            throw new AuthException("缺少鉴权上下文");
        }
        return ctx;
    }

    /** 账户 ID（JWT sub）解析：非法 → AuthException（2001）。 */
    public static long accountIdOf(AuthContext ctx) {
        try {
            return Long.parseLong(ctx.accountId());
        } catch (NumberFormatException e) {
            throw new AuthException("账户 ID 非法");
        }
    }

    /** 监管二次鉴权：仅 REGULATOR（否则 403/2002）。 */
    public static void requireRegulator(AuthContext ctx) {
        if (!FundsGuard.canAccessFunds(ctx)) {
            throw new AccessDeniedException("仅监管角色可访问资金审计/对账");
        }
    }

    /** 内部接口鉴权：X-Internal-Token 必须匹配配置，不匹配 → 403（2002）。 */
    public static void requireInternalToken(HttpServletRequest request, String expectedToken) {
        String actual = request.getHeader(INTERNAL_TOKEN_HEADER);
        if (expectedToken == null || !expectedToken.equals(actual)) {
            throw new AccessDeniedException("内部接口仅内网可调（X-Internal-Token 校验失败）");
        }
    }

    /** 可选日期参数解析：空白 → null；非法 → 1002。 */
    public static LocalDate parseDate(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(value);
        } catch (DateTimeParseException e) {
            throw new AccBusinessException(1002, "日期格式非法（ISO 8601 yyyy-MM-dd）");
        }
    }
}

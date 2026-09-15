package com.msz.common.api;

/**
 * 平台统一业务码（分段）：0 成功 / 1xxx 参数校验 / 2xxx 鉴权权限 / 3xxx 业务规则 / 4xxx 第三方依赖 / 5xxx 系统。
 * 码值与默认文案口径对齐 {@code services/_common/openapi.yaml}（错误码权威源）。
 */
public final class ErrorCode {

    private ErrorCode() {
    }

    // 0 成功
    public static final int OK = 0;

    // 1xxx 参数校验
    public static final int PARAM_MISSING = 1001;
    public static final int PARAM_FORMAT = 1002;
    public static final int PARAM_RANGE = 1003;

    // 2xxx 鉴权权限
    public static final int UNAUTHORIZED = 2001;
    public static final int FORBIDDEN = 2002;
    public static final int MFA_REQUIRED = 2003;
    public static final int RATE_LIMITED = 2004;

    // 3xxx 业务规则
    public static final int REALNAME_INCOMPLETE = 3001;
    public static final int REALNAME_MISMATCH = 3002;
    public static final int LICENSE_FAILED = 3003;
    public static final int CREDIT_INSUFFICIENT = 3004;
    public static final int MERCHANT_NOT_ONBOARDED = 3005;
    public static final int OBJECT_NOT_FOUND = 3006;
    public static final int STATUS_NOT_ALLOWED = 3007;
    public static final int IDEMPOTENCY_CONFLICT = 3008;
    public static final int RECONCILE_DIFF = 3009;
    public static final int MINOR_VIOLATION = 3010;
    public static final int CONTENT_VIOLATION = 3011;

    // 4xxx 第三方依赖
    public static final int THIRD_PARTY_REALNAME_FAILED = 4001;
    public static final int CHANNEL_FAILED = 4002;
    public static final int AI_API_FAILED = 4003;
    public static final int SMS_FAILED = 4004;

    // 5xxx 系统
    public static final int INTERNAL_ERROR = 5000;
    public static final int DB_ERROR = 5001;
    public static final int DEPENDENCY_TIMEOUT = 5002;
    public static final int GATEWAY_UNAVAILABLE = 5003;

    /** 默认文案（取自 openapi.yaml 错误码 message 口径）。 */
    public static String message(int code) {
        return switch (code) {
            case OK -> "成功";
            case PARAM_MISSING -> "参数缺失";
            case PARAM_FORMAT -> "参数格式错误";
            case PARAM_RANGE -> "枚举/范围非法";
            case UNAUTHORIZED -> "未登录 / Token 失效";
            case FORBIDDEN -> "无权限 / 越权";
            case MFA_REQUIRED -> "MFA 未通过";
            case RATE_LIMITED -> "请求过于频繁";
            case REALNAME_INCOMPLETE -> "实名未完成";
            case REALNAME_MISMATCH -> "实名不匹配";
            case LICENSE_FAILED -> "证照核验不通过";
            case CREDIT_INSUFFICIENT -> "信用分不足";
            case MERCHANT_NOT_ONBOARDED -> "商户未入驻";
            case OBJECT_NOT_FOUND -> "对象不存在";
            case STATUS_NOT_ALLOWED -> "状态不允许该操作";
            case IDEMPOTENCY_CONFLICT -> "幂等键冲突";
            case RECONCILE_DIFF -> "资金对账不一致";
            case MINOR_VIOLATION -> "违规对象（未成年人）";
            case CONTENT_VIOLATION -> "内容违规（敏感词/合规）";
            case THIRD_PARTY_REALNAME_FAILED -> "实名接口失败";
            case CHANNEL_FAILED -> "支付通道失败 / 超时";
            case AI_API_FAILED -> "大模型 / 视觉 API 失败";
            case SMS_FAILED -> "短信通道失败";
            case INTERNAL_ERROR -> "内部错误";
            case DB_ERROR -> "数据库错误";
            case DEPENDENCY_TIMEOUT -> "依赖超时 / 熔断";
            case GATEWAY_UNAVAILABLE -> "网关暂不可用";
            default -> "未知错误";
        };
    }
}

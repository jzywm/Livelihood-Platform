package com.msz.common.api;

/**
 * 分页与幂等约定常量（对齐 {@code services/_common/openapi.yaml}）。
 */
public final class ApiConventions {

    private ApiConventions() {
    }

    /** 幂等键请求头：资金类写操作强制。 */
    public static final String IDEMPOTENCY_KEY_HEADER = "Idempotency-Key";

    /** 默认页码（从 1 开始）。 */
    public static final int DEFAULT_PAGE = 1;

    /** 默认每页条数。 */
    public static final int DEFAULT_PAGE_SIZE = 20;

    /** 每页条数上限。 */
    public static final int MAX_PAGE_SIZE = 100;
}

package com.msz.common.api;

import java.util.List;

/**
 * 统一分页结果（放在 Envelope.data 内）。
 */
public record PageResult<T>(List<T> list, long total, int page, int pageSize) {
}

package com.msz.acc.domain.service;

import java.time.Instant;

/**
 * 记账流水哈希链节点（er.md §6.3：hash = SHA-256(前链 hash + 行数据 + 时间戳)，R-04 只增不改可出证）。
 *
 * @param flowId    流水 ID（雪花 ID）
 * @param rowData   参与哈希的行数据摘要（类型/方向/金额/通道交易号等业务字段拼接）
 * @param occurredAt 资金发生时间（UTC）
 * @param hash      本行存证哈希
 */
public record HashChainEntry(String flowId, String rowData, Instant occurredAt, String hash) {
}

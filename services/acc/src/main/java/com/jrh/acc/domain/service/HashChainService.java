package com.msz.acc.domain.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;

/**
 * 存证哈希链：SHA-256 哈希链，R-04 流水只增不改、可出证。
 * 口径：er.md §6.3 hash 列（SHA-256(前链 hash + 行数据 + 时间戳)）+ test-plan.md UT-B01/B02。
 */
public final class HashChainService {

    private static final String GENESIS_PAYLOAD = "GENESIS";

    /** 计算存证哈希：SHA-256(前链 hash + 行数据 + 时间戳)。 */
    public String compute(String prevHash, String rowData, Instant occurredAt) {
        String payload = prevHash + "|" + rowData + "|" + occurredAt.toEpochMilli();
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(payload.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(bytes);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    /** 创世哈希（首行流水的前链基准）。 */
    public String genesisHash() {
        return compute("", GENESIS_PAYLOAD, Instant.EPOCH);
    }

    /**
     * 校验整链：首行前链必须等于创世哈希，其后每行按「前一行 hash + 行数据 + 时间戳」重算比对。
     * 断链抛 {@link ChainVerificationException}，携带断链下标（0 起）。
     */
    public void verify(List<HashChainEntry> chain) {
        String prevHash = genesisHash();
        for (int i = 0; i < chain.size(); i++) {
            HashChainEntry entry = chain.get(i);
            String expected = compute(prevHash, entry.rowData(), entry.occurredAt());
            if (!expected.equals(entry.hash())) {
                throw new ChainVerificationException(i, "哈希链断链：第 " + i + " 行哈希不匹配");
            }
            prevHash = entry.hash();
        }
    }
}

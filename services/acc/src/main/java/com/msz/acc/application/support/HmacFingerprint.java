package com.msz.acc.application.support;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * 手机号指纹工具：SHA-256 十六进制（64 字符），对齐 account.mobile_hash varchar(64) 辅助列。
 * 说明：er.md 称「HMAC-SHA256 指纹」，但 S4 工具签名为单参 {@code sha256Hex(String)}（无密钥），
 * 故按 SHA-256 实现；带密钥的 HMAC 变体待密钥管理（KMS）落地后扩展。
 */
public final class HmacFingerprint {

    private HmacFingerprint() {
    }

    public static String sha256Hex(String input) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(input.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(bytes);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }
}

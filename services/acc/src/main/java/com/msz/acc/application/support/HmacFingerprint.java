package com.msz.acc.application.support;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.HexFormat;

/**
 * 手机号指纹工具：带密钥的 HMAC-SHA256 十六进制（64 字符），对齐 er.md §7.1「mobile_hash 指纹辅助列」口径。
 * 密钥构造注入（测试用固定测试凭据，生产经 KMS 配置）。
 */
public final class HmacFingerprint {

    private final SecretKeySpec key;

    public HmacFingerprint(String secret) {
        this.key = new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
    }

    public String hmacSha256Hex(String value) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(key);
            byte[] bytes = mac.doFinal(value.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(bytes);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("HMAC-SHA256 不可用", e);
        }
    }
}

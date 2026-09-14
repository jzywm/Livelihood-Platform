package com.msz.acc.infrastructure.crypto;

import com.msz.acc.application.port.SignatureVerifier;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.util.HexFormat;

/**
 * 实名回调验签器（S5）：HMAC-SHA256，密钥来自 {@code acc.callback-secret} 配置（默认测试值）。
 *
 * <p>签名输入为回调规范化 payload（{@code bizId|openId|name|idNo|pass|timestamp|nonce}），
 * 签名输出小写十六进制；验签用常数时间比较。{@link #sign(String)} 供通道模拟/Fake/WireMock
 * 测试共用（服务端从不签发回调签名）。</p>
 */
public final class HmacSignatureVerifier implements SignatureVerifier {

    private final SecretKeySpec key;

    public HmacSignatureVerifier(String secret) {
        this.key = new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
    }

    @Override
    public boolean verify(String payload, String sign) {
        if (payload == null || sign == null || sign.isEmpty()) {
            return false;
        }
        byte[] actual;
        try {
            actual = HexFormat.of().parseHex(sign);
        } catch (IllegalArgumentException e) {
            return false;
        }
        return MessageDigest.isEqual(hmac(payload), actual);
    }

    /** 生成签名（小写十六进制 SHA-256），供 Fake/WireMock 通道模拟共用。 */
    public String sign(String payload) {
        return HexFormat.of().formatHex(hmac(payload));
    }

    private byte[] hmac(String payload) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(key);
            return mac.doFinal(payload.getBytes(StandardCharsets.UTF_8));
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("HMAC-SHA256 不可用", e);
        }
    }
}

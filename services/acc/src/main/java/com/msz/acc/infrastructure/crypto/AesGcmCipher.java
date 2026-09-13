package com.msz.acc.infrastructure.crypto;

import javax.crypto.BadPaddingException;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Base64;

/**
 * AES-256-GCM 加解密器（2.1）。
 *
 * <p>密文格式：{@code base64(iv) + ":" + base64(ciphertext)}，随机 12 字节 IV，
 * GCM 认证标签 128 bit（认证加密，密文不含明文，篡改即解密失败）。
 *
 * <p>轮换兼容：解密时先用 keyId 对应密钥；命中 AEADBadTag/BadPadding（换钥后旧密文场景）
 * 再按 {@link KeyProvider#keyIds()} 顺序逐一尝试其余密钥，过渡期旧密文仍可解（UT-F01）。
 */
public final class AesGcmCipher {

    private static final int IV_LENGTH = 12;
    private static final int TAG_BITS = 128;
    private static final String TRANSFORMATION = "AES/GCM/NoPadding";

    private final KeyProvider keys;
    private final SecureRandom random = new SecureRandom();

    public AesGcmCipher(KeyProvider keys) {
        this.keys = keys;
    }

    /** 加密：随机 IV + AES-256-GCM，输出 base64(iv):base64(ct)。plaintext 为 null 透传 null。 */
    public String encrypt(String keyId, String plaintext) {
        if (plaintext == null) {
            return null;
        }
        SecretKey key = requireKey(keyId);
        byte[] iv = new byte[IV_LENGTH];
        random.nextBytes(iv);
        byte[] ciphertext = encrypt(key, iv, plaintext.getBytes(StandardCharsets.UTF_8));
        return Base64.getEncoder().encodeToString(iv)
                + ":" + Base64.getEncoder().encodeToString(ciphertext);
    }

    /** 解密：keyId 优先，失败按 keyIds() 顺序兜底尝试；全部失败抛 {@link IllegalStateException}。ciphertext 为 null 透传 null。 */
    public String decrypt(String keyId, String ciphertext) {
        if (ciphertext == null) {
            return null;
        }
        String[] parts = ciphertext.split(":", 2);
        if (parts.length != 2) {
            throw new IllegalStateException("非法密文格式：缺少 iv:ct 分隔");
        }
        byte[] iv = decode(parts[0]);
        byte[] ct = decode(parts[1]);

        Throwable last = null;
        SecretKey primary = keys.key(keyId);
        if (primary != null) {
            try {
                return decrypt(primary, iv, ct);
            } catch (BadPaddingException e) {
                last = e;
            }
        }
        for (String otherKeyId : keys.keyIds()) {
            if (otherKeyId.equals(keyId)) {
                continue;
            }
            SecretKey candidate = keys.key(otherKeyId);
            if (candidate == null) {
                continue;
            }
            try {
                return decrypt(candidate, iv, ct);
            } catch (BadPaddingException e) {
                last = e;
            }
        }
        throw new IllegalStateException("AES-256-GCM 解密失败（密钥不匹配或密文被篡改）", last);
    }

    private String decrypt(SecretKey key, byte[] iv, byte[] ct) throws BadPaddingException {
        byte[] plaintext;
        try {
            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            plaintext = cipher.doFinal(ct);
        } catch (BadPaddingException e) {
            // AEADBadTagException 是其子类：密钥不匹配/密文被篡改 → 交给调用方轮换兜底
            throw e;
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("AES-256-GCM 解密失败", e);
        }
        return new String(plaintext, StandardCharsets.UTF_8);
    }

    private byte[] encrypt(SecretKey key, byte[] iv, byte[] plaintext) {
        try {
            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            return cipher.doFinal(plaintext);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("AES-256-GCM 加密失败", e);
        }
    }

    private SecretKey requireKey(String keyId) {
        SecretKey key = keys.key(keyId);
        if (key == null) {
            throw new IllegalArgumentException("未知 keyId: " + keyId);
        }
        return key;
    }

    private byte[] decode(String s) {
        try {
            return Base64.getDecoder().decode(s);
        } catch (IllegalArgumentException e) {
            throw new IllegalStateException("非法 base64 密文", e);
        }
    }
}

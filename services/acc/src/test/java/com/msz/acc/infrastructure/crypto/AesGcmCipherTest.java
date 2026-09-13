package com.msz.acc.infrastructure.crypto;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * UT-F01：AES-256-GCM 加解密 + 密钥轮换兼容。
 */
class AesGcmCipherTest {

    private static final String KEY_OLD = "old";
    private static final String KEY_NEW = "new";

    private static SecretKey aesKey(byte seed) {
        byte[] bytes = new byte[32];
        for (int i = 0; i < bytes.length; i++) {
            bytes[i] = seed;
        }
        return new SecretKeySpec(bytes, "AES");
    }

    private static AesGcmCipher cipherWith(Map<String, SecretKey> keys) {
        return new AesGcmCipher(new FixedKeyProvider(keys));
    }

    @Test
    @DisplayName("UT-F01 AES-256-GCM round-trip")
    void ut_roundTrip() {
        AesGcmCipher cipher = cipherWith(Map.of("k1", aesKey((byte) 1)));
        String plaintext = "13812345678";

        String ciphertext = cipher.encrypt("k1", plaintext);

        assertThat(cipher.decrypt("k1", ciphertext)).isEqualTo(plaintext);
    }

    @Test
    @DisplayName("UT-F01 密文不含明文子串")
    void ut_ciphertextDoesNotContainPlaintext() {
        AesGcmCipher cipher = cipherWith(Map.of("k1", aesKey((byte) 2)));
        String plaintext = "110101199001011234";

        String ciphertext = cipher.encrypt("k1", plaintext);

        assertThat(ciphertext).doesNotContain(plaintext);
        assertThat(ciphertext).doesNotContain("110101");
    }

    @Test
    @DisplayName("UT-F01 同一明文两次加密密文不同（随机 IV）")
    void ut_samePlaintextTwiceProducesDifferentCiphertext() {
        AesGcmCipher cipher = cipherWith(Map.of("k1", aesKey((byte) 3)));
        String plaintext = "secret-payload";

        String c1 = cipher.encrypt("k1", plaintext);
        String c2 = cipher.encrypt("k1", plaintext);

        assertThat(c1).isNotEqualTo(c2);
        assertThat(cipher.decrypt("k1", c1)).isEqualTo(plaintext);
        assertThat(cipher.decrypt("k1", c2)).isEqualTo(plaintext);
    }

    @Test
    @DisplayName("UT-F01 错误 keyId 解密失败（无任何密钥可解）")
    void ut_wrongKeyIdDecryptFails() {
        AesGcmCipher writer = cipherWith(Map.of("k1", aesKey((byte) 4)));
        String ciphertext = writer.encrypt("k1", "secret");

        AesGcmCipher reader = cipherWith(Map.of("k2", aesKey((byte) 5)));

        assertThatThrownBy(() -> reader.decrypt("k2", ciphertext))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    @DisplayName("UT-F01 轮换兼容：换 keyId 后按 keyIds 兜底仍可解")
    void ut_rotation_multiKeyFallback() {
        Map<String, SecretKey> keys = new LinkedHashMap<>();
        keys.put(KEY_OLD, aesKey((byte) 6));
        keys.put(KEY_NEW, aesKey((byte) 7));
        AesGcmCipher cipher = cipherWith(keys);

        String plaintext = "13812345678";
        String ciphertext = cipher.encrypt(KEY_NEW, plaintext);

        // 以旧 keyId 解密（旧钥失败 → 按 keyIds 顺序兜底到新钥）
        assertThat(cipher.decrypt(KEY_OLD, ciphertext)).isEqualTo(plaintext);
    }

    @Test
    @DisplayName("UT-F01 keyIds 多 key 兜底解密（按序尝试）")
    void ut_keyIdsMultiKeyFallbackDecrypt() {
        Map<String, SecretKey> keys = new LinkedHashMap<>();
        keys.put("k1", aesKey((byte) 8));
        keys.put("k2", aesKey((byte) 9));
        keys.put("k3", aesKey((byte) 10));
        AesGcmCipher cipher = cipherWith(keys);

        String plaintext = "id-card-or-card-number";
        String ciphertext = cipher.encrypt("k3", plaintext);

        // 以 k1 解密：k1 失败 → k2 失败 → k3 成功
        assertThat(cipher.decrypt("k1", ciphertext)).isEqualTo(plaintext);
    }
}

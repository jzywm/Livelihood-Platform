package com.msz.acc.infrastructure.crypto;

import org.apache.ibatis.type.JdbcType;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.lang.reflect.Proxy;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * UT-F01 / SEC-02：加密 TypeHandler——参数为密文（不含明文）、读取解密还原、null 透传。
 */
class EncryptedStringTypeHandlerTest {

    private static final String KEY_ID = "k1";

    private static AesGcmCipher cipher() {
        byte[] bytes = new byte[32];
        bytes[0] = 42;
        return new AesGcmCipher(new FixedKeyProvider(Map.of(KEY_ID, new SecretKeySpec(bytes, "AES"))));
    }

    @Test
    @DisplayName("UT-F01 setNonNullParameter 写密文（不含明文）")
    void ut_setNonNullParameterEncryptsWithoutPlaintext() throws Exception {
        AesGcmCipher cipher = cipher();
        EncryptedStringTypeHandler handler = new EncryptedStringTypeHandler(cipher, KEY_ID);
        String plaintext = "13812345678";

        Map<Integer, String> params = new HashMap<>();
        PreparedStatement ps = fakePreparedStatement(params);

        handler.setNonNullParameter(ps, 1, plaintext, JdbcType.VARCHAR);

        String stored = params.get(1);
        assertThat(stored).isNotNull();
        assertThat(stored).doesNotContain(plaintext);
        assertThat(cipher.decrypt(KEY_ID, stored)).isEqualTo(plaintext);
    }

    @Test
    @DisplayName("UT-F01 getNullableResult 解密还原")
    void ut_getNullableResultDecrypts() throws Exception {
        AesGcmCipher cipher = cipher();
        EncryptedStringTypeHandler handler = new EncryptedStringTypeHandler(cipher, KEY_ID);
        String plaintext = "13812345678";
        String ciphertext = cipher.encrypt(KEY_ID, plaintext);

        ResultSet rs = fakeResultSet(ciphertext);

        assertThat(handler.getNullableResult(rs, "mobile")).isEqualTo(plaintext);
        assertThat(handler.getNullableResult(rs, 1)).isEqualTo(plaintext);
    }

    @Test
    @DisplayName("UT-F01 null 透传")
    void ut_nullPassthrough() throws Exception {
        AesGcmCipher cipher = cipher();
        EncryptedStringTypeHandler handler = new EncryptedStringTypeHandler(cipher, KEY_ID);

        ResultSet rs = fakeResultSet(null);

        assertThat(handler.getNullableResult(rs, "mobile")).isNull();
        assertThat(handler.getNullableResult(rs, 1)).isNull();
    }

    private static PreparedStatement fakePreparedStatement(Map<Integer, String> sink) {
        return (PreparedStatement) Proxy.newProxyInstance(
                PreparedStatement.class.getClassLoader(),
                new Class<?>[]{PreparedStatement.class},
                (proxy, method, args) -> {
                    if (method.getName().equals("setString") && args != null && args.length == 2) {
                        sink.put((Integer) args[0], (String) args[1]);
                        return null;
                    }
                    return defaultReturn(method.getReturnType());
                });
    }

    private static ResultSet fakeResultSet(String value) {
        return (ResultSet) Proxy.newProxyInstance(
                ResultSet.class.getClassLoader(),
                new Class<?>[]{ResultSet.class},
                (proxy, method, args) -> {
                    if (method.getName().equals("getString")) {
                        return value;
                    }
                    return defaultReturn(method.getReturnType());
                });
    }

    private static Object defaultReturn(Class<?> type) {
        if (!type.isPrimitive()) {
            return null;
        }
        if (type == boolean.class) {
            return false;
        }
        if (type == int.class || type == long.class || type == short.class || type == byte.class) {
            return 0;
        }
        if (type == double.class || type == float.class) {
            return 0.0;
        }
        if (type == char.class) {
            return '\0';
        }
        return null;
    }
}

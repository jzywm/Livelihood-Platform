package com.msz.acc.infrastructure.crypto;

import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;

import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

/**
 * 加密字符串 TypeHandler（2.1）：落库时 AES-256-GCM 加密、读取时解密、null 透传。
 *
 * <p>经 MyBatis 类注册（无参构造）时需另行注入 cipher/keyId；本类同时提供
 * {@link #EncryptedStringTypeHandler(AesGcmCipher, String)} 供显式实例注册（对齐 design.md §2.3 L1 字段）。
 */
public class EncryptedStringTypeHandler extends BaseTypeHandler<String> {

    private final AesGcmCipher cipher;
    private final String keyId;

    /** 无参构造：供 MyBatis 类级注册；使用前须配置 cipher/keyId（否则调用时抛 NPE）。 */
    public EncryptedStringTypeHandler() {
        this(null, null);
    }

    public EncryptedStringTypeHandler(AesGcmCipher cipher, String keyId) {
        this.cipher = cipher;
        this.keyId = keyId;
    }

    @Override
    public void setNonNullParameter(PreparedStatement ps, int i, String parameter, JdbcType jdbcType) throws SQLException {
        ps.setString(i, cipher.encrypt(keyId, parameter));
    }

    @Override
    public String getNullableResult(ResultSet rs, String columnName) throws SQLException {
        return decrypt(rs.getString(columnName));
    }

    @Override
    public String getNullableResult(ResultSet rs, int columnIndex) throws SQLException {
        return decrypt(rs.getString(columnIndex));
    }

    @Override
    public String getNullableResult(CallableStatement cs, int columnIndex) throws SQLException {
        return decrypt(cs.getString(columnIndex));
    }

    private String decrypt(String ciphertext) {
        return ciphertext == null ? null : cipher.decrypt(keyId, ciphertext);
    }
}

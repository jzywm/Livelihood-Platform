package com.msz.acc.repository;

import com.msz.acc.infrastructure.crypto.AesGcmCipher;
import com.msz.acc.infrastructure.crypto.EncryptedStringTypeHandler;
import com.msz.acc.infrastructure.crypto.FixedKeyProvider;
import com.msz.common.sharding.MonthlyShardingInterceptor;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.LocalCacheScope;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.session.SqlSessionFactoryBuilder;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import javax.sql.DataSource;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * 数据层手动装配：SqlSessionFactory 工厂 + wallet_flow 动态表名白名单校验。
 *
 * <p>注册内容：{@link MonthlyShardingInterceptor}（按月路由）、{@link EncryptedStringTypeHandler}
 * （L1 字段加解密，实例注册）、注解式 Mapper 与驼峰映射。不引 MyBatis-Plus starter。</p>
 */
public final class DaoSupport {

    private static final Pattern TABLE_NAME_PATTERN = Pattern.compile("^wallet_flow_\\d{6}$");
    private static final String KEY_ID = "k1";

    private final AesGcmCipher cipher;
    private final String keyId;

    /** 默认构造：测试/本地凭据（固定密钥）；生产经 {@link #DaoSupport(AesGcmCipher, String)} 注入 KMS 密钥。 */
    public DaoSupport() {
        this(defaultCipher(), KEY_ID);
    }

    public DaoSupport(AesGcmCipher cipher, String keyId) {
        this.cipher = cipher;
        this.keyId = keyId;
    }

    public SqlSessionFactory factory(DataSource dataSource) {
        Environment environment = new Environment("acc", new JdbcTransactionFactory(), dataSource);
        Configuration configuration = new Configuration(environment);
        configuration.setMapUnderscoreToCamelCase(true);
        // 关闭一级缓存（STATEMENT 级）：幂等轮询/并发场景须每次真实查库，避免会话级缓存返回陈旧数据。
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        configuration.addInterceptor(new MonthlyShardingInterceptor("createdAt"));
        configuration.addInterceptor(new TableNameGuardInterceptor());
        // 以 CharSequence 为显式 javaType 注册实例：使 #{...,typeHandler=EncryptedStringTypeHandler}
        // 经 getMappingTypeHandler(Class) 命中该实例，同时不覆盖 String 默认 handler（避免全局加密）。
        configuration.getTypeHandlerRegistry().register(
                CharSequence.class, new EncryptedStringTypeHandler(cipher, keyId));
        configuration.addMapper(AccountMapper.class);
        configuration.addMapper(RealnameRecordMapper.class);
        configuration.addMapper(WalletFlowMapper.class);
        configuration.addMapper(WalletBindingMapper.class);
        configuration.addMapper(ReconcileTaskMapper.class);
        configuration.addMapper(IdempotencyRecordMapper.class);
        return new SqlSessionFactoryBuilder().build(configuration);
    }

    /**
     * wallet_flow 动态表名白名单校验（防注入）：必须匹配 {@code ^wallet_flow_\d{6}$}，否则抛
     * {@link IllegalArgumentException}。
     */
    public static void requireTableName(String tableName) {
        if (tableName == null || !TABLE_NAME_PATTERN.matcher(tableName).matches()) {
            throw new IllegalArgumentException("非法动态表名（须匹配 ^wallet_flow_\\d{6}$）: " + tableName);
        }
    }

    private static AesGcmCipher defaultCipher() {
        byte[] bytes = new byte[32];
        for (int i = 0; i < bytes.length; i++) {
            bytes[i] = (byte) (i + 1);
        }
        SecretKey key = new SecretKeySpec(bytes, "AES");
        return new AesGcmCipher(new FixedKeyProvider(Map.of(KEY_ID, key)));
    }
}

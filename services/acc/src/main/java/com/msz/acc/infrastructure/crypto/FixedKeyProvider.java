package com.msz.acc.infrastructure.crypto;

import javax.crypto.SecretKey;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 固定密钥提供者：测试/本地凭据用；生产 KMS 适配另留实现。
 * 保持传入顺序（LinkedHashMap），{@link #keyIds()} 即轮换兜底解密的尝试顺序。
 */
public final class FixedKeyProvider implements KeyProvider {

    private final Map<String, SecretKey> keys;

    public FixedKeyProvider(Map<String, SecretKey> keys) {
        this.keys = new LinkedHashMap<>(keys);
    }

    @Override
    public SecretKey key(String keyId) {
        return keys.get(keyId);
    }

    @Override
    public List<String> keyIds() {
        return List.copyOf(keys.keySet());
    }
}

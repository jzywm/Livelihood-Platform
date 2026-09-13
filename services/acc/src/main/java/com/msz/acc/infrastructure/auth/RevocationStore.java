package com.msz.acc.infrastructure.auth;

/**
 * JWT 吊销存储（2.3）：按 jti 判断 token 是否已吊销。Redis 版实现留伞变更 1.6。
 */
public interface RevocationStore {

    boolean isRevoked(String jti);
}

package com.msz.acc.infrastructure.auth;

/**
 * 无吊销存储（2.3 默认实现）：恒返回未吊销；Redis 吊销实现留伞变更 1.6。
 */
public final class NoopRevocationStore implements RevocationStore {

    @Override
    public boolean isRevoked(String jti) {
        return false;
    }
}

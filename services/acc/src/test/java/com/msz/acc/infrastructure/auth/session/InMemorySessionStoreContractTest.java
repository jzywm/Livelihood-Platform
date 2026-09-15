package com.msz.acc.infrastructure.auth.session;

import com.msz.acc.application.port.SessionStore;

/**
 * 内存实现的端口契约直跑（任务 2.2）：语义与 Redis 实现共用同一套断言
 * （见 {@link AbstractSessionStoreContractTest}）。
 */
class InMemorySessionStoreContractTest extends AbstractSessionStoreContractTest {

    private InMemorySessionStore memory;

    @Override
    protected SessionStore newStore(MutableClock clock) {
        memory = new InMemorySessionStore(clock);
        return memory;
    }

    @Override
    protected String rawValue(String key) {
        return memory.rawValue(key);
    }

    @Override
    protected long rawTtl(String key) {
        return memory.rawTtlSeconds(key);
    }
}

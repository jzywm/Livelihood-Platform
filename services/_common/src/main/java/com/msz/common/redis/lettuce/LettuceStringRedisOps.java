package com.msz.common.redis.lettuce;

import com.msz.common.redis.StringRedisOps;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.ScriptOutputType;
import io.lettuce.core.SetArgs;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;

import java.util.List;

/**
 * {@link StringRedisOps} 的 Lettuce 实现（io.lettuce:lettuce-core 6.3.x）。
 * 构造注入连接 URI。本任务仅要求编译通过 + 用接口 fake 测业务逻辑，不写 Redis 集成测试。
 */
public final class LettuceStringRedisOps implements StringRedisOps, AutoCloseable {

    private final RedisClient client;
    private final StatefulRedisConnection<String, String> connection;
    private final RedisCommands<String, String> sync;

    public LettuceStringRedisOps(String uri) {
        this.client = RedisClient.create(RedisURI.create(uri));
        this.connection = client.connect();
        this.sync = connection.sync();
    }

    @Override
    public Long incr(String key) {
        return sync.incr(key);
    }

    @Override
    public Boolean expire(String key, long seconds) {
        return sync.expire(key, seconds);
    }

    @Override
    public String get(String key) {
        return sync.get(key);
    }

    @Override
    public Boolean setNx(String key, String value, long ttlSeconds) {
        SetArgs args = SetArgs.Builder.nx().ex(ttlSeconds);
        String result = sync.set(key, value, args);
        return "OK".equals(result);
    }

    @Override
    public Object eval(String script, List<String> keys, List<String> args) {
        String[] keysArray = keys.toArray(new String[0]);
        String[] argsArray = args.toArray(new String[0]);
        return sync.eval(script, ScriptOutputType.VALUE, keysArray, argsArray);
    }

    @Override
    public void close() {
        connection.close();
        client.shutdown();
    }
}

package com.msz.common.redis;

import java.util.List;

/**
 * 字符串 Redis 操作抽象（最小版），供 infra-idgen workerId 租约及后续 Lua（2.2）复用。
 */
public interface StringRedisOps {

    /** INCR：原子自增返回自增后的值。 */
    Long incr(String key);

    /** EXPIRE：设置 key 过期时间（秒），返回是否成功。 */
    Boolean expire(String key, long seconds);

    /** GET：返回 key 对应值，不存在返回 null。 */
    String get(String key);

    /** SET NX + EX：仅当 key 不存在时写入并设置 TTL，返回是否写入成功。 */
    Boolean setNx(String key, String value, long ttlSeconds);

    /** EVAL：执行 Lua 脚本，keys/args 为脚本入参。 */
    Object eval(String script, List<String> keys, List<String> args);
}

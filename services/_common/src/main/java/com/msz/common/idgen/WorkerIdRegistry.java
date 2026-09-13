package com.msz.common.idgen;

import com.msz.common.redis.StringRedisOps;

import java.util.Objects;

/**
 * workerId 租约注册：基于 Redis {@link StringRedisOps}。
 *
 * <ul>
 *   <li>{@link #acquire(String)}：INCR("idgen:workerId") 得 id，再 SETNX("idgen:worker:" + id, instanceId, 60s) 落租约；
 *       若 key 已被不同 instanceId 占用 → 抛 {@link IdGenException}（workerId 撞车）+ alert(0, …) P0。</li>
 *   <li>{@link #renew()}：EXPIRE 续租。</li>
 * </ul>
 */
public final class WorkerIdRegistry {

    public static final String WORKER_COUNTER_KEY = "idgen:workerId";
    public static final String WORKER_KEY_PREFIX = "idgen:worker:";
    public static final long LEASE_SECONDS = 60L;

    private final StringRedisOps ops;
    private final IdGenAlert alert;
    private volatile long currentWorkerId = -1L;

    public WorkerIdRegistry(StringRedisOps ops, IdGenAlert alert) {
        this.ops = Objects.requireNonNull(ops, "ops");
        this.alert = Objects.requireNonNull(alert, "alert");
    }

    /** 领取一个 workerId 并落租约；撞车则 fast-fail + P0 告警。 */
    public long acquire(String instanceId) {
        long id = ops.incr(WORKER_COUNTER_KEY);
        String key = WORKER_KEY_PREFIX + id;
        boolean acquired = Boolean.TRUE.equals(ops.setNx(key, instanceId, LEASE_SECONDS));
        if (!acquired) {
            String owner = ops.get(key);
            if (owner != null && !owner.equals(instanceId)) {
                alert.alert(0, "workerId 撞车：workerId=" + id + "，占用者=" + owner);
                throw new IdGenException("workerId 撞车，拒绝发号：" + id);
            }
            // 同实例重复 acquire：续租即可。
            ops.expire(key, LEASE_SECONDS);
        }
        this.currentWorkerId = id;
        return id;
    }

    /** 续租当前租约。 */
    public void renew() {
        if (currentWorkerId < 0) {
            throw new IllegalStateException("尚未 acquire，无法续租");
        }
        ops.expire(WORKER_KEY_PREFIX + currentWorkerId, LEASE_SECONDS);
    }
}

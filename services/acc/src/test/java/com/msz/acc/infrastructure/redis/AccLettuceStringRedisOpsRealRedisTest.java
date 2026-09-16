package com.msz.acc.infrastructure.redis;

import com.msz.acc.infrastructure.auth.session.AccessJti;
import com.msz.acc.infrastructure.auth.session.FamilyRecord;
import com.msz.acc.infrastructure.auth.session.RedisSessionStore;
import io.lettuce.core.RedisClient;
import io.lettuce.core.api.StatefulRedisConnection;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import redis.embedded.RedisServer;

import java.io.File;
import java.net.ServerSocket;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * **真实 Redis 上的 EVAL 与端口契约**（任务 7.2 演练暴露的缺陷 + L4 回归防线）。
 *
 * <p>背景（真实缺陷，2026-09-16 由「双 token 会话闭环演练」首次在真实 Redis 上暴露）：
 * {@link AccLettuceStringRedisOps#eval} 原先用 {@code ScriptOutputType.VALUE} 解码，而
 * {@link RedisSessionStore} 的 5 个 Lua 脚本一律 {@code return 1}（整数回复）——真实 Redis 下
 * Lettuce 抛 {@code UnsupportedOperationException: ValueOutput does not support set(long)}，
 * 建族/轮换/单次使用/吊销全部失败（登录直接 503 + 5003）。单元测试用的是「假装执行脚本」的假客户端，
 * 只回放了期望语义，从未真正执行过脚本，故该缺陷一路漏到真机演练。</p>
 *
 * <p>本用例把「真实 Redis 执行真实脚本」钉成回归防线：起内嵌 Redis（test 作用域 embedded-redis）→
 * 用生产实现 {@link AccLettuceStringRedisOps} 跑 {@link RedisSessionStore} 的键路径与语义
 * （建族双键 / 单次使用 / 轮换 / 已轮换标记 / 吊销 TTL）。</p>
 *
 * <p><b>环境不可用即跳过</b>（{@link Assumptions}）：内嵌 Redis 需要随 jar 提供的原生 redis-server，
 * 起不来时（不支持的 OS/架构）本用例跳过而非失败——它守的是「真实 Redis 行为」，不是「本机有没有 Redis」。</p>
 */
class AccLettuceStringRedisOpsRealRedisTest {

    private static final long REFRESH_TTL_SECONDS = 604_800L;

    private static RedisServer server;
    private static int port;

    @BeforeAll
    static void startRedis() {
        try {
            port = freePort();
            String dir = System.getProperty("user.dir") + File.separator + "target" + File.separator + "test-redis";
            new File(dir).mkdirs();
            server = RedisServer.newRedisServer()
                    .port(port)
                    .bind("127.0.0.1")
                    .setting("save \"\"")
                    .setting("appendonly no")
                    .setting("dir " + dir.replace('\\', '/'))
                    .build();
            server.start();
        } catch (Exception e) {
            Assumptions.abort("内嵌 Redis 不可用（本机无法启动原生 redis-server）：" + e.getMessage());
        }
    }

    @AfterAll
    static void stopRedis() {
        if (server != null) {
            try {
                server.stop();
            } catch (Exception ignored) {
                // 测试收尾清理，忽略
            }
        }
    }

    @Test
    @DisplayName("L4/任务7.2 EVAL 必须能解码脚本的整数回复（原用 VALUE 输出 → 真实 Redis 抛 UnsupportedOperationException）")
    void evalDecodesIntegerReply() {
        try (AccLettuceStringRedisOps ops = new AccLettuceStringRedisOps("127.0.0.1", port, "", "")) {
            Object result = ops.eval("return 1", List.of("acc:probe:eval"), List.of());

            assertThat(result).isInstanceOf(Number.class);
            assertThat(((Number) result).longValue()).isEqualTo(1L);
        }
    }

    @Test
    @DisplayName("L4/任务7.2 真实 Redis 上跑真实脚本：建族双键 → 单次使用 → 轮换标记 → 吊销 TTL")
    void realScriptsKeepSessionContract() {
        long now = System.currentTimeMillis();
        try (AccLettuceStringRedisOps ops = new AccLettuceStringRedisOps("127.0.0.1", port, "", "");
             RedisClient probe = RedisClient.create("redis://127.0.0.1:" + port);
             StatefulRedisConnection<String, String> conn = probe.connect()) {
            RedisSessionStore store = new RedisSessionStore(ops, System::currentTimeMillis);
            String familyId = "fam_real_" + now;
            String firstJti = "rf_real_1_" + now;
            String secondJti = "rf_real_2_" + now;
            String accessJti = "at_real_1_" + now;

            FamilyRecord family = new FamilyRecord(familyId, 1001L, "CONSUMER", false, now,
                    now + REFRESH_TTL_SECONDS * 1000L, FamilyRecord.STATUS_ACTIVE, firstJti, null, 0L,
                    Map.of(), Map.of());
            store.issue(family, firstJti, REFRESH_TTL_SECONDS);

            assertThat(store.find(familyId)).isNotNull();
            assertThat(ops.get(RedisSessionStore.REFRESH_KEY_PREFIX + firstJti)).isEqualTo(familyId);
            assertThat(conn.sync().ttl(RedisSessionStore.REFRESH_KEY_PREFIX + firstJti))
                    .isBetween(1L, REFRESH_TTL_SECONDS);

            // 单次使用：脚本 EXISTS+DEL 原子消费，第二次必须为 false
            assertThat(store.consume(firstJti)).isTrue();
            assertThat(store.consume(firstJti)).isFalse();

            // 轮换：新映射写入 + 旧 jti 进「已轮换」标记（族记录里可读，供重放识别）
            FamilyRecord rotated = new FamilyRecord(familyId, 1001L, "CONSUMER", false, now,
                    now + REFRESH_TTL_SECONDS * 1000L, FamilyRecord.STATUS_ACTIVE, secondJti, firstJti,
                    now + 5_000L, Map.of(firstJti, now + REFRESH_TTL_SECONDS * 1000L), Map.of());
            store.rotate(rotated, secondJti, REFRESH_TTL_SECONDS, firstJti);
            FamilyRecord reloaded = store.find(familyId);
            assertThat(reloaded.currentJti()).isEqualTo(secondJti);
            assertThat(reloaded.rotatedJtis()).containsKey(firstJti);
            assertThat(ops.get(RedisSessionStore.REFRESH_KEY_PREFIX + firstJti)).isNull();

            // 吊销契约：revoked:jti:{jti} 占位值 + TTL = 剩余有效期（此处 900s 上限内）
            store.bindAccessJti(familyId, accessJti, now + 900_000L);
            store.revoke(List.of(new AccessJti(accessJti, 900L)));
            assertThat(ops.get(RedisSessionStore.REVOKED_KEY_PREFIX + accessJti))
                    .isEqualTo(RedisSessionStore.REVOKED_VALUE);
            assertThat(conn.sync().ttl(RedisSessionStore.REVOKED_KEY_PREFIX + accessJti))
                    .isBetween(1L, 900L);

            // 整族吊销：族状态置 REVOKED 且记录保留（后续重放能被识别为「已吊销族」）
            store.markRevoked(familyId);
            assertThat(store.find(familyId).revoked()).isTrue();
        }
    }

    private static int freePort() throws Exception {
        try (ServerSocket socket = new ServerSocket(0)) {
            return socket.getLocalPort();
        }
    }
}

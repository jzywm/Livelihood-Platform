package com.msz.acc.infrastructure.captcha;

import com.msz.acc.application.port.CaptchaPort;
import com.msz.acc.application.port.CaptchaVerifyResult;
import com.msz.acc.domain.support.AccBusinessException;
import com.msz.common.idgen.IdGenerator;
import com.msz.common.redis.StringRedisOps;

import java.time.Clock;
import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 人机验证服务（S5 端口适配）：StringRedisOps + 内存 ConcurrentHashMap 兜底（Redis 缺失/异常时降级内存）。
 *
 * <p>口径：挑战号 {@code cap_} 前缀、一次性凭证 {@code ct_} 前缀（er.md §6.6）；TTL 300s；
 * 一次性消费——verify 成功即删 challenge key、captchaToken 消费即删 token key；
 * 校验失败（错/过期/未知）返回 success=false 不抛异常；非法 type → 1003。</p>
 */
public final class CaptchaService implements CaptchaPort {

    /** 挑战/凭证 TTL（秒）。 */
    public static final long TTL_SECONDS = 300;

    private static final String TYPE_SLIDER = "SLIDER";
    private static final String TYPE_IMAGE = "IMAGE";
    private static final int SLIDER_TOLERANCE_PX = 5;
    private static final String CHALLENGE_KEY_PREFIX = "acc:captcha:";
    private static final String TOKEN_KEY_PREFIX = "acc:captcha:token:";

    private final StringRedisOps ops;
    private final IdGenerator idGenerator;
    private final Clock clock;
    private final ConcurrentHashMap<String, MemoryEntry> memory = new ConcurrentHashMap<>();

    /** {@code ops} 可为 null（纯内存兜底，本地/单测）；非 null 时写入/读取失败自动降级内存。 */
    public CaptchaService(StringRedisOps ops, IdGenerator idGenerator, Clock clock) {
        this.ops = ops;
        this.idGenerator = idGenerator;
        this.clock = clock;
    }

    @Override
    public String createChallenge(String type) {
        String resolved = resolveType(type);
        String captchaId = "cap_" + idGenerator.nextId();
        String answer = TYPE_SLIDER.equals(resolved)
                ? String.valueOf(100 + ThreadLocalRandom.current().nextInt(100))
                : randomCode();
        store(CHALLENGE_KEY_PREFIX + captchaId, resolved + ":" + answer);
        return captchaId;
    }

    @Override
    public CaptchaVerifyResult verify(String captchaId, Integer offsetX, String code) {
        MemoryEntry entry = load(CHALLENGE_KEY_PREFIX + captchaId);
        if (entry == null) {
            return new CaptchaVerifyResult(false, null);
        }
        String[] parts = entry.value().split(":", 2);
        boolean ok = TYPE_SLIDER.equals(parts[0])
                ? offsetX != null && Math.abs(offsetX - Integer.parseInt(parts[1])) <= SLIDER_TOLERANCE_PX
                : code != null && code.equalsIgnoreCase(parts[1]);
        if (!ok) {
            return new CaptchaVerifyResult(false, null);
        }
        delete(CHALLENGE_KEY_PREFIX + captchaId);
        String token = "ct_" + idGenerator.nextId();
        store(TOKEN_KEY_PREFIX + token, "1");
        return new CaptchaVerifyResult(true, token);
    }

    @Override
    public void consumeToken(String captchaToken) {
        if (captchaToken == null || !delete(TOKEN_KEY_PREFIX + captchaToken)) {
            throw new AccBusinessException(1003, "captchaToken 无效或已用");
        }
    }

    /** 滑块挑战期望偏移（测试/运维支持：答案仅存服务端，HTTP 层从不返回）。 */
    public Integer expectedOffset(String captchaId) {
        MemoryEntry entry = load(CHALLENGE_KEY_PREFIX + captchaId);
        if (entry == null || !entry.value().startsWith(TYPE_SLIDER + ":")) {
            return null;
        }
        return Integer.valueOf(entry.value().substring(TYPE_SLIDER.length() + 1));
    }

    /** 图形挑战期望答案（测试/运维支持：答案仅存服务端，HTTP 层从不返回）。 */
    public String expectedCode(String captchaId) {
        MemoryEntry entry = load(CHALLENGE_KEY_PREFIX + captchaId);
        if (entry == null || !entry.value().startsWith(TYPE_IMAGE + ":")) {
            return null;
        }
        return entry.value().substring(TYPE_IMAGE.length() + 1);
    }

    private static String resolveType(String type) {
        if (type == null || type.isEmpty() || TYPE_SLIDER.equals(type)) {
            return TYPE_SLIDER;
        }
        if (TYPE_IMAGE.equals(type)) {
            return TYPE_IMAGE;
        }
        throw new AccBusinessException(1003, "验证类型非法（仅 SLIDER/IMAGE）");
    }

    private static String randomCode() {
        String alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
        StringBuilder sb = new StringBuilder(4);
        for (int i = 0; i < 4; i++) {
            sb.append(alphabet.charAt(ThreadLocalRandom.current().nextInt(alphabet.length())));
        }
        return sb.toString();
    }

    private void store(String key, String value) {
        try {
            if (ops != null && Boolean.TRUE.equals(ops.setNx(key, value, TTL_SECONDS))) {
                return;
            }
        } catch (RuntimeException ignored) {
            // Redis 异常 → 内存兜底
        }
        memory.put(key, new MemoryEntry(value, clock.instant().plusSeconds(TTL_SECONDS)));
    }

    private MemoryEntry load(String key) {
        String value = null;
        try {
            if (ops != null) {
                value = ops.get(key);
            }
        } catch (RuntimeException ignored) {
            value = null;
        }
        MemoryEntry entry = value != null
                ? new MemoryEntry(value, clock.instant().plusSeconds(TTL_SECONDS))
                : memory.get(key);
        if (entry == null || entry.expireAt().isBefore(clock.instant())) {
            memory.remove(key);
            return null;
        }
        return entry;
    }

    private boolean delete(String key) {
        boolean deleted = false;
        try {
            if (ops != null) {
                deleted = ops.get(key) != null;
                ops.expire(key, 0);
            }
        } catch (RuntimeException ignored) {
            deleted = false;
        }
        deleted = deleted || memory.remove(key) != null;
        return deleted;
    }

    private record MemoryEntry(String value, Instant expireAt) {
    }
}

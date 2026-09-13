package com.msz.common.api;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 1.1 Envelope 统一响应包络工厂与字段断言。
 */
class EnvelopeTest {

    @Test
    @DisplayName("1.1: Envelope.ok 工厂产出 code=0 / data / traceId / ISO-8601 timestamp")
    void ut_envelope_ok_factory() {
        Envelope<Integer> env = Envelope.ok(42, "trace-1");
        assertThat(env.code()).isEqualTo(0);
        assertThat(env.message()).isEqualTo("成功");
        assertThat(env.data()).isEqualTo(42);
        assertThat(env.traceId()).isEqualTo("trace-1");
        assertThat(env.timestamp()).isNotBlank();
        assertThat(Instant.parse(env.timestamp())).isNotNull();
    }

    @Test
    @DisplayName("1.1: Envelope.fail 工厂产出 code/message/null data/traceId")
    void ut_envelope_fail_factory() {
        Envelope<?> env = Envelope.fail(1003, "枚举/范围非法", "trace-2");
        assertThat(env.code()).isEqualTo(1003);
        assertThat(env.message()).isEqualTo("枚举/范围非法");
        assertThat(env.data()).isNull();
        assertThat(env.traceId()).isEqualTo("trace-2");
        assertThat(Instant.parse(env.timestamp())).isNotNull();
    }
}

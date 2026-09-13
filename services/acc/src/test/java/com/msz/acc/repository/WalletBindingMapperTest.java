package com.msz.acc.repository;

import com.msz.acc.domain.model.WalletBinding;
import org.apache.ibatis.session.SqlSession;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * WalletBindingMapperTest：uk_account_channel 冲突被拒、markUnbound 不删行、markBound 复用原行。
 */
class WalletBindingMapperTest extends AbstractDbTest {

    @Test
    @DisplayName("uk_account_channel(account_id, channel) 冲突被拒")
    void duplicateAccountChannelIsRejected() {
        try (SqlSession s = openSession()) {
            WalletBindingMapper mapper = s.getMapper(WalletBindingMapper.class);
            mapper.insert(binding("bnd_1", 1L, "WECHAT"));
            assertDuplicateKey(() -> mapper.insert(binding("bnd_2", 1L, "WECHAT")));
        }
    }

    @Test
    @DisplayName("markUnbound 后行仍存在且 status=UNBOUND")
    void markUnboundLeavesRowWithUnboundStatus() {
        try (SqlSession s = openSession()) {
            s.getMapper(WalletBindingMapper.class).insert(binding("bnd_10", 5L, "WECHAT"));
        }

        Instant unboundAt = Instant.parse("2026-02-01T00:00:00Z");
        try (SqlSession s = openSession()) {
            assertThat(s.getMapper(WalletBindingMapper.class).markUnbound("bnd_10", unboundAt)).isEqualTo(1);
        }

        try (SqlSession s = openSession()) {
            WalletBinding loaded = s.getMapper(WalletBindingMapper.class).selectById("bnd_10");
            assertThat(loaded).as("解绑后行仍存在").isNotNull();
            assertThat(loaded.getStatus()).isEqualTo("UNBOUND");
            assertThat(loaded.getUnboundAt()).isEqualTo(unboundAt);
            assertThat(s.getMapper(WalletBindingMapper.class).listByAccount(5L)).hasSize(1);
        }
    }

    @Test
    @DisplayName("markBound 复用原行（行数不增）")
    void markBoundReusesOriginalRow() {
        try (SqlSession s = openSession()) {
            s.getMapper(WalletBindingMapper.class).insert(binding("bnd_20", 6L, "ALIPAY"));
        }
        try (SqlSession s = openSession()) {
            WalletBindingMapper mapper = s.getMapper(WalletBindingMapper.class);
            mapper.markUnbound("bnd_20", Instant.parse("2026-02-01T00:00:00Z"));
            assertThat(mapper.markBound("bnd_20")).isEqualTo(1);
        }
        try (SqlSession s = openSession()) {
            WalletBindingMapper mapper = s.getMapper(WalletBindingMapper.class);
            assertThat(mapper.listByAccount(6L)).hasSize(1);
            WalletBinding loaded = mapper.selectById("bnd_20");
            assertThat(loaded.getStatus()).isEqualTo("BOUND");
            assertThat(loaded.getPayeeAccount()).isEqualTo("6222000011112222");
            assertThat(loaded.getPayeeName()).isEqualTo("王五");
        }
    }

    private static WalletBinding binding(String bindingId, long accountId, String channel) {
        WalletBinding binding = new WalletBinding();
        binding.setBindingId(bindingId);
        binding.setAccountId(accountId);
        binding.setChannel(channel);
        binding.setPayeeAccount("6222000011112222");
        binding.setPayeeName("王五");
        binding.setStatus("BOUND");
        binding.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
        return binding;
    }
}

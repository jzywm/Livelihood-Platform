package com.msz.acc.repository;

import com.msz.acc.domain.model.Account;
import org.apache.ibatis.session.SqlSession;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * AccountMapperTest：insert/selectById 加解密回环、mobile_hash 唯一冲突、softClose 留痕（UT-F08）。
 */
class AccountMapperTest extends AbstractDbTest {

    @Test
    @DisplayName("insert + selectById：L1 字段落库加密、读取解密回环")
    void insertAndSelectByIdRoundTrips() throws Exception {
        try (SqlSession s = openSession()) {
            s.getMapper(AccountMapper.class).insert(account(1001L, "hash-1001"));
        }

        // 库层断言：mobile 为密文（不含明文）
        try (Connection c = dataSource.getConnection(); Statement st = c.createStatement();
             ResultSet rs = st.executeQuery("SELECT mobile FROM account WHERE account_id = 1001")) {
            assertThat(rs.next()).isTrue();
            assertThat(rs.getString(1)).doesNotContain("13800138000");
        }

        try (SqlSession s = openSession()) {
            Account loaded = s.getMapper(AccountMapper.class).selectById(1001L);
            assertThat(loaded).isNotNull();
            assertThat(loaded.getMobile()).isEqualTo("13800138000");
            assertThat(loaded.getRealName()).isEqualTo("张三");
            assertThat(loaded.getIdNo()).isEqualTo("110101199001011234");
            assertThat(loaded.getMobileHash()).isEqualTo("hash-1001");
            assertThat(loaded.getRole()).isEqualTo("CONSUMER");
            assertThat(loaded.getRealNameStatus()).isEqualTo("UNREALNAMED");
            assertThat(loaded.getWalletStatus()).isEqualTo("ACTIVE");
        }
    }

    @Test
    @DisplayName("mobile_hash 唯一冲突：第二次插同 hash 抛 DuplicateKey")
    void duplicateMobileHashIsRejected() {
        try (SqlSession s = openSession()) {
            AccountMapper mapper = s.getMapper(AccountMapper.class);
            mapper.insert(account(2001L, "hash-dup"));
            assertDuplicateKey(() -> mapper.insert(account(2002L, "hash-dup")));
        }
    }

    @Test
    @DisplayName("UT-F08: softClose 后 closed_at 留痕且行仍在")
    void softCloseLeavesTrace() {
        try (SqlSession s = openSession()) {
            s.getMapper(AccountMapper.class).insert(account(3001L, "hash-3001"));
        }

        Instant closedAt = Instant.parse("2026-03-01T00:00:00Z");
        try (SqlSession s = openSession()) {
            assertThat(s.getMapper(AccountMapper.class).softClose(3001L, "用户主动注销", closedAt)).isEqualTo(1);
        }

        try (SqlSession s = openSession()) {
            Account loaded = s.getMapper(AccountMapper.class).selectById(3001L);
            assertThat(loaded).as("注销后行仍存在").isNotNull();
            assertThat(loaded.getClosedAt()).isEqualTo(closedAt);
            assertThat(loaded.getCloseReason()).isEqualTo("用户主动注销");
        }
    }

    private static Account account(long accountId, String mobileHash) {
        Account account = new Account();
        account.setAccountId(accountId);
        account.setMobile("13800138000");
        account.setRole("CONSUMER");
        account.setRealNameStatus("UNREALNAMED");
        account.setWalletStatus("ACTIVE");
        account.setRealName("张三");
        account.setIdNo("110101199001011234");
        account.setMobileHash(mobileHash);
        account.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
        return account;
    }
}

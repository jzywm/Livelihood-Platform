package com.msz.acc.repository;

import com.msz.acc.domain.model.Account;
import com.msz.acc.infrastructure.crypto.EncryptedStringTypeHandler;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Result;
import org.apache.ibatis.annotations.Results;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.Instant;

/**
 * account Mapper（注解式）：L1 字段 mobile/real_name/id_no 经 EncryptedStringTypeHandler 加解密。
 */
public interface AccountMapper {

    String ENC = "com.msz.acc.infrastructure.crypto.EncryptedStringTypeHandler";

    @Insert("INSERT INTO account (account_id, mobile, role, real_name_status, wallet_status, real_name, id_no, "
            + "mobile_hash, created_at, closed_at, close_reason) VALUES ("
            + "#{accountId}, "
            + "#{mobile,typeHandler=" + ENC + "}, "
            + "#{role}, #{realNameStatus}, #{walletStatus}, "
            + "#{realName,typeHandler=" + ENC + "}, "
            + "#{idNo,typeHandler=" + ENC + "}, "
            + "#{mobileHash}, #{createdAt}, #{closedAt}, #{closeReason})")
    int insert(Account account);

    @Select("SELECT * FROM account WHERE account_id = #{accountId}")
    @Results({
            @Result(column = "mobile", property = "mobile", typeHandler = EncryptedStringTypeHandler.class),
            @Result(column = "real_name", property = "realName", typeHandler = EncryptedStringTypeHandler.class),
            @Result(column = "id_no", property = "idNo", typeHandler = EncryptedStringTypeHandler.class)
    })
    Account selectById(@Param("accountId") long accountId);

    @Select("SELECT * FROM account WHERE mobile_hash = #{mobileHash}")
    @Results({
            @Result(column = "mobile", property = "mobile", typeHandler = EncryptedStringTypeHandler.class),
            @Result(column = "real_name", property = "realName", typeHandler = EncryptedStringTypeHandler.class),
            @Result(column = "id_no", property = "idNo", typeHandler = EncryptedStringTypeHandler.class)
    })
    Account selectByMobileHash(@Param("mobileHash") String mobileHash);

    @Update("UPDATE account SET closed_at = #{closedAt}, close_reason = #{closeReason} WHERE account_id = #{accountId}")
    int softClose(@Param("accountId") long accountId,
                  @Param("closeReason") String closeReason,
                  @Param("closedAt") Instant closedAt);
}

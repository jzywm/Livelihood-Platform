package com.msz.acc.repository;

import com.msz.acc.domain.model.WalletBinding;
import com.msz.acc.infrastructure.crypto.EncryptedStringTypeHandler;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Result;
import org.apache.ibatis.annotations.Results;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.Instant;
import java.util.List;

/**
 * wallet_binding Mapper（注解式）：L1 字段 payee_account/payee_name 经 EncryptedStringTypeHandler 加解密。
 * 解绑置 UNBOUND 不删行（markUnbound）；重新绑定复用原行（markBound）。
 */
public interface WalletBindingMapper {

    String ENC = "com.msz.acc.infrastructure.crypto.EncryptedStringTypeHandler";

    @Insert("INSERT INTO wallet_binding (binding_id, account_id, channel, payee_account, payee_name, status, "
            + "created_at, unbound_at) VALUES ("
            + "#{bindingId}, #{accountId}, #{channel}, "
            + "#{payeeAccount,typeHandler=" + ENC + "}, "
            + "#{payeeName,typeHandler=" + ENC + "}, "
            + "#{status}, #{createdAt}, #{unboundAt})")
    int insert(WalletBinding binding);

    @Select("SELECT * FROM wallet_binding WHERE account_id = #{accountId} AND channel = #{channel}")
    @Results({
            @Result(column = "payee_account", property = "payeeAccount", typeHandler = EncryptedStringTypeHandler.class),
            @Result(column = "payee_name", property = "payeeName", typeHandler = EncryptedStringTypeHandler.class)
    })
    WalletBinding selectByAccountAndChannel(@Param("accountId") long accountId, @Param("channel") String channel);

    @Select("SELECT * FROM wallet_binding WHERE binding_id = #{bindingId}")
    @Results({
            @Result(column = "payee_account", property = "payeeAccount", typeHandler = EncryptedStringTypeHandler.class),
            @Result(column = "payee_name", property = "payeeName", typeHandler = EncryptedStringTypeHandler.class)
    })
    WalletBinding selectById(@Param("bindingId") String bindingId);

    @Select("SELECT * FROM wallet_binding WHERE account_id = #{accountId}")
    @Results({
            @Result(column = "payee_account", property = "payeeAccount", typeHandler = EncryptedStringTypeHandler.class),
            @Result(column = "payee_name", property = "payeeName", typeHandler = EncryptedStringTypeHandler.class)
    })
    List<WalletBinding> listByAccount(@Param("accountId") long accountId);

    @Update("UPDATE wallet_binding SET status = 'UNBOUND', unbound_at = #{unboundAt} WHERE binding_id = #{bindingId}")
    int markUnbound(@Param("bindingId") String bindingId, @Param("unboundAt") Instant unboundAt);

    @Update("UPDATE wallet_binding SET status = 'BOUND' WHERE binding_id = #{bindingId}")
    int markBound(@Param("bindingId") String bindingId);
}

package com.msz.acc.repository;

import com.msz.acc.domain.model.RealnameRecord;
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
 * realname_record Mapper（注解式）：L1 字段 name/id_no 经 EncryptedStringTypeHandler 加解密。
 */
public interface RealnameRecordMapper {

    String ENC = "com.msz.acc.infrastructure.crypto.EncryptedStringTypeHandler";

    @Insert("INSERT INTO realname_record (biz_id, account_id, channel, open_id, name, id_no, status, level, "
            + "created_at, callback_at) VALUES ("
            + "#{bizId}, #{accountId}, #{channel}, #{openId}, "
            + "#{name,typeHandler=" + ENC + "}, "
            + "#{idNo,typeHandler=" + ENC + "}, "
            + "#{status}, #{level}, #{createdAt}, #{callbackAt})")
    int insert(RealnameRecord record);

    @Select("SELECT * FROM realname_record WHERE biz_id = #{bizId}")
    @Results({
            @Result(column = "name", property = "name", typeHandler = EncryptedStringTypeHandler.class),
            @Result(column = "id_no", property = "idNo", typeHandler = EncryptedStringTypeHandler.class)
    })
    RealnameRecord selectByBizId(@Param("bizId") String bizId);

    @Select("SELECT * FROM realname_record WHERE open_id = #{openId}")
    @Results({
            @Result(column = "name", property = "name", typeHandler = EncryptedStringTypeHandler.class),
            @Result(column = "id_no", property = "idNo", typeHandler = EncryptedStringTypeHandler.class)
    })
    RealnameRecord selectByOpenId(@Param("openId") String openId);

    @Update("UPDATE realname_record SET status = #{status}, account_id = #{accountId}, callback_at = #{callbackAt} "
            + "WHERE biz_id = #{bizId}")
    int updateCallback(@Param("bizId") String bizId,
                       @Param("status") String status,
                       @Param("accountId") Long accountId,
                       @Param("callbackAt") Instant callbackAt);

    @Select("SELECT * FROM realname_record WHERE account_id = #{accountId} AND status = #{status}")
    @Results({
            @Result(column = "name", property = "name", typeHandler = EncryptedStringTypeHandler.class),
            @Result(column = "id_no", property = "idNo", typeHandler = EncryptedStringTypeHandler.class)
    })
    List<RealnameRecord> selectByAccountIdAndStatus(@Param("accountId") long accountId, @Param("status") String status);
}

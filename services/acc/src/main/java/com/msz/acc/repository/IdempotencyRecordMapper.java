package com.msz.acc.repository;

import com.msz.acc.domain.model.IdempotencyRecord;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * acc_idempotency_record Mapper（注解式）：INSERT IGNORE 抢占幂等槽位，uk_idempotency_key 为唯一事实源。
 */
public interface IdempotencyRecordMapper {

    @Insert("INSERT IGNORE INTO acc_idempotency_record (biz_scene, idempotency_key, response_code, response_payload) "
            + "VALUES (#{bizScene}, #{idempotencyKey}, #{responseCode}, #{responsePayload})")
    int insertIgnore(@Param("bizScene") String bizScene,
                     @Param("idempotencyKey") String idempotencyKey,
                     @Param("responseCode") int responseCode,
                     @Param("responsePayload") String responsePayload);

    @Select("SELECT * FROM acc_idempotency_record WHERE idempotency_key = #{idempotencyKey}")
    IdempotencyRecord selectByKey(@Param("idempotencyKey") String idempotencyKey);

    @Update("UPDATE acc_idempotency_record SET response_code = #{responseCode}, response_payload = #{responsePayload} "
            + "WHERE idempotency_key = #{idempotencyKey}")
    int updateResult(@Param("idempotencyKey") String idempotencyKey,
                     @Param("responseCode") int responseCode,
                     @Param("responsePayload") String responsePayload);
}

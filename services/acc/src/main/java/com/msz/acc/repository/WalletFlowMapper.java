package com.msz.acc.repository;

import com.msz.acc.domain.model.WalletFlow;
import com.msz.common.sharding.ShardingKey;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.Instant;
import java.util.List;

/**
 * wallet_flow Mapper（注解式，按月分表）：
 * <ul>
 *   <li>写入：SQL 表名写裸 {@code wallet_flow}，由 {@code MonthlyShardingInterceptor} 按 createdAt（UTC）路由到月表；</li>
 *   <li>查询：走逐表显式 {@code ${tableName}}，表名必须匹配 {@code ^wallet_flow_\d{6}$}（见 {@link DaoSupport#requireTableName}）；</li>
 *   <li>只增不改：无任何 update/delete 方法，库层由 V2 回收写权限（UT-B03 / SEC-09）。</li>
 * </ul>
 */
public interface WalletFlowMapper {

    @ShardingKey(accountIdField = "accountId", createdAtField = "createdAt")
    @Insert("INSERT INTO wallet_flow (flow_id, account_id, type, direction, amount, status, channel_order_no, "
            + "biz_type, hash, occurred_at, created_at) VALUES ("
            + "#{flowId}, #{accountId}, #{type}, #{direction}, #{amount}, #{status}, #{channelOrderNo}, "
            + "#{bizType}, #{hash}, #{occurredAt}, #{createdAt})")
    int insert(WalletFlow flow);

    @Select("<script>"
            + "SELECT flow_id, account_id, type, direction, amount, status, channel_order_no, biz_type, hash, "
            + "occurred_at, created_at FROM ${tableName} "
            + "WHERE account_id = #{accountId} AND created_at &gt;= #{from} AND created_at &lt;= #{to}"
            + "<if test='type != null'> AND type = #{type}</if> "
            + "ORDER BY created_at DESC LIMIT #{limit} OFFSET #{offset}"
            + "</script>")
    List<WalletFlow> selectByAccountAndRange(@Param("tableName") String tableName,
                                             @Param("accountId") long accountId,
                                             @Param("from") Instant from,
                                             @Param("to") Instant to,
                                             @Param("offset") int offset,
                                             @Param("limit") int limit,
                                             @Param("type") String type);

    @Select("<script>"
            + "SELECT COUNT(*) FROM ${tableName} WHERE account_id = #{accountId} "
            + "AND created_at &gt;= #{from} AND created_at &lt;= #{to}"
            + "<if test='type != null'> AND type = #{type}</if>"
            + "</script>")
    long countByAccountAndRange(@Param("tableName") String tableName,
                                @Param("accountId") long accountId,
                                @Param("from") Instant from,
                                @Param("to") Instant to,
                                @Param("type") String type);

    @Select("<script>"
            + "SELECT flow_id, account_id, type, direction, amount, status, channel_order_no, biz_type, hash, "
            + "occurred_at, created_at FROM ${tableName} "
            + "WHERE created_at &gt;= #{from} AND created_at &lt;= #{to} "
            + "ORDER BY created_at DESC LIMIT #{limit} OFFSET #{offset}"
            + "</script>")
    List<WalletFlow> selectAllByRange(@Param("tableName") String tableName,
                                      @Param("from") Instant from,
                                      @Param("to") Instant to,
                                      @Param("offset") int offset,
                                      @Param("limit") int limit);
}

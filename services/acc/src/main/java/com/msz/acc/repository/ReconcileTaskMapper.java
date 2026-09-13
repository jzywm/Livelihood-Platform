package com.msz.acc.repository;

import com.msz.acc.domain.model.ReconcileTask;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.Instant;
import java.util.List;

/**
 * reconcile_task Mapper（注解式）。
 */
public interface ReconcileTaskMapper {

    @Insert("INSERT INTO reconcile_task (reconcile_id, from_date, to_date, status, diff_count, created_at, finished_at) "
            + "VALUES (#{reconcileId}, #{fromDate}, #{toDate}, #{status}, #{diffCount}, #{createdAt}, #{finishedAt})")
    int insert(ReconcileTask task);

    @Select("SELECT * FROM reconcile_task WHERE reconcile_id = #{reconcileId}")
    ReconcileTask selectById(@Param("reconcileId") String reconcileId);

    @Update("UPDATE reconcile_task SET status = #{status}, diff_count = #{diffCount}, finished_at = #{finishedAt} "
            + "WHERE reconcile_id = #{reconcileId}")
    int finish(@Param("reconcileId") String reconcileId,
               @Param("status") String status,
               @Param("diffCount") long diffCount,
               @Param("finishedAt") Instant finishedAt);

    @Select("SELECT * FROM reconcile_task WHERE status = #{status} ORDER BY created_at DESC "
            + "LIMIT #{limit} OFFSET #{offset}")
    List<ReconcileTask> listByStatusCreated(@Param("status") String status,
                                            @Param("offset") int offset,
                                            @Param("limit") int limit);
}

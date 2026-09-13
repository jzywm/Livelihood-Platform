package com.msz.acc.infrastructure.redis;

/**
 * 流水链尾 DB 读取器（2.2）：从最近月表反查最后一条流水的 hash（链尾权威来源兜底）。
 * 实现由 repository 层提供（按 wallet_flow_YYYYMM 反查），S2 仅定义接口。
 */
public interface FlowHashReader {

    /** 返回账户最近一条流水的存证 hash；无流水返回 null。 */
    String latestHash(long accountId);
}

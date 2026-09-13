-- ACC 专用数据库 acc（裁决：CREATE DATABASE IF NOT EXISTS acc DEFAULT CHARACTER SET utf8mb4）
-- 表用 er.md §6 裸表名；wallet_flow 按月分表 14 张（202507~202608）。
CREATE DATABASE IF NOT EXISTS acc DEFAULT CHARACTER SET utf8mb4;

-- ---------------------------------------------------------------------------
-- account 平台账户（不分片）· er.md §6.1 / §7.1
-- ---------------------------------------------------------------------------
CREATE TABLE account (
    account_id       BIGINT UNSIGNED NOT NULL,
    mobile           VARCHAR(255) NOT NULL,
    role             ENUM('CONSUMER','MERCHANT','SUPPLIER','WORKER','REGULATOR','OPERATOR') NOT NULL,
    real_name_status ENUM('UNREALNAMED','REALNAMING','REALNAMED','SUSPENDED') NOT NULL DEFAULT 'UNREALNAMED',
    wallet_status    ENUM('ACTIVE','FROZEN') NOT NULL DEFAULT 'ACTIVE',
    real_name        VARCHAR(255) NOT NULL,
    id_no            VARCHAR(255) NOT NULL,
    mobile_hash      VARCHAR(64) NULL,
    created_at       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    closed_at        DATETIME(3) NULL,
    close_reason     VARCHAR(255) NULL,
    PRIMARY KEY (account_id),
    UNIQUE KEY uk_mobile_hash (mobile_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- realname_record 实名业务单（不分片）· er.md §6.2 / §7.2
-- ---------------------------------------------------------------------------
CREATE TABLE realname_record (
    biz_id      VARCHAR(32) NOT NULL,
    account_id  BIGINT UNSIGNED NULL,
    channel     ENUM('WECHAT','ALIPAY') NOT NULL,
    open_id     VARCHAR(64) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    id_no       VARCHAR(255) NOT NULL,
    status      ENUM('UNREALNAMED','REALNAMING','REALNAMED','SUSPENDED') NOT NULL DEFAULT 'REALNAMING',
    level       ENUM('BASE','ENHANCED') NOT NULL DEFAULT 'BASE',
    created_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    callback_at DATETIME(3) NULL,
    PRIMARY KEY (biz_id),
    UNIQUE KEY uk_open_id (open_id),
    KEY idx_account_id (account_id),
    KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- wallet_binding 收款账户绑定（不分片）· er.md §6.4 / §7.4
-- ---------------------------------------------------------------------------
CREATE TABLE wallet_binding (
    binding_id    VARCHAR(32) NOT NULL,
    account_id    BIGINT UNSIGNED NOT NULL,
    channel       ENUM('WECHAT','ALIPAY') NOT NULL,
    payee_account VARCHAR(255) NOT NULL,
    payee_name    VARCHAR(255) NULL,
    status        ENUM('BOUND','UNBOUND') NOT NULL DEFAULT 'BOUND',
    created_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    unbound_at    DATETIME(3) NULL,
    PRIMARY KEY (binding_id),
    UNIQUE KEY uk_account_channel (account_id, channel),
    KEY idx_account_id (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- reconcile_task 监管端资金对账任务（不分片）· er.md §6.5 / §7.5
-- ---------------------------------------------------------------------------
CREATE TABLE reconcile_task (
    reconcile_id VARCHAR(32) NOT NULL,
    from_date    DATE NOT NULL,
    to_date      DATE NOT NULL,
    status       ENUM('RUNNING','DONE','DIFF') NOT NULL DEFAULT 'RUNNING',
    diff_count   BIGINT UNSIGNED NOT NULL DEFAULT 0,
    created_at   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    finished_at  DATETIME(3) NULL,
    PRIMARY KEY (reconcile_id),
    KEY idx_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- acc_idempotency_record 幂等记录表（唯一事实源：uk_idempotency_key）· 3.3
-- ---------------------------------------------------------------------------
CREATE TABLE acc_idempotency_record (
    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    biz_scene        VARCHAR(32) NOT NULL,
    idempotency_key  VARCHAR(64) NOT NULL,
    response_code    INT NOT NULL,
    response_payload TEXT NULL,
    created_at       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_idempotency_key (idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- wallet_flow 按月分表（14 张，结构相同）· er.md §6.3 / §7.3
-- 覆盖 202507 ~ 202608：12 热月 + 跨年边界测试。
-- ---------------------------------------------------------------------------
CREATE TABLE wallet_flow_202507 (
    flow_id          BIGINT UNSIGNED NOT NULL,
    account_id       BIGINT UNSIGNED NOT NULL,
    type             ENUM('PAYROLL','SERVICE_FEE','SPLIT','REFUND','OTHER') NOT NULL,
    direction        ENUM('IN','OUT') NOT NULL,
    amount           DECIMAL(18,2) NOT NULL,
    status           ENUM('SUCCEEDED','PENDING','FAILED') NOT NULL,
    channel_order_no VARCHAR(64) NULL,
    biz_type         VARCHAR(32) NULL,
    hash             VARCHAR(128) NOT NULL,
    occurred_at      DATETIME(3) NOT NULL,
    created_at       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (flow_id),
    UNIQUE KEY uk_channel_order_no (channel_order_no),
    KEY idx_account_created (account_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE wallet_flow_202508 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202509 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202510 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202511 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202512 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202601 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202602 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202603 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202604 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202605 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202606 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202607 LIKE wallet_flow_202507;
CREATE TABLE wallet_flow_202608 LIKE wallet_flow_202507;

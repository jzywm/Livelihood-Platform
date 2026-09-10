# 账户服务（ACC）ER 图

> 依据文档：`docs/design/产品设计文档.md` v1.4（§5.1 / §6.4.1）、`docs/design/微服务边界与职责基准.md`（§2.1 / §4.5）、
> `docs/design/高并发架构演进设计.md`（§2.2 分表方案）、`services/acc/docs/openapi.yaml` v1.1.0（唯一可手改源）。
> 数据域归属：① 身份域（`account`、`wallet_flow`）。口径与 openapi.yaml 冲突时以 openapi.yaml 为准。

## 1. ER 图（Mermaid）

```mermaid
erDiagram
    %% ACC 账户服务 ER 图 · 实名身份底座 + 纯记账簿（I-01 / I-06 / G-01）

    ACCOUNT {
        bigint account_id PK "雪花ID"
        varchar mobile "手机号,加密存储,输出脱敏如138****8000"
        enum role "六方角色:CONSUMER/MERCHANT/SUPPLIER/WORKER/REGULATOR/OPERATOR"
        enum real_name_status "实名状态机:UNREALNAMED/REALNAMING/REALNAMED/SUSPENDED"
        enum wallet_status "钱包状态:ACTIVE/FROZEN"
        varchar real_name "实名姓名,L1敏感,AES-256-GCM加密"
        varchar id_no "证件号,L1敏感,AES-256-GCM加密"
        datetime created_at "注册时间"
        datetime closed_at "注销时间,注销留痕"
        varchar close_reason "注销原因"
    }

    REALNAME_RECORD {
        varchar biz_id PK "业务号rz_xxx,实名状态轮询凭据"
        bigint account_id FK "回调后落账户,建户前为空"
        enum channel "回传通道:WECHAT/ALIPAY"
        varchar open_id UK "第三方open_id,幂等键,重复返回原账户"
        varchar name "实名姓名,加密"
        varchar id_no "证件号,加密"
        enum status "实名状态机:UNREALNAMED/REALNAMING/REALNAMED/SUSPENDED"
        enum level "实名等级:BASE基础回传/ENHANCED强实名(I-06 NFC)"
        datetime created_at "申请时间"
        datetime callback_at "第三方回调时间"
    }

    WALLET_FLOW {
        bigint flow_id PK "雪花ID"
        bigint account_id FK "分表键(account_id+created_at)"
        enum type "流水类型:PAYROLL/SERVICE_FEE/SPLIT/REFUND/OTHER"
        enum direction "资金方向:IN/OUT,记账簿视角"
        decimal amount "金额,字符串小数,防浮点误差"
        enum status "流水状态:SUCCEEDED/PENDING/FAILED"
        varchar channel_order_no "第三方通道交易号,R-04留痕"
        varchar biz_type "业务类型:代付/分账/服务费等"
        varchar hash "存证哈希,SHA-256哈希链,R-04只增不改"
        datetime occurred_at "发生时间UTC"
        datetime created_at "入账时间,分表键"
    }

    WALLET_BINDING {
        varchar binding_id PK "绑定号bnd_xxx"
        bigint account_id FK "所属账户"
        enum channel "收款通道:WECHAT/ALIPAY"
        varchar payee_account "收款账号,加密存储,输出脱敏"
        varchar payee_name "收款人,输出脱敏"
        enum status "绑定状态:BOUND/UNBOUND"
        datetime created_at "绑定时间"
        datetime unbound_at "解绑时间"
    }

    RECONCILE_TASK {
        varchar reconcile_id PK "对账任务号rec_xxx"
        date from_date "对账起始日期"
        date to_date "对账截止日期"
        enum status "任务状态:RUNNING/DONE/DIFF"
        bigint diff_count "对账不一致笔数,大于0报3009"
        datetime created_at "任务创建时间"
        datetime finished_at "任务完成时间"
    }

    CAPTCHA_CHALLENGE {
        varchar captcha_id PK "挑战号cap_xxx"
        enum type "验证类型:SLIDER滑块/IMAGE图形"
        int answer "正确答案,仅存服务端,前端拿不到"
        varchar verify_token "一次性凭证,5分钟有效,注册回填captchaToken"
        datetime expire_at "挑战过期时间,一次性消费"
    }

    ACCOUNT ||--o{ REALNAME_RECORD : "回传落账户/重试/强实名增强"
    ACCOUNT ||--o{ WALLET_FLOW : "记账流水,只增不改"
    ACCOUNT ||--o{ WALLET_BINDING : "绑定收款账户"
    RECONCILE_TASK }o--o{ WALLET_FLOW : "对账核对,逻辑关联按日期范围,非FK"

    %% CAPTCHA_CHALLENGE 存 Redis（内存态兜底），一次性消费，不入 MySQL；
    %% 经 verify_token 与注册/登录流程逻辑关联，防机器人与登录爆破限速一体化。
```

## 2. 实体清单

| 实体（表名） | 存储介质 | 说明 |
|---|---|---|
| `account` | MySQL 主库（主数据，不分片） | 平台账户：六方角色 + 实名/钱包状态，全平台可信身份底座 |
| `realname_record` | MySQL | 实名业务单：回传/重试/NFC 增强留痕，承载实名状态机 |
| `wallet_flow` | MySQL **按月分表** | 纯记账簿流水：只增不改，通道交易号 + 存证哈希链 |
| `wallet_binding` | MySQL | 收款账户绑定（持牌通道），供 SETTLE 代付/分账收款 |
| `reconcile_task` | MySQL | 监管端资金对账任务（R-11），平台流水 vs 通道账单 |
| `captcha_challenge` | Redis（内存态兜底） | 人机验证挑战（G-01），一次性消费，**不入库** |

## 3. 关键设计约定

- **R-01 只记账不碰钱**：ACC 不设资金余额字段，`wallet_flow` 是纯记账簿，钱包汇总由流水聚合计算。
- **R-02 实名唯一口径**：证件号仅由微信/支付宝回传，平台不收集证件照片；`realname_record.open_id` 为幂等键，重复回传返回原账户；第三方不可用按红线暂停注册并明示，不静默降级。
- **R-04 流水只增不改**：`channel_order_no` + `hash`（SHA-256 哈希链）+ 时间戳即证据链，可出证（P-02）。
- **加密与脱敏**：`real_name` / `id_no` 等 L1 高敏感字段 AES-256-GCM 加密存储、脱敏输出（如 138****8000）。
- **分表**：`wallet_flow` 按月分表，分片键 `account_id + created_at`；>12 月热转冷 OSS，保留热表 12 个月；主数据（account 等）不分片。
- **幂等**：实名（重复 `open_id`）与绑定（同账号同通道）幂等返回原记录；资金类接口走 `Idempotency-Key`。
- **状态机**：实名 `UNREALNAMED → REALNAMING → REALNAMED / SUSPENDED`；NFC 增强（I-06）在 `level` 上标记 BASE/ENHANCED，基础回传路径不变。
- **监管审计（R-11）**：`reconcile_task` 对账不一致报 3009；审计视图 `FundsAuditFlow` = 流水 + `payerId/payeeId/merchantName/reconcileStatus(PENDING/RECONCILED/DIFF)`。
- **人机验证（G-01）**：`captcha_challenge` 存 Redis、一次性消费、5 分钟有效，`verify_token` 供注册回填 `captchaToken`。

## 4. 关系说明

| 关系 | 基数 | 说明 |
|---|---|---|
| ACCOUNT — REALNAME_RECORD | 1 : N | 注册发起产生业务单，回调后落账户；重试/强实名增强产生多条 |
| ACCOUNT — WALLET_FLOW | 1 : N | 本人全部记账流水；查询做水平越权（IDOR）校验，越权报 2002 |
| ACCOUNT — WALLET_BINDING | 1 : N | 可绑定微信/支付宝多条；账号与实名不一致拒绝绑定（3002） |
| RECONCILE_TASK — WALLET_FLOW | M : N | 逻辑关联（按日期范围核对），非外键 |
| CAPTCHA_CHALLENGE | 独立 | Redis 实体，经 `verify_token` 与注册/登录流程逻辑关联 |

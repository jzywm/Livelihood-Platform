# services · 后端微服务

Java 17 + Spring Boot 3.5 微服务。当前为**单聚合服务**(`server`):先单体后拆,单体内部按业务域分包,后续按需拆分为独立 Maven 模块 / 服务。

## 结构

```
services/
├─ pom.xml        # 父 POM(聚合,依赖管理)
└─ server/        # 单聚合服务
   └─ src/main/java/com/minsheng/platform/
      └─ (domain.* 按业务域分包,预留拆分)
```

## 运行

```bash
cd services
mvn -pl server spring-boot:run    # http://localhost:8080
```

## 预留拆分边界(按业务域,对应《需求规格说明书》模块)

| 业务域 | 对应需求模块 | 未来服务(预留) |
|---|---|---|
| 账户 / 实名 / 信用 | I 平台账户系统、A 信用与监管 | `user-service` |
| 交易 / 溯源 / 维权 | B 透明溯源、D 交易维权、T 全产业透明交易 | `trade-service` |
| 物流 / 货运 | F 物流货运 | `logistics-service` |
| AI 能力 / 智能助手 | J 智能助手、K AI 能力中心 | `ai-service` |
| 政民互动 / 民生监督 | G 政民互动、H 民生建设监督 | `gov-service` |
| 平台治理 / 运营 | P 平台级能力、C 用工保障、E 社区生态 | `platform-service` |
| 网关 / 鉴权 | — | `gateway` |

> 说明:当前仅落地 `server` 单聚合服务;上表为**预留拆分边界**,待单体稳定后按域逐步抽出。

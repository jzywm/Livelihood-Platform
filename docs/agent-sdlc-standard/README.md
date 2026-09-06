# Agent 驱动软件开发 · 企业标准(方案 B)

> 面向 **10~100 人正式产品团队**的分层门禁 + Agent 治理开发标准。
> 对标:NIST SSDF SP 800-218、Microsoft SDL、OWASP SAMM / ASVS、SLSA、ISO 27001(参考对齐)。

## 这套标准解决什么问题

1. **提交安全**:代码在合并到 main / 发布之前,必须通过密钥扫描、SAST、SCA、构建、测试等分层门禁,任何人(包括 Agent)都无法绕过。
2. **Agent 可控**:使用 Agent 开发时,AI 的速度不绕过人的判断 —— Agent 有权限边界、有审计留痕、有人工评审。
3. **供应链可信**:发布物附带 SBOM、签名与来源证明,可复现、可追溯。

## 快速上手(三步)

1. **复制模板**:将 `templates/` 下的配置文件复制到你的仓库根目录(每个文件内有注释说明)。
2. **启用 CI**:将 `templates/.github/workflows/` 复制到仓库 `.github/workflows/`,并在 GitHub 仓库 Settings → Branches 中把 `pr-checks`、`codeql-analysis` 设为 **required status checks**。
3. **锁定分支**:管理员在仓库根目录运行 `templates/scripts/setup-branch-protection.ps1`,启用 main 分支保护(评审、签名、状态检查、merge queue)。
4. **对齐规范**:团队过一遍 `docs/` 六篇规范 + `checklists/` 三份清单(评审 / 安全 / 发布),并确定 CODEOWNERS 中的安全负责人。

## 五层门禁总览(核心架构)

| 门禁 | 触发时机 | 检查内容 | 工具 | 强制方式 |
|---|---|---|---|---|
| **G0 提交前** | `git commit` | 格式、Lint、密钥扫描、大文件 | pre-commit + Gitleaks | 本地 hook(CI 复验兜底) |
| **G1 推送前** | `git push` | 编译 + 单元测试(快、不联网) | git hooks / 本地脚本 | 本地(可选) |
| **G2 PR 检查** | 创建/更新 PR | SAST、SCA、构建、单测、覆盖率 | CodeQL + Semgrep + Dependabot | required status check |
| **G3 合并门** | 合并到 main 前 | 人工评审、提交签名、质量门、merge queue | 分支保护 + CODEOWNERS | 分支保护强制 |
| **G4 发布门** | 打 tag / 发版 | 镜像漏洞扫描、SBOM 生成与签名、发布审批 | Trivy + Syft + cosign | 发布流水线强制 |

> 详见 `docs/01-开发与Git规范.md` 与 `docs/05-发布与供应链安全.md`。

## 关键指标(SLO)

| 指标 | 目标 |
|---|---|
| 严重 / 高危漏洞进入 main | **0**(G2/G3 门禁阻断) |
| 密钥泄露进仓库事件 | **0**(G0 拦截 + G2 复验) |
| 漏洞响应 SLA | 严重(CRITICAL)≤ 24h;高危(HIGH)≤ 7 天 |
| 新代码单元测试覆盖率 | ≥ 80%(行 / 函数 / 分支) |
| PR 评审响应 SLA | ≤ 24h(工作时间) |
| 依赖更新 | 周级自动 PR;安全更新不排队、立即升级 |
| 发布产物 | 100% 附 SBOM + 签名,镜像扫描零高危 |

## 目录结构

```
agent-sdlc-standard/
├── README.md                  # 本文件:总览与快速上手
├── docs/                      # 规范文档(团队必读)
│   ├── 01-开发与Git规范.md
│   ├── 02-安全基线.md
│   ├── 03-评审与合并规范.md
│   ├── 04-威胁建模模板.md
│   ├── 05-发布与供应链安全.md
│   └── 06-Agent治理与操作SOP.md
├── checklists/                # 落地清单(评审/安全/发布时逐项勾选)
│   ├── PR评审Checklist.md
│   ├── 安全评审Checklist.md
│   └── 发布Checklist.md
└── templates/                 # 可直接复制的配置文件模板
    ├── .pre-commit-config.yaml
    ├── .gitleaks.toml
    ├── .semgrep.yaml
    ├── trivy.yaml
    ├── .trivyignore
    ├── renovate.json
    ├── .github/
    │   ├── dependabot.yml
    │   ├── CODEOWNERS
    │   └── workflows/
    │       ├── pr-checks.yml        # G2 门禁
    │       ├── codeql-analysis.yml  # G2 SAST 强化(每周定时)
    │       ├── merge-gate.yml       # G3 合并后主分支验证
    │       └── release.yml          # G4 发布门
    └── scripts/
        └── setup-branch-protection.ps1
```

## 文档导航

| 要解决什么 | 看哪里 |
|---|---|
| 分支怎么建、提交怎么写、怎么签名 | `docs/01-开发与Git规范.md` |
| 安全基线、密钥、漏洞 SLA | `docs/02-安全基线.md` |
| PR 怎么评审、谁有权合并 | `docs/03-评审与合并规范.md` |
| 高风险变更怎么分析威胁 | `docs/04-威胁建模模板.md` |
| 发布流程、SBOM、签名、回滚 | `docs/05-发布与供应链安全.md` |
| Agent 怎么用、权限与审批、审计 | `docs/06-Agent治理与操作SOP.md` |
| 具体配置文件怎么配 | `templates/` 各文件内注释 |
| 评审/发布时逐项打勾 | `checklists/` 三份清单 |

## 参考标准

- **NIST SSDF SP 800-218**:软件安全开发框架(门禁与证据链设计依据)
- **Microsoft SDL**:安全开发生命周期(全流程检查项)
- **OWASP ASVS / SAMM / Top 10**:应用安全验证与成熟度模型
- **SLSA**(slsa.dev):供应链安全等级(本方案对齐 L2~L3)
- **ISO 27001 / SOC 2**:发布与审计控制项参考(非认证要求,认证见方案 C)

## 落地节奏建议

| 周次 | 动作 |
|---|---|
| 第 1 周 | 复制模板、启用 CI、锁定分支、确定 CODEOWNERS;团队通读 `docs/01` `02` `06` |
| 第 2 周 | 试行 PR 评审 + 安全评审 checklist;补齐单测覆盖率;跑通一次威胁建模 |
| 第 3~4 周 | 打通发布门(release.yml + SBOM + 签名);回顾门禁拦截率与 MTTR,调整规则阈值 |

> 本目录为方案 B 的完整交付物;如需向方案 C(合规治理级)演进,可在此文档集上叠加审计证据链、IAM/SIEM、4-eyes 审批等控制项。

# 01 · 开发与 Git 规范

> 目的:统一分支、提交、签名与代码质量要求,让"代码进 main"的每一步都可审计、可回滚。
> 配套:`templates/.pre-commit-config.yaml`、`templates/scripts/setup-branch-protection.ps1`。

## 1. 分支模型(Trunk-Based + 短生命周期分支)

| 分支 | 用途 | 生命周期 | 谁可推送 |
|---|---|---|---|
| `main` | 唯一受保护主干,随时可发布 | 永久 | 仅通过 PR 合并(禁止直推) |
| `feature/<ticket>-<slug>` | 功能开发 | ≤ 3 天,频繁合并 | 所有开发者(含 Agent) |
| `fix/<ticket>-<slug>` | 缺陷修复 | 随 PR 关闭 | 所有开发者 |
| `release/<version>` | 发布分支(可选) | 发布后删除 | 发布负责人 |

规则:

- 分支名带工单号(`feature/AUTH-123-oidc-login`),CI 与评审可自动关联需求。
- 主干保持**始终可发布**:合并即部署候选。
- 禁止长期分支;分支超过 3 天未合并需说明原因(防止合并冲突放大)。

## 2. 提交规范(Conventional Commits)

提交信息必须符合 [Conventional Commits](https://www.conventionalcommits.org/),由 `conventional-pre-commit` hook(G0)强制:

```
<type>(<scope>): <subject>

[body: 为什么改、怎么验证]
```

| type | 含义 | 对 release notes 的影响 |
|---|---|---|
| `feat` | 新功能 | 记为 minor |
| `fix` | 缺陷修复 | 记为 patch |
| `perf` | 性能优化 | 记为 patch |
| `refactor` | 重构(无行为变化) | 不记录 |
| `docs` / `test` / `chore` / `ci` / `build` | 文档/测试/杂务/CI/构建 | 不记录 |

附加要求:

- **Agent 提交必须打标**:Agent 生成的提交在 subject 前加 `[AI]`,例如 `feat(auth): [AI] 增加 OIDC 回调处理`。便于抽查审计(见 `docs/06`)。
- **一个提交只做一件事**:提交粒度 = 一个可独立回滚的逻辑单元。
- **禁止混合提交**:格式化、依赖升级、功能改动分开提交。

## 3. 提交签名(强制)

所有提交必须签名(对应 G3 门禁的 `required_signatures`)。

- 推荐 **SSH 签名**(配置简单)或 GPG。
- 配置示例:

```bash
# SSH 签名
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
# 生成 SSH 签名密钥并添加到 GitHub:Settings → SSH and GPG keys → New SSH key(Key type: Signing Key)
```

- 未签名的提交在分支保护下**无法合并**。

## 4. 分支保护(必须启用)

在 GitHub 仓库 Settings → Branches → Add branch protection rule(`main`)启用,或在 CI 中运行 `setup-branch-protection.ps1`:

| 规则 | 取值 | 目的 |
|---|---|---|
| Require a pull request before merging | 是 | 禁止直推 |
| Required approvals | ≥ 1(高风险目录见 CODEOWNERS 双审) | 人工评审 |
| Dismiss stale reviews | 是 | 新提交后旧评审失效 |
| Require review from Code Owners | 是 | 敏感目录必审 |
| Require status checks to pass | `pr-checks`、`codeql-analysis` | G2 门禁强制 |
| Require signed commits | 是 | 提交签名 |
| Require merge queue | 是(SQUASH) | 串行合并防踩踏 |
| Do not allow force pushes / deletions | 是 | 历史不可篡改 |
| Require conversation resolution | 是 | 评论必须解决 |

## 5. 代码质量要求(进入 PR 的最低标准)

| 检查项 | 要求 | 门禁 |
|---|---|---|
| 格式 | 统一 formatter(ruff-format / prettier / gofmt 等) | G0 |
| Lint | 静态检查零错误、零警告(配置 `--max-warnings 0`) | G0 + G2 |
| 密钥扫描 | Gitleaks 零命中(白名单见 `.gitleaks.toml`) | G0 + G2 |
| 单元测试 | 新代码行覆盖率 ≥ 80%;函数 ≥ 80%;分支 ≥ 75% | G2 |
| 构建 | 必须可复现构建通过 | G2 |
| 依赖 | 新增依赖需在 PR 描述说明用途与替代评估 | G2 评审 |

## 6. 依赖变更规范

- 依赖版本一律**锁定**(`package-lock.json` / `uv.lock` / `go.sum` 等提交进仓库)。
- 依赖升级走自动化:`Dependabot`(GitHub 原生)或 `Renovate`(`templates/renovate.json`),见 `docs/05`。
- **安全更新优先**:涉及已知漏洞的升级不排队、不降级处理。
- 大版本升级(major)必须人工评审,并跑通全量测试 + 威胁建模复核(如涉及身份/加密)。

## 7. Definition of Done(DoD)

一个功能"完成"必须同时满足:

- [ ] 代码通过 G0~G3 全部门禁,无高危漏洞、无密钥泄露
- [ ] 单元测试覆盖新代码 ≥ 80%,关键路径有集成测试
- [ ] PR 经人工评审(高风险变更双审),评论全部 resolved
- [ ] 提交已签名,commit message 符合规范(Agent 提交带 `[AI]` 标记)
- [ ] 文档(README / API)已更新
- [ ] 变更记录(conventional commits)可生成 release notes
- [ ] 若涉及高风险变更,威胁建模结论已通过(`checklists/安全评审Checklist.md`)

## 8. 评审与合并

- 合并方式统一 **Squash and merge**,保证 main 历史线性(配合 merge queue)。
- 评审要求、角色与时限见 `docs/03-评审与合并规范.md`。
- 拒绝合并的硬条件:门禁红、未签名、无评审、密钥扫描命中、覆盖率不达标、高风险变更未做威胁建模。

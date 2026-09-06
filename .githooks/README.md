# .githooks · 本地提交门禁(G0 本地层)

本目录存放**提交前物理门禁** hook,与 AI Skill `commit-check` 配合,构成"且"关系的双重提交检查。

## hook 清单

| 文件 | 阶段 | 检查内容 |
|---|---|---|
| `pre-commit` | `git commit` 前 | 合并冲突标记、行尾空白、>1MB 大文件、私钥/高置信密钥、真实 `.env` 文件 |
| `commit-msg` | 写提交信息后 | Conventional Commits 格式 |

## 启用(每个克隆仓库执行一次)

```bash
git config core.hooksPath .githooks
```

> `core.hooksPath` 是仓库本地配置(`.git/config`),不会被提交;新克隆者需各自执行一次。
> Windows 下 Git 自带 `sh`,脚本 `#!/bin/sh` 可直接运行;Linux/macOS 需 `chmod +x .githooks/pre-commit .githooks/commit-msg`。

## 说明

- 本地 hook 可被 `git commit --no-verify` 绕过;真正"不可跳过"由 CI 的 G2 门禁(agent-sdlc-standard)兜底复验。
- hook 只做**确定性**机器检查;命名/注释语言/SQL/XSS/测试/`[AI]` 标记等**语义级**检查由 AI Skill `commit-check` 完成。
- 完整约束见根目录 `DEVELOPMENT_CONSTRAINTS.md` 与 `docs/agent-sdlc-standard/`。

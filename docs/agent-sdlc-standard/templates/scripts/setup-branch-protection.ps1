# ============================================================
# 一键配置 GitHub main 分支保护 (G3 合并门)
# 前置条件:
#   1. gh CLI 已安装并登录: gh auth login (权限: repo admin)
#   2. 在仓库中已启用 pr-checks / codeql-analysis 工作流 (至少各跑过一次)
# 用法(在仓库根目录):
#   .\setup-branch-protection.ps1 -Owner <org> -Repo <repo> [-AdminTeam <team>]
# ============================================================

param(
    [Parameter(Mandatory)][string]$Owner,
    [Parameter(Mandatory)][string]$Repo,
    [string]$AdminTeam = "platform-owners"
)

$ErrorActionPreference = "Stop"
$repo = "$Owner/$Repo"

Write-Host "==> 配置分支保护: $repo (main) =="

# 注意: required status checks 的名称必须与 workflow 的 name 字段一致
$body = @{
    required_status_checks = @{
        strict = $true                          # 合并前基于最新 main 重新检查
        contexts = @(
            "pr-checks",                        # G2 门禁
            "codeql-analysis"                   # CodeQL
            # 如启用 merge-gate 且作为 required check, 加入 "merge-gate"
        )
    }
    enforce_admins = $true                      # 管理员同样受限
    required_pull_request_reviews = @{
        required_approving_review_count = 1     # 至少 1 人批准
        dismiss_stale_reviews = $true           # 新提交后旧评审失效
        require_code_owner_reviews = $true      # 敏感目录 Code Owner 必审
        require_last_push_approval = $true      # 最后推送者不能是批准者
    }
    restrictions = @{
        apps = @()
        users = @()
        teams = @($AdminTeam)                   # 仅管理员团队可绕过(仍需评审)
    }
    required_linear_history = $true             # 线性历史 (配合 Squash)
    allow_force_pushes = $false
    allow_deletions = $false
    required_conversation_resolution = $true    # 评论必须 resolved
    required_signatures = $true                 # 提交签名强制
    required_merge_queue = $true                # merge queue (需 GH Team/Enterprise)
    merge_queue_parameters = @{
        max_entries_to_build = 5
        min_entries_to_merge = 1
        merge_method = "SQUASH"
    }
} | ConvertTo-Json -Depth 10

Write-Host "--> 写入分支保护规则..."
$body | gh api --method PUT "repos/$repo/branches/main/protection" --input -

Write-Host "==> 分支保护已启用 =="
Write-Host "   - PR 必审 / 签名必检 / 状态检查必过 / merge queue 已开"
Write-Host "   - 检查项: pr-checks, codeql-analysis (按需加 merge-gate)"
Write-Host "提示: 若 organization 策略要求, 也可在 org 层面设为默认分支保护"

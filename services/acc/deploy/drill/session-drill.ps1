<#
.SYNOPSIS
  双 token 会话闭环演练（登录 → 业务接口 → 换发 → 旧 refresh 重放被拒且整族吊销 → 重新登录取新对 → 登出后立即 401）。

.DESCRIPTION
  前提（两条独立命令，见 deploy/drill/README.md §3）：
    ① ACC 真机桩已起：`drill.AccDrill`（内嵌真实 MariaDB 33061 + **内嵌真实 Redis 6380**，
       `acc.session.store=redis` + `acc.redis.host/port` 指向该 Redis）；
    ② 网关 fat jar 已起（18081，`GATEWAY_STORE=redis` + `GATEWAY_REDIS_HOST/PORT` 指向同一个 Redis）。

  闭环链与本脚本产出（逐项原始输出落在 -EvidenceDir）：
    0  预检：网关 /gateway/health 报 redis=up；Redis PING=PONG
    1  登录：GET /api/v1/acc/captcha?type=IMAGE → 从**真实 Redis** 读回挑战答案 →
       POST /api/v1/acc/captcha/verify 取一次性票据 → POST /api/v1/acc/auth/login
       （断言：200；响应体只有短 token、无 refreshToken 字段；Set-Cookie 带 HttpOnly/Secure/SameSite/Path）
    2  短 token 访问 GET /api/v1/acc/me → 200
    3  Cookie 换发 POST /api/v1/acc/auth/refresh → 200 + 新短 token + 新 Set-Cookie
    4  **等待超过 5s 轮换宽限窗口**后重放旧 refresh → 401 + 2001，且整族吊销：
       原短 token 访问 /api/v1/acc/me → 401（网关从 Redis 的 `revoked:jti:{jti}` 读到吊销）
    5  重新登录取新 token 对 → 200
    6  POST /api/v1/acc/auth/logout → 200（Max-Age=0 清 Cookie），随后同一短 token → 401（网关侧证据）
    7  Redis 键路径与语义（L4）：`acc:session:{familyId}` / `acc:refresh:{jti}`（TTL ≤ 7 天）/
       `revoked:jti:{jti}`（TTL = 短 token 剩余有效期）逐键 TYPE+TTL

  说明：refresh Cookie 按生产口径带 `Secure`，curl 的 cookie 引擎不会在 http 链路回带，故脚本从
  `Set-Cookie` 头解析出长 token 并以**显式 Cookie 头**回放（等价于浏览器行为，且不放松生产属性）。

  用法：
    powershell -NoProfile -ExecutionPolicy Bypass -File services/acc/deploy/drill/session-drill.ps1

  退出码：0 = 全部断言通过；1 = 存在失败项（详见 summary.txt）。
#>
[CmdletBinding()]
param(
    [string]$GatewayBase = 'http://127.0.0.1:18081',
    [string]$Mobile = '13800138000',
    [string]$RedisHost = '127.0.0.1',
    [int]$RedisPort = 6380,
    [int]$GraceWaitSeconds = 6,
    [string]$CookieName = 'refresh_token',
    [string]$EvidenceDir = 'D:\progrom\.superpowers\sdd\add-refresh-token-rotation\drill',
    [string]$AccLog = '',
    [string]$GatewayLog = ''
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
if (-not $AccLog) { $AccLog = Join-Path $EvidenceDir 'acc-stdout.log' }
if (-not $GatewayLog) { $GatewayLog = Join-Path $EvidenceDir 'gateway-stdout.log' }

$script:checks = New-Object System.Collections.Generic.List[object]

function Write-Evidence {
    param([string]$Name, [string]$Text)
    $Text | Out-File -FilePath (Join-Path $EvidenceDir $Name) -Encoding utf8
    Write-Host "[evidence] $Name"
}

function Assert-Step {
    param([string]$Id, [string]$Expect, [string]$Actual, [bool]$Pass)
    $script:checks.Add([pscustomobject]@{ Id = $Id; Expect = $Expect; Actual = $Actual; Pass = $Pass })
    $mark = 'FAIL'
    if ($Pass) { $mark = 'PASS' }
    Write-Host "[$mark] $Id | 期望: $Expect | 实际: $Actual"
}

function Short {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) { return '<空>' }
    if ($Value.Length -le 18) { return $Value }
    return $Value.Substring(0, 18) + '…'
}

# 摘要里对 token 原文做脱敏（原始报文仍在取证文件里，摘要与终端不留凭据原文）。
function Redact {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    return ($Text -replace 'eyJ[A-Za-z0-9_\-\.]{10,}', '<jwt-redacted>')
}

# ---------- Redis RESP 客户端（无 redis-cli，用 TcpClient 直连；只读命令，不改任何键） ----------

function Read-RedisLine {
    param([System.IO.Stream]$Stream)
    $bytes = New-Object System.Collections.Generic.List[byte]
    while ($true) {
        $b = $Stream.ReadByte()
        if ($b -lt 0) { break }
        if ($b -eq 13) { [void]$Stream.ReadByte(); break }
        $bytes.Add([byte]$b)
    }
    return [System.Text.Encoding]::UTF8.GetString($bytes.ToArray())
}

function Read-RedisReply {
    param([System.IO.Stream]$Stream)
    $line = Read-RedisLine -Stream $Stream
    if ($null -eq $line) { return $null }
    if ($line.StartsWith('+')) { return $line.Substring(1) }
    if ($line.StartsWith('-')) { return "ERR $($line.Substring(1))" }
    if ($line.StartsWith(':')) { return [long]$line.Substring(1) }
    if ($line.StartsWith('$')) {
        $len = [int]$line.Substring(1)
        if ($len -lt 0) { return $null }
        $buf = New-Object byte[] $len
        $read = 0
        while ($read -lt $len) {
            $n = $Stream.Read($buf, $read, $len - $read)
            if ($n -le 0) { break }
            $read += $n
        }
        [void](Read-RedisLine -Stream $Stream)
        return [System.Text.Encoding]::UTF8.GetString($buf, 0, $read)
    }
    if ($line.StartsWith('*')) {
        $count = [int]$line.Substring(1)
        if ($count -lt 0) { return $null }
        $items = @()
        for ($i = 0; $i -lt $count; $i++) { $items += , (Read-RedisReply -Stream $Stream) }
        # 平铺返回（不额外包一层）：调用方用 @(...) 收集即得到逐个键，foreach 才能逐键取 TYPE/TTL
        return $items
    }
    return $line
}

function Invoke-Redis {
    param([string[]]$Command)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect($RedisHost, $RedisPort)
        $stream = $client.GetStream()
        $sb = New-Object System.Text.StringBuilder
        [void]$sb.Append("*$($Command.Count)`r`n")
        foreach ($arg in $Command) {
            $argBytes = [System.Text.Encoding]::UTF8.GetBytes([string]$arg)
            [void]$sb.Append("`$$($argBytes.Length)`r`n$arg`r`n")
        }
        $payload = [System.Text.Encoding]::UTF8.GetBytes($sb.ToString())
        $stream.Write($payload, 0, $payload.Length)
        $stream.Flush()
        return Read-RedisReply -Stream $stream
    }
    finally { $client.Close() }
}

# ---------- HTTP（curl.exe：headers/body 分别落盘，便于逐项取证） ----------

function Invoke-Api {
    param([string]$Name, [string]$Method, [string]$Url, [string[]]$Headers, [string]$JsonBody)
    $headerFile = Join-Path $EvidenceDir "$Name-headers.txt"
    $bodyFile = Join-Path $EvidenceDir "$Name-body.txt"
    $curlArgs = @('-s', '-X', $Method, '-D', $headerFile, '-o', $bodyFile, '-w', '%{http_code}',
        '--max-time', '15')
    if ($JsonBody) {
        $bodyPath = Join-Path $EvidenceDir "$Name-request.json"
        $JsonBody | Out-File -FilePath $bodyPath -Encoding ascii
        $curlArgs += @('-H', 'Content-Type: application/json', '--data-binary', "@$bodyPath")
    }
    foreach ($h in @($Headers)) {
        if ($h) { $curlArgs += @('-H', $h) }
    }
    $curlArgs += $Url
    $code = & curl.exe @curlArgs
    return [int]$code
}

function Get-HeaderLine {
    param([string]$Name, [string]$Pattern)
    $file = Join-Path $EvidenceDir "$Name-headers.txt"
    if (-not (Test-Path $file)) { return '' }
    $hit = Get-Content $file -Encoding UTF8 | Where-Object { $_ -match $Pattern } | Select-Object -First 1
    if ($null -eq $hit) { return '' }
    return $hit.Trim()
}

function Get-SetCookieLine {
    param([string]$Name)
    return (Get-HeaderLine -Name $Name -Pattern "^Set-Cookie:\s*$CookieName=")
}

function Get-SetCookieValue {
    param([string]$Name)
    $line = Get-SetCookieLine -Name $Name
    if (-not $line) { return $null }
    if ($line -match "$CookieName=([^;]+)") { return $Matches[1] }
    return $null
}

function Get-Body {
    param([string]$Name)
    $file = Join-Path $EvidenceDir "$Name-body.txt"
    if (-not (Test-Path $file)) { return '' }
    return (Get-Content $file -Raw -Encoding UTF8)
}

function Get-JwtPayload {
    param([string]$Token)
    $part = $Token.Split('.')[1]
    $padded = $part.Replace('-', '+').Replace('_', '/')
    while ($padded.Length % 4 -ne 0) { $padded += '=' }
    return ([System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($padded)) | ConvertFrom-Json)
}

# ---------- 组合动作 ----------

function New-Login {
    param([string]$NamePrefix)
    $code = Invoke-Api -Name "$NamePrefix-captcha" -Method GET -Url "$GatewayBase/api/v1/acc/captcha?type=IMAGE"
    $captchaId = (Get-Body "$NamePrefix-captcha" | ConvertFrom-Json).data.captchaId
    if ($code -ne 200 -or -not $captchaId) { throw "$NamePrefix 挑战下发失败: http=$code" }
    # 挑战答案只在服务端：演练脚本以真实 Redis 客户端读取（等价于「知道答案的真人」）
    $answerRaw = [string](Invoke-Redis -Command @('GET', "acc:captcha:$captchaId"))
    Write-Evidence "$NamePrefix-redis-captcha.txt" "GET acc:captcha:$captchaId -> $answerRaw"
    $answer = $answerRaw.Split(':')[1]
    $body = @{ captchaId = $captchaId; code = $answer } | ConvertTo-Json -Compress
    $code = Invoke-Api -Name "$NamePrefix-verify" -Method POST -Url "$GatewayBase/api/v1/acc/captcha/verify" -JsonBody $body
    $captchaToken = (Get-Body "$NamePrefix-verify" | ConvertFrom-Json).data.verifyToken
    if ($code -ne 200 -or -not $captchaToken) { throw "$NamePrefix 票据换取失败: http=$code" }
    $body = @{ mobile = $Mobile; captchaToken = $captchaToken } | ConvertTo-Json -Compress
    $code = Invoke-Api -Name "$NamePrefix-login" -Method POST -Url "$GatewayBase/api/v1/acc/auth/login" -JsonBody $body
    $raw = Get-Body "$NamePrefix-login"
    $json = $raw | ConvertFrom-Json
    return [pscustomobject]@{
        Http        = $code
        Raw         = $raw
        Json        = $json
        AccessToken = $json.data.accessToken
        SetCookie   = (Get-SetCookieLine "$NamePrefix-login")
        Refresh     = (Get-SetCookieValue "$NamePrefix-login")
    }
}

# ---------- 演练主流程 ----------

Write-Host "=== 双 token 会话闭环演练 $(Get-Date -Format o) ==="
Write-Host "网关: $GatewayBase | Redis: ${RedisHost}:${RedisPort} | 取证: $EvidenceDir"

# 0) 预检
$health = & curl.exe -s --max-time 10 "$GatewayBase/gateway/health"
Write-Evidence 'step0-gateway-health.txt' $health
$ping = [string](Invoke-Redis -Command @('PING'))
Write-Evidence 'step0-redis-ping.txt' "PING -> $ping"
Assert-Step '0.1' '网关 /gateway/health 报 redis=up（网关与 ACC 指向同一 Redis 实例）' $health ($health -match '"redis":"up"')
Assert-Step '0.2' '内嵌真实 Redis 可 PING' $ping ($ping -eq 'PONG')

# 1) 登录（真实库账户 1001 / 13800138000）
$login1 = New-Login -NamePrefix 'step1'
$access1 = $login1.AccessToken
$refresh1 = $login1.Refresh
$claims1 = Get-JwtPayload $access1
Write-Evidence 'step1d-login-claims.txt' (($claims1 | ConvertTo-Json -Compress))
Assert-Step '1.1' 'POST /api/v1/acc/auth/login 200（网关白名单放行 → 真实 ACC → 真实库）' "http=$($login1.Http) accountId=$($login1.Json.data.accountId)" ($login1.Http -eq 200 -and $login1.Json.data.accountId -eq 'acc_1001')
Assert-Step '1.2' '响应体只有短 token（无 refreshToken 字段、无长 token 原文）' (Redact $login1.Raw) ($login1.Raw -notmatch 'refreshToken' -and $access1)
Assert-Step '1.3' 'Set-Cookie 四属性齐备（HttpOnly/Secure/SameSite=Lax/Path=/api/v1/acc/auth）+ Max-Age=7 天' (Redact $login1.SetCookie) (($login1.SetCookie -match 'HttpOnly') -and ($login1.SetCookie -match 'Secure') -and ($login1.SetCookie -match 'SameSite=Lax') -and ($login1.SetCookie -match 'Path=/api/v1/acc/auth') -and ($login1.SetCookie -match 'Max-Age=604800'))
Assert-Step '1.4' '短 token 声明含 sub/role/mfa/jti/iat/exp/fam 且 exp-iat=900s' "sub=$($claims1.sub) jti=$(Short $claims1.jti) fam=$(Short $claims1.fam) ttl=$([long]$claims1.exp - [long]$claims1.iat)" (($claims1.sub -eq '1001') -and $claims1.jti -and $claims1.fam -and (([long]$claims1.exp - [long]$claims1.iat) -eq 900))

# 2) 短 token 访问业务接口
$code = Invoke-Api -Name 'step2-me' -Method GET -Url "$GatewayBase/api/v1/acc/me" -Headers @("Authorization: Bearer $access1")
$meBody = Get-Body 'step2-me'
Assert-Step '2.1' '带短 token 访问 /api/v1/acc/me → 200 且返回真实账户' "http=$code body=$meBody" ($code -eq 200 -and $meBody -match '"accountId":"acc_1001"')

# 3) 换发（Cookie 换发 → 新短 token + 新 Cookie）
$code = Invoke-Api -Name 'step3-refresh' -Method POST -Url "$GatewayBase/api/v1/acc/auth/refresh" -Headers @("Cookie: $CookieName=$refresh1")
$refresh3Body = Get-Body 'step3-refresh'
$access2 = ($refresh3Body | ConvertFrom-Json).data.accessToken
$refresh2 = Get-SetCookieValue 'step3-refresh'
$jti1 = $claims1.jti
$family = $claims1.fam
$familyAfterRotate = [string](Invoke-Redis -Command @('GET', "acc:session:$family"))
Write-Evidence 'step3-redis-family.txt' "GET acc:session:$family ->`r`n$familyAfterRotate"
Assert-Step '3.1' 'Cookie 换发 POST /api/v1/acc/auth/refresh → 200 + 新短 token' "http=$code access2=$(Short $access2)" ($code -eq 200 -and $access2 -and $access2 -ne $access1)
Assert-Step '3.2' '换发响应带新 Set-Cookie（长 token 轮换，值已变）' (Redact (Get-SetCookieLine 'step3-refresh')) ($refresh2 -and $refresh2 -ne $refresh1)
Assert-Step '3.3' 'Redis 族记录：currentJti 前移且旧 jti 进已轮换标记（rotation marker 保留）' "len=$($familyAfterRotate.Length)" ($familyAfterRotate -match 'rotated' -and $familyAfterRotate -match [regex]::Escape($jti1))

# 4) 重放旧 refresh（必须超出 5s 并发宽限窗口）
Write-Host "等待 $GraceWaitSeconds 秒（轮换并发宽限窗口 5s）后重放旧 refresh…"
Start-Sleep -Seconds $GraceWaitSeconds
$code = Invoke-Api -Name 'step4-replay' -Method POST -Url "$GatewayBase/api/v1/acc/auth/refresh" -Headers @("Cookie: $CookieName=$refresh1")
$replayBody = Get-Body 'step4-replay'
$replayJson = $replayBody | ConvertFrom-Json
$familyAfterReplay = [string](Invoke-Redis -Command @('GET', "acc:session:$family"))
$revokedValue = [string](Invoke-Redis -Command @('GET', "revoked:jti:$jti1"))
$revokedTtl = [long](Invoke-Redis -Command @('TTL', "revoked:jti:$jti1"))
Write-Evidence 'step4-redis-family.txt' "GET acc:session:$family ->`r`n$familyAfterReplay"
Write-Evidence 'step4-redis-revoked.txt' "GET revoked:jti:$jti1 -> $revokedValue`r`nTTL revoked:jti:$jti1 -> $revokedTtl"
Assert-Step '4.1' '重放旧 refresh → 401 + 2001' "http=$code code=$($replayJson.code) msg=$($replayJson.message)" ($code -eq 401 -and $replayJson.code -eq 2001)
Assert-Step '4.2' '整族吊销：族记录 status=REVOKED（记录保留，重放可识别为已吊销族）' "len=$($familyAfterReplay.Length)" ($familyAfterReplay -match 'REVOKED')
Assert-Step '4.3' "吊销名单按网关契约写 `revoked:jti:{jti}`（TTL=剩余有效期，1..900）" "value=$revokedValue ttl=$revokedTtl" ($revokedValue -eq '1' -and $revokedTtl -ge 1 -and $revokedTtl -le 900)
$code = Invoke-Api -Name 'step4-revoked-access' -Method GET -Url "$GatewayBase/api/v1/acc/me" -Headers @("Authorization: Bearer $access1")
$revokedAccessBody = Get-Body 'step4-revoked-access'
Assert-Step '4.4' '原短 token 立即 401（网关读 Redis 吊销名单，非本地缓存）' "http=$code body=$revokedAccessBody" ($code -eq 401 -and $revokedAccessBody -match '"code":2001')
$code = Invoke-Api -Name 'step4-new-access-after-revoke' -Method GET -Url "$GatewayBase/api/v1/acc/me" -Headers @("Authorization: Bearer $access2")
Assert-Step '4.5' '换发出的第二个短 token 也被整族吊销 → 401' "http=$code" ($code -eq 401)

# 5) 重新登录取新对
$login2 = New-Login -NamePrefix 'step5'
$access3 = $login2.AccessToken
$refresh3 = $login2.Refresh
$claims3 = Get-JwtPayload $access3
Assert-Step '5.1' '重新登录取新 token 对 → 200 且新族与旧族不同' "http=$($login2.Http) fam=$(Short $claims3.fam)" ($login2.Http -eq 200 -and $access3 -and $claims3.fam -ne $family)
$code = Invoke-Api -Name 'step5-me' -Method GET -Url "$GatewayBase/api/v1/acc/me" -Headers @("Authorization: Bearer $access3")
Assert-Step '5.2' '新短 token 可用（/api/v1/acc/me → 200）' "http=$code" ($code -eq 200)

# 6) 登出 → 短 token 立即失效（网关侧证据）
$code = Invoke-Api -Name 'step6-logout' -Method POST -Url "$GatewayBase/api/v1/acc/auth/logout" -Headers @("Authorization: Bearer $access3")
$logoutCode = $code
$logoutJson = Get-Body 'step6-logout' | ConvertFrom-Json
$clearCookie = Get-SetCookieLine 'step6-logout'
$jti3 = $claims3.jti
$logoutTtl = [long](Invoke-Redis -Command @('TTL', "revoked:jti:$jti3"))
Write-Evidence 'step6-redis-revoked.txt' "GET revoked:jti:$jti3 -> $([string](Invoke-Redis -Command @('GET', "revoked:jti:$jti3")))`r`nTTL revoked:jti:$jti3 -> $logoutTtl"
Assert-Step '6.1' 'POST /api/v1/acc/auth/logout → 200 + revoked=true + 清 Cookie（Max-Age=0）' "http=$logoutCode revoked=$($logoutJson.data.revoked) cookie=$(Redact $clearCookie)" ($logoutCode -eq 200 -and $logoutJson.data.revoked -eq $true -and $clearCookie -match 'Max-Age=0')
$code = Invoke-Api -Name 'step6-after-logout-me' -Method GET -Url "$GatewayBase/api/v1/acc/me" -Headers @("Authorization: Bearer $access3")
$afterLogoutBody = Get-Body 'step6-after-logout-me'
Assert-Step '6.2' '登出后同一短 token 立即 401（网关侧证据，code=2001）' "http=$code body=$afterLogoutBody" ($code -eq 401 -and $afterLogoutBody -match '"code":2001')
Assert-Step '6.3' '登出吊销 TTL = 短 token 剩余有效期（1..900）' "ttl=$logoutTtl" ($logoutTtl -ge 1 -and $logoutTtl -le 900)

# 6b) 幂等：重复登出仍成功——经网关会被吊销名单拦下（401），故**直连 ACC** 观测 ACC 侧幂等语义
$code = Invoke-Api -Name 'step6b-logout-direct' -Method POST -Url 'http://127.0.0.1:8080/acc/auth/logout' `
    -Headers @("Authorization: Bearer $access3", 'X-User-Id: 1001', 'X-User-Role: CONSUMER', 'X-User-Mfa: false', "X-User-Jti: $jti3")
$againJson = Get-Body 'step6b-logout-direct' | ConvertFrom-Json
Assert-Step '6.4' '重复登出幂等（直连 ACC：仍 200 且 revoked=false 表示未再次改变状态）' "http=$code revoked=$($againJson.data.revoked)" ($code -eq 200 -and $againJson.data.revoked -eq $false)

# 7) Redis 键路径与语义核验（L4：真实 Redis 上的键/TTL 行为）
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# 键路径与语义核验 $(Get-Date -Format o)（Redis ${RedisHost}:${RedisPort}）")
foreach ($pattern in @('acc:session:*', 'acc:refresh:*', 'revoked:jti:*')) {
    $keys = @(Invoke-Redis -Command @('KEYS', $pattern))
    $lines.Add("KEYS $pattern -> $($keys.Count) 个")
    foreach ($key in $keys) {
        $type = [string](Invoke-Redis -Command @('TYPE', $key))
        $ttl = [long](Invoke-Redis -Command @('TTL', $key))
        $lines.Add("  $key type=$type ttl=$ttl")
    }
}
$refreshKeys = @(Invoke-Redis -Command @('KEYS', 'acc:refresh:*'))
$maxRefreshTtl = 0
foreach ($key in $refreshKeys) {
    $ttl = [long](Invoke-Redis -Command @('TTL', $key))
    if ($ttl -gt $maxRefreshTtl) { $maxRefreshTtl = $ttl }
}
$revokedKeys = @(Invoke-Redis -Command @('KEYS', 'revoked:jti:*'))
$maxRevokedTtl = 0
foreach ($key in $revokedKeys) {
    $ttl = [long](Invoke-Redis -Command @('TTL', $key))
    if ($ttl -gt $maxRevokedTtl) { $maxRevokedTtl = $ttl }
}
$lines.Add("acc:refresh:* 最大 TTL = $maxRefreshTtl（须 ≤ 604800 = 7 天）")
$lines.Add("revoked:jti:* 最大 TTL = $maxRevokedTtl（须 ≤ 900 = 短 token 有效期）")
$inventory = $lines -join "`r`n"
Write-Evidence 'step7-redis-inventory.txt' $inventory
Assert-Step '7.1' '会话键路径与语义：acc:refresh:{jti} TTL ≤ 7 天' "maxTtl=$maxRefreshTtl" ($maxRefreshTtl -ge 1 -and $maxRefreshTtl -le 604800)
Assert-Step '7.2' '网关共享吊销契约：revoked:jti:{jti} TTL ≤ 短 token 有效期' "maxTtl=$maxRevokedTtl" ($maxRevokedTtl -ge 1 -and $maxRevokedTtl -le 900)
Assert-Step '7.3' '三类键均落在同一真实 Redis 实例' "session=$(@(Invoke-Redis -Command @('KEYS','acc:session:*')).Count) refresh=$($refreshKeys.Count) revoked=$($revokedKeys.Count)" ((@(Invoke-Redis -Command @('KEYS', 'acc:session:*')).Count -ge 1) -and ($refreshKeys.Count -ge 1) -and ($revokedKeys.Count -ge 1))

# 8) 审计与网关侧日志证据（不落 token 原文）
$auditLines = @()
if (Test-Path $AccLog) {
    $auditLines = @(Get-Content $AccLog | Select-String -Pattern 'SESSION_REFRESH_REPLAY|SESSION_LOGOUT' | ForEach-Object { $_.Line })
}
Write-Evidence 'step8-audit.log' (($auditLines -join "`r`n"))
$gwLines = @()
if (Test-Path $GatewayLog) {
    $gwLines = @(Get-Content $GatewayLog | Select-String -Pattern '鉴权失败' | Select-Object -Last 8 | ForEach-Object { $_.Line })
}
Write-Evidence 'step8-gateway-401.log' (($gwLines -join "`r`n"))
Assert-Step '8.1' 'ACC 审计事件：重放整族吊销 + 登出吊销各一条（不含 token 原文）' "$($auditLines.Count) 行" (($auditLines -join ' ') -match 'SESSION_REFRESH_REPLAY' -and ($auditLines -join ' ') -match 'SESSION_LOGOUT' -and ($auditLines -join ' ') -notmatch 'eyJ')

# 汇总
$failed = @($script:checks | Where-Object { -not $_.Pass })
$summary = New-Object System.Collections.Generic.List[string]
$summary.Add("# 双 token 会话闭环演练摘要 $(Get-Date -Format o)")
$summary.Add("网关=$GatewayBase Redis=${RedisHost}:${RedisPort} 账户=$Mobile 取证目录=$EvidenceDir")
$summary.Add("")
$summary.Add("| # | 期望 | 实际 | 结果 |")
$summary.Add("|---|---|---|---|")
foreach ($c in $script:checks) {
    $mark = '❌ FAIL'
    if ($c.Pass) { $mark = '✅ PASS' }
    $summary.Add("| $($c.Id) | $($c.Expect) | $($c.Actual) | $mark |")
}
$summary.Add("")
$summary.Add("合计 $($script:checks.Count) 项，失败 $($failed.Count) 项。")
$summaryText = $summary -join "`r`n"
Write-Evidence 'summary.txt' $summaryText
Write-Host $summaryText
if ($failed.Count -gt 0) { exit 1 }
exit 0

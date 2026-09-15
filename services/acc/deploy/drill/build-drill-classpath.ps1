<#
.SYNOPSIS
  构建 ACC 真机联调桩（deploy/drill/AccDrill.java）的运行 classpath 并编译。

.DESCRIPTION
  1) 生成含 test 作用域依赖的模块 classpath（演练桩需要 mariaDB4j / mariadb-java-client）；
  2) 修正版本遮蔽：test 作用域的 mariaDB4j 会把 javax 时代的 jakarta.annotation-api 1.3.5
     拉到依赖调解的最前，导致 Tomcat 启动报 NoClassDefFoundError: jakarta/annotation/PostConstruct；
     脚本剔除 1.3.5 并置于本地仓库中的 2.1.1（与 Spring Boot 3.5 对齐）；
  3) 编译演练桩到 target/drill-classes。

  产物：target/drill-cp-final.txt（运行用 classpath）、target/drill-classes/。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$moduleDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $moduleDir
try {
    Write-Host "[drill] 生成 classpath（含 test 作用域）..."
    & mvn -q test-compile dependency:build-classpath "-Dmdep.includeScope=test" "-Dmdep.outputFile=target/drill-cp.txt"
    if ($LASTEXITCODE -ne 0) { throw "mvn dependency:build-classpath 失败（exit=$LASTEXITCODE）" }

    $localRepo = (& mvn -q help:evaluate "-Dexpression=settings.localRepository" "-DforceStdout" | Select-Object -Last 1).Trim()
    $jakarta211 = Join-Path $localRepo 'jakarta\annotation\jakarta.annotation-api\2.1.1\jakarta.annotation-api-2.1.1.jar'
    if (-not (Test-Path $jakarta211)) {
        throw "本地仓库缺少 $jakarta211（请先执行 mvn dependency:get -Dartifact=jakarta.annotation:jakarta.annotation-api:2.1.1）"
    }

    $entries = (Get-Content 'target\drill-cp.txt' -Raw).Trim().Split(';') |
        Where-Object { $_ -and ($_ -notmatch 'jakarta\.annotation-api-1\.3\.5\.jar$') } |
        Select-Object -Unique
    # pom 已显式钉 jakarta.annotation-api 2.1.1（依赖调解已修正）；此处仅兜底：classpath 未含 2.1.1 时才前置
    if ($entries -notcontains $jakarta211) {
        $entries = @($jakarta211) + $entries
        Write-Host "[drill] 兜底前置 jakarta.annotation-api 2.1.1（classpath 中未出现）"
    }
    $final = $entries -join ';'
    Set-Content -Path 'target\drill-cp-final.txt' -Value $final -Encoding ascii
    Write-Host "[drill] classpath 条目数: $($entries.Count)"

    Write-Host "[drill] 编译演练桩..."
    New-Item -ItemType Directory -Force -Path 'target\drill-classes' | Out-Null
    & javac -encoding UTF-8 -cp "target\classes;$final" -d 'target\drill-classes' 'deploy\drill\AccDrill.java'
    if ($LASTEXITCODE -ne 0) { throw "javac 失败（exit=$LASTEXITCODE）" }

    Write-Host "[drill] 完成。启动 ACC 真机："
    Write-Host '  java -cp "target\classes;target\drill-classes;$(Get-Content target\drill-cp-final.txt -Raw)" drill.AccDrill'
}
finally {
    Pop-Location
}

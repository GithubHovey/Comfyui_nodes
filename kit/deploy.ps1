<#
  deploy.ps1 —— 在一台新机器上重建这套 ComfyUI 工作区。

  做四件事：找到 ComfyUI Desktop 实例 → 建共享目录（models / input / output）→
  拉工作流与节点仓库、铺 roco-scene 和 tools → 改写 Desktop 的 settings.json →
  按 kit\models.json 下载模型。

  用法（一般直接双击 kit\一键部署.bat）：
    powershell -ExecutionPolicy Bypass -File kit\deploy.ps1
    powershell -ExecutionPolicy Bypass -File kit\deploy.ps1 -Root D:\Comfy-Desktop
    powershell -ExecutionPolicy Bypass -File kit\deploy.ps1 -Check        只体检，不动任何文件
    powershell -ExecutionPolicy Bypass -File kit\deploy.ps1 -DryRun       打印计划，不落盘
    powershell -ExecutionPolicy Bypass -File kit\deploy.ps1 -SkipModels   只搞配置和代码

  前提：ComfyUI Desktop 已安装并启动过一次；模型从 ModelScope / hf-mirror 下载，需要能上网。
#>
[CmdletBinding()]
param(
    [string]$Root,
    [switch]$DryRun,
    [switch]$Check,
    [switch]$SkipModels,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'

$KitDir     = $PSScriptRoot
$RepoDir    = Split-Path $KitDir -Parent
$ModelsFile = Join-Path $KitDir 'models.json'
$FlowsUrl   = 'https://github.com/GithubHovey/Comfyui_flows.git'
$NodesUrl   = 'https://github.com/GithubHovey/Comfyui_nodes.git'

function Step($Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Ok($Text)   { Write-Host "    ok   $Text" -ForegroundColor Green }
function Note($Text) { Write-Host "    ..   $Text" -ForegroundColor DarkGray }
function Warn($Text) { Write-Host "    !!   $Text" -ForegroundColor Yellow }
function Bad($Text)  { Write-Host "    xx   $Text" -ForegroundColor Red }

function Format-GB([double]$Bytes) {
    return '{0:N1} GB' -f ($Bytes / 1GB)
}

function Get-FreeGB([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $name = ([IO.Path]::GetPathRoot($full)).TrimEnd('\').TrimEnd(':')
    if (-not $name) { return -1 }
    $drive = Get-PSDrive -Name $name -ErrorAction SilentlyContinue
    if (-not $drive) { return -1 }
    return [math]::Round($drive.Free / 1GB, 1)
}

function Test-SamePath([string]$A, [string]$B) {
    if (-not $A -or -not $B) { return $false }
    $pa = [IO.Path]::GetFullPath($A).TrimEnd('\')
    $pb = [IO.Path]::GetFullPath($B).TrimEnd('\')
    return $pa.Equals($pb, [StringComparison]::OrdinalIgnoreCase)
}

function Find-Desktop {
    $file = Join-Path $env:APPDATA 'Comfy Desktop\installations.json'
    if (-not (Test-Path $file)) { return $null }
    try { $list = Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
    $hit = $list | Where-Object { $_.sourceId -eq 'standalone' -and $_.installPath -and $_.status -eq 'installed' } | Select-Object -First 1
    if (-not $hit) {
        $hit = $list | Where-Object { $_.sourceId -eq 'standalone' -and $_.installPath } | Select-Object -First 1
    }
    return $hit
}

function Invoke-Desktop {
    $file = Join-Path $env:APPDATA 'Comfy Desktop\installations.json'
    if (-not (Test-Path $file)) { return $false }
    try { $list = Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $false }
    foreach ($item in $list) {
        if ($item.installPath) {
            $main = Join-Path $item.installPath 'ComfyUI\main.py'
            if (Test-Path $main) { return $main }
        }
    }
    return $false
}

function Get-CurlPath {
    $fixed = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (Test-Path $fixed) { return $fixed }
    return 'curl.exe'
}

function Invoke-CurlDownload([string]$Url, [string]$OutFile) {
    $curl = Get-CurlPath
    & $curl --fail --location --retry 5 --retry-delay 3 --continue-at - --progress-bar --output $OutFile $Url
    return $LASTEXITCODE
}

function Set-SettingsValue($Object, [string]$Name, $Value) {
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Get-WorkflowModelRefs([string]$WorkflowsDir) {
    $refs = @{}
    if (-not (Test-Path $WorkflowsDir)) { return $refs }
    Get-ChildItem $WorkflowsDir -Filter *.json -File | ForEach-Object {
        $name = $_.Name
        $text = Get-Content $_.FullName -Raw -Encoding UTF8
        foreach ($hit in [regex]::Matches($text, '"([^"\\/]+\.(?:safetensors|pth|ckpt))"')) {
            $model = $hit.Groups[1].Value
            if (-not $refs.ContainsKey($model)) {
                $refs[$model] = New-Object System.Collections.ArrayList
            }
            if (-not $refs[$model].Contains($name)) {
                [void]$refs[$model].Add($name)
            }
        }
    }
    return $refs
}

function Show-ModelCheck([string]$ModelsDir, [string]$WorkflowsDir) {
    if (-not (Test-Path $WorkflowsDir)) {
        Warn ("工作流目录还不存在（{0}），先完整跑一次部署" -f $WorkflowsDir)
        return
    }
    $present = @{}
    if (Test-Path $ModelsDir) {
        Get-ChildItem $ModelsDir -Recurse -File | ForEach-Object {
            $present[$_.Name.ToLowerInvariant()] = $true
        }
    }

    $refs = Get-WorkflowModelRefs $WorkflowsDir
    $missing = @()
    foreach ($model in ($refs.Keys | Sort-Object)) {
        if (-not $present.ContainsKey($model.ToLowerInvariant())) {
            $missing += [pscustomobject]@{
                Model = $model
                UsedBy = ($refs[$model] -join '; ')
            }
        }
    }

    Write-Host ''
    Note ("工作流引用了 {0} 个模型，磁盘上共 {1} 个模型文件" -f $refs.Count, $present.Count)
    if ($missing.Count -eq 0) {
        Ok '工作流引用的模型都在，没有缺件'
        return
    }
    Bad ("缺少 {0} 个模型：" -f $missing.Count)
    foreach ($item in $missing) {
        Write-Host ("         {0}`n             <- {1}" -f $item.Model, $item.UsedBy) -ForegroundColor Red
    }
}

# ---------------------------------------------------------------- 开始

Write-Host ''
Write-Host 'ComfyUI 工作区部署' -ForegroundColor White
Write-Host ("节点仓库：{0}" -f $RepoDir) -ForegroundColor DarkGray

Step '检查 PowerShell 和 git'
if ($PSVersionTable.PSVersion.Major -lt 5) {
    Bad '需要 PowerShell 5.1 或更高版本'
    exit 1
}
Ok ("PowerShell {0}" -f $PSVersionTable.PSVersion)
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Bad '找不到 git，请先安装：https://git-scm.com/download/win'
    exit 1
}
Ok ("git {0}" -f ((& git --version) -replace 'git version ', ''))
if (-not (Get-Command (Get-CurlPath) -ErrorAction SilentlyContinue)) {
    Bad '找不到 curl.exe（Windows 10 1803 以上自带），请更新系统或手动装一个'
    exit 1
}

Step '查找 ComfyUI Desktop 实例'
$desktop = Find-Desktop
if (-not $desktop) {
    Bad '没有找到已安装的 ComfyUI Desktop'
    Note '先到 https://www.comfy.org/download 安装，启动一次，再回来双击这个脚本'
    exit 2
}
$InstallPath = $desktop.installPath
Note ("实例：{0}" -f $desktop.name)
Note ("路径：{0}" -f $InstallPath)
if (-not (Test-Path (Join-Path $InstallPath 'ComfyUI\main.py'))) {
    Bad '这个实例目录不完整（缺 ComfyUI\main.py），请在 Desktop 里修一下再跑'
    exit 2
}
Ok '实例可用'

Step '确认目标目录'
if (-not $Root) {
    $Root = Split-Path (Split-Path $InstallPath -Parent) -Parent
    if (-not $Root -or -not (Test-Path $Root)) {
        $Root = Join-Path ([IO.Path]::GetPathRoot($InstallPath)) 'Comfy-Desktop'
    }
    if (-not $Yes -and -not $Check) {
        Write-Host ("    模型和输出放在哪？回车用默认：{0}" -f $Root) -ForegroundColor Gray
        $answer = Read-Host '    目标目录'
        if ($answer) { $Root = $answer.Trim('"') }
    }
}
$Root = [IO.Path]::GetFullPath($Root).TrimEnd('\')

$SharedDir   = Join-Path $Root 'ComfyUI-Shared'
$ModelsDir   = Join-Path $SharedDir 'models'
$InputDir    = Join-Path $SharedDir 'input'
$OutputDir   = Join-Path $SharedDir 'output'
$ToolsDir    = Join-Path $Root 'tools'
$CacheDir    = Join-Path $Root 'ComfyUI-Cache\download-cache'
$InstallDir  = Split-Path $InstallPath -Parent
$WorkflowsDir = Join-Path $InstallPath 'ComfyUI\user\default\workflows'
$NodesDir    = Join-Path $InstallPath 'ComfyUI\custom_nodes'

$manifest = Get-Content $ModelsFile -Raw -Encoding UTF8 | ConvertFrom-Json
$files = @($manifest.files)
$totalBytes = ($files | Measure-Object -Property size -Sum).Sum

Note ("模型目录：{0}" -f $ModelsDir)
Note ("工作流目录：{0}" -f $WorkflowsDir)
Note ("节点目录：{0}" -f $NodesDir)
Note ("模型合计：{0}（{1} 个文件）" -f (Format-GB $totalBytes), $files.Count)

$neededGB = if ($SkipModels) { 10 } else { [math]::Ceiling($totalBytes / 1GB) + 15 }
$free = Get-FreeGB $Root
if ($free -ge 0) {
    Note ("{0} 剩余 {1} GB，需要 {2} GB" -f ([IO.Path]::GetPathRoot($Root)), $free, $neededGB)
    if ($free -lt $neededGB) {
        Bad ("空间不够：模型 {0} GB，加上余量要 {1} GB" -f [math]::Ceiling($totalBytes / 1GB), $neededGB)
        exit 1
    }
}

if ($Check) {
    Step '体检'
    Show-ModelCheck $ModelsDir $WorkflowsDir
    exit 0
}

$running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -match '^(ComfyUI|Comfy Desktop|comfyui-electron)$'
})
if ($running.Count -gt 0 -and -not $DryRun) {
    Bad 'ComfyUI Desktop 正在运行，它会用退出时的设置覆盖 settings.json'
    Note '先完全退出 Desktop，再重跑这个脚本'
    exit 3
}

if ($DryRun) {
    Step '演练模式：下面这些会执行，但不会真的改文件'
    Note ("建目录：{0}" -f $ModelsDir)
    Note ("拉工作流：{0} -> {1}" -f $FlowsUrl, $WorkflowsDir)
    Note ("节点：{0} -> {1}" -f $NodesUrl, (Join-Path $NodesDir 'save-near-input'))
    Note ("复制节点：{0} -> {1}" -f (Join-Path $RepoDir 'roco-scene'), (Join-Path $NodesDir 'roco-scene'))
    Note ("复制脚本：{0} -> {1}" -f (Join-Path $KitDir 'tools'), $ToolsDir)
    Note ("改写设置：{0}" -f (Join-Path $env:APPDATA 'Comfy Desktop\settings.json'))
    if ($SkipModels) {
        Note '跳过模型下载'
    } else {
        Note ("下载 {0} 个模型，共 {1}" -f $files.Count, (Format-GB $totalBytes))
        foreach ($item in $files) {
            $dest = Join-Path $ModelsDir ($item.path -replace '/', '\')
            $state = '待下载'
            if (Test-Path $dest) {
                $sizes = @($item.size)
                if ($item.altSizes) { $sizes += $item.altSizes }
                if ($sizes -contains (Get-Item $dest).Length) { $state = '已有' } else { $state = '大小不符，要重下' }
            }
            Note ("  {0}  {1}  ({2})" -f $state.PadRight(12), $item.path, (Format-GB $item.size))
        }
    }
    Step '演练结束'
    exit 0
}

Step '建目录'
foreach ($dir in @($ModelsDir, $InputDir, $OutputDir, $ToolsDir, $CacheDir)) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}
$modelSubDirs = $files | ForEach-Object { Split-Path (Join-Path $ModelsDir ($_.path -replace '/', '\')) -Parent } | Sort-Object -Unique
foreach ($dir in $modelSubDirs) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}
Ok ("{0} 个子目录就位" -f $modelSubDirs.Count)

Step '同步工作流仓库'
if (Test-Path (Join-Path $WorkflowsDir '.git')) {
    & git -C $WorkflowsDir pull --ff-only
    if ($LASTEXITCODE -ne 0) { Warn '拉取失败，先用本地已有的工作流继续' } else { Ok '已更新' }
} elseif (Test-Path $WorkflowsDir) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = "$WorkflowsDir.local-$stamp"
    Move-Item $WorkflowsDir $backup
    Note ("本地文件已备份到 {0}" -f $backup)
    & git clone $FlowsUrl $WorkflowsDir
    if ($LASTEXITCODE -ne 0) { Bad '克隆工作流仓库失败，检查网络或仓库地址'; exit 4 }
    Ok '已克隆'
} else {
    & git clone $FlowsUrl $WorkflowsDir
    if ($LASTEXITCODE -ne 0) { Bad '克隆工作流仓库失败，检查网络或仓库地址'; exit 4 }
    Ok '已克隆'
}

Step '同步节点仓库'
$saveNodeDir = Join-Path $NodesDir 'save-near-input'
if (Test-SamePath $RepoDir $saveNodeDir) {
    & git -C $RepoDir pull --ff-only
    if ($LASTEXITCODE -ne 0) { Warn '拉取失败，用当前这份继续' } else { Ok '本仓库已是最新' }
} elseif (Test-Path (Join-Path $saveNodeDir '.git')) {
    & git -C $saveNodeDir pull --ff-only
    if ($LASTEXITCODE -ne 0) { Warn '拉取失败，用当前这份继续' } else { Ok '已更新' }
} elseif (Test-Path $saveNodeDir) {
    Warn ("{0} 已存在但不是 git 仓库，跳过克隆" -f $saveNodeDir)
} else {
    & git clone $NodesUrl $saveNodeDir
    if ($LASTEXITCODE -ne 0) { Bad '克隆节点仓库失败，检查网络或仓库地址'; exit 4 }
    Ok '已克隆'
}

Step '铺 roco-scene 和 tools'
$rocoSrc = Join-Path $RepoDir 'roco-scene'
$rocoDst = Join-Path $NodesDir 'roco-scene'
if (Test-Path $rocoSrc) {
    if (Test-Path $rocoDst) {
        $srcHash = (Get-FileHash (Join-Path $rocoSrc '__init__.py') -Algorithm SHA256).Hash
        $dstFile = Join-Path $rocoDst '__init__.py'
        $dstHash = if (Test-Path $dstFile) { (Get-FileHash $dstFile -Algorithm SHA256).Hash } else { '' }
        if ($srcHash -ne $dstHash) {
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            $backup = "$rocoDst.bak-$stamp"
            Move-Item $rocoDst $backup
            Note ("旧版本备份到 {0}" -f $backup)
            Copy-Item $rocoSrc $rocoDst -Recurse
            Ok 'roco-scene 已更新'
        } else {
            Ok 'roco-scene 已是最新'
        }
    } else {
        Copy-Item $rocoSrc $rocoDst -Recurse
        Ok 'roco-scene 已就位'
    }
} else {
    Warn ("{0} 不存在，跳过" -f $rocoSrc)
}

$toolsSrc = Join-Path $KitDir 'tools'
if (Test-Path $toolsSrc) {
    Copy-Item (Join-Path $toolsSrc '*') $ToolsDir -Recurse -Force
    Ok ("脚本已复制到 {0}" -f $ToolsDir)
}

Step '改写 Desktop 设置'
$settingsFile = Join-Path $env:APPDATA 'Comfy Desktop\settings.json'
$settings = $null
if (Test-Path $settingsFile) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Copy-Item $settingsFile "$settingsFile.bak-$stamp"
    try { $settings = Get-Content $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $settings = $null }
}
if (-not $settings) { $settings = [pscustomobject]@{} }
Set-SettingsValue $settings 'installDir' $InstallDir
Set-SettingsValue $settings 'modelsDirs' @($ModelsDir)
Set-SettingsValue $settings 'inputDir' $InputDir
Set-SettingsValue $settings 'outputDir' $OutputDir
Set-SettingsValue $settings 'cacheDir' $CacheDir
Set-SettingsValue $settings 'useChineseMirrors' $true
if ($settings.PSObject.Properties.Name -contains 'lastSaveDialogDir') {
    $settings.lastSaveDialogDir = $OutputDir
}
$json = $settings | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText($settingsFile, $json, (New-Object System.Text.UTF8Encoding($false)))
Ok ("{0}" -f $settingsFile)

if ($SkipModels) {
    Step '跳过模型下载'
} else {
    Step ("下载模型，共 {0}" -f (Format-GB $totalBytes))
    $failed = @()
    $done = 0
    foreach ($item in $files) {
        $dest = Join-Path $ModelsDir ($item.path -replace '/', '\')
        $label = Split-Path $dest -Leaf
        $sizes = @($item.size)
        if ($item.altSizes) { $sizes += $item.altSizes }
        if (Test-Path $dest) {
            if ($sizes -contains (Get-Item $dest).Length) {
                $done++
                Note ("[{0}/{1}] 已有 {2}" -f $done, $files.Count, $label)
                continue
            }
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            Move-Item $dest "$dest.bad-$stamp"
            Warn ("{0} 大小不对，旧文件改成 .bad-$stamp" -f $label)
        }

        $part = "$dest.part"
        $got = $false
        if ((Test-Path $part) -and ((Get-Item $part).Length -eq $item.size)) {
            Move-Item $part $dest -Force
            $got = $true
        }
        foreach ($url in $item.urls) {
            if ($got) { break }
            Write-Host ("    [{0}/{1}] {2}  ({3})" -f ($done + 1), $files.Count, $label, (Format-GB $item.size)) -ForegroundColor White
            Note ("      来源 {0}" -f $url)
            $code = Invoke-CurlDownload $url $part
            if ((Test-Path $part) -and ((Get-Item $part).Length -eq $item.size)) {
                Move-Item $part $dest -Force
                $got = $true
                break
            }
            if ($code -eq 33) {
                Note '       服务器不支持续传，从头下'
                Remove-Item $part -Force -ErrorAction SilentlyContinue
                $code = Invoke-CurlDownload $url $part
                if ((Test-Path $part) -and ((Get-Item $part).Length -eq $item.size)) {
                    Move-Item $part $dest -Force
                    $got = $true
                    break
                }
            }
            $len = if (Test-Path $part) { (Get-Item $part).Length } else { 0 }
            Warn ("       没下完（curl {0}，{1}/{2} 字节），换下一个来源" -f $code, $len, $item.size)
            Remove-Item $part -Force -ErrorAction SilentlyContinue
        }
        if ($got) {
            $done++
            Ok ("完成 {0}" -f $label)
        } else {
            $failed += $item.path
            Bad ("失败 {0}（重跑这个脚本会接着下）" -f $label)
        }
    }
    Write-Host ''
    if ($failed.Count -eq 0) {
        Ok ("{0} 个模型全部就绪" -f $files.Count)
    } else {
        Bad ("{0} 个没下完：" -f $failed.Count)
        foreach ($path in $failed) { Write-Host ("         {0}" -f $path) -ForegroundColor Red }
    }
}

Step '体检'
Show-ModelCheck $ModelsDir $WorkflowsDir

Step '收尾'
Note '打开 ComfyUI Desktop，模型下拉框里应该能看到这些文件'
Note '工作流在 Desktop 的「工作流」面板里，来自 GithubHovey/Comfyui_flows'
Note ("图片工具：{0}" -f $ToolsDir)
Write-Host ''

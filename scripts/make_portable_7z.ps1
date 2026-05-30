[CmdletBinding()]
param(
    [string]$OutputRoot = "",
    [string]$ArchiveName = "",
    [string]$BandizipPath = "",
    [string]$VolumeSize = "2000MB",
    [ValidateRange(0, 9)]
    [int]$CompressionLevel = 5,
    [switch]$ExcludeAsr,
    [switch]$ExcludeDocs,
    [switch]$IncludeLocalVoices,
    [switch]$AllowMissingModels,
    [switch]$SkipExtract,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp.com 65001 > $null

$GitHubReleaseAssetLimitBytes = 2GB

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RepoName = Split-Path $RepoRoot -Leaf

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $RepoRoot ".codex-temp\compress"
}
if ([string]::IsNullOrWhiteSpace($ArchiveName)) {
    $ArchiveName = "$RepoName-portable"
}

$OutputRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputRoot)
$ArchiveRoot = Join-Path $OutputRoot "archive"
$ExtractRoot = Join-Path $OutputRoot "extracted"
$StagingRoot = Join-Path $OutputRoot ".staging"
$PortableRoot = Join-Path $StagingRoot $RepoName
$ArchivePath = Join-Path $ArchiveRoot "$ArchiveName.7z"

function Resolve-Bandizip {
    param([string]$ExplicitPath)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $Resolved = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ExplicitPath)
        if (Test-Path $Resolved) {
            return $Resolved
        }
        throw "找不到指定的 Bandizip 命令行工具: $ExplicitPath"
    }

    $Command = Get-Command "bz.exe" -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }

    $Candidates = @(
        "D:\Programs\Bandizip\Bandizip\bz.exe",
        (Join-Path $env:ProgramFiles "Bandizip\bz.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Bandizip\bz.exe")
    )
    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path $Candidate)) {
            return $Candidate
        }
    }

    throw "找不到 Bandizip bz.exe。请安装 Bandizip，或用 -BandizipPath 指向 bz.exe。"
}

function Resolve-RepoPath {
    param([string]$RelativePath)
    return Join-Path $RepoRoot $RelativePath
}

function Assert-RepoPath {
    param(
        [string]$RelativePath,
        [switch]$Optional
    )

    $Absolute = Resolve-RepoPath $RelativePath
    if (Test-Path $Absolute) {
        return $true
    }
    if ($Optional) {
        return $false
    }
    throw "缺少打包项: $RelativePath"
}

function Assert-UnderPath {
    param(
        [string]$Path,
        [string]$Parent
    )

    $FullPath = [System.IO.Path]::GetFullPath($Path)
    $FullParent = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $FullPath.StartsWith($FullParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作输出目录之外的路径: $FullPath"
    }
}

function Reset-Directory {
    param([string]$Path)

    Assert-UnderPath -Path $Path -Parent $OutputRoot
    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Copy-Directory {
    param(
        [string]$RelativePath,
        [string[]]$ExcludeDirs = @(),
        [string[]]$ExcludeFiles = @()
    )

    $Source = Resolve-RepoPath $RelativePath
    $Destination = Join-Path $PortableRoot $RelativePath
    New-Item -ItemType Directory -Path (Split-Path $Destination -Parent) -Force | Out-Null

    $Args = @(
        $Source,
        $Destination,
        "/E",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NC",
        "/NS",
        "/NP"
    )

    $AllExcludeDirs = @(".git", "__pycache__", ".pytest_cache") + $ExcludeDirs
    if ($AllExcludeDirs.Count -gt 0) {
        $Args += "/XD"
        $Args += $AllExcludeDirs
    }

    $AllExcludeFiles = @("*.pyc", "*.pyo") + $ExcludeFiles
    if ($AllExcludeFiles.Count -gt 0) {
        $Args += "/XF"
        $Args += $AllExcludeFiles
    }

    & robocopy @Args | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "复制目录失败: $RelativePath，robocopy 退出码: $LASTEXITCODE"
    }
}

function Copy-FileIfExists {
    param([string]$RelativePath)

    $Source = Resolve-RepoPath $RelativePath
    if (-not (Test-Path $Source)) {
        return
    }
    $Destination = Join-Path $PortableRoot $RelativePath
    New-Item -ItemType Directory -Path (Split-Path $Destination -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function New-PortableDirectory {
    param([string]$RelativePath)

    New-Item -ItemType Directory -Path (Join-Path $PortableRoot $RelativePath) -Force | Out-Null
}

function Repair-StagedEditableInstalls {
    $SitePackages = Join-Path $PortableRoot ".pixi\envs\default\Lib\site-packages"
    if (-not (Test-Path $SitePackages)) {
        return
    }

    foreach ($PthFile in Get-ChildItem -Path $SitePackages -Filter "__editable__.voxcpm*.pth" -File) {
        Set-Content -LiteralPath $PthFile.FullName -Value "..\..\..\..\..\VoxCPM\src" -Encoding ASCII
    }
}

function Get-FirstArchivePart {
    $VolumeFirst = "$ArchivePath.001"
    if (Test-Path $VolumeFirst) {
        return $VolumeFirst
    }
    if (Test-Path $ArchivePath) {
        return $ArchivePath
    }
    throw "未找到生成的压缩包: $ArchivePath"
}

function Get-ArchiveParts {
    $Parts = @(Get-ChildItem -Path $ArchiveRoot -File -Filter "$ArchiveName.7z*" | Sort-Object Name)
    if (-not $Parts) {
        throw "未找到生成的压缩包分卷: $ArchiveRoot"
    }
    return $Parts
}

function Assert-GitHubReleaseAssetSizes {
    foreach ($Part in Get-ArchiveParts) {
        if ($Part.Length -ge $GitHubReleaseAssetLimitBytes) {
            throw "GitHub Release 单个资产必须小于 2 GiB，但 $($Part.Name) 是 $($Part.Length) bytes。请调小 -VolumeSize。"
        }
    }
}

function Write-ReleaseMetadata {
    $Parts = Get-ArchiveParts
    $ChecksumsPath = Join-Path $ArchiveRoot "SHA256SUMS.txt"
    $ManifestPath = Join-Path $ArchiveRoot "RELEASE_ASSETS.md"

    $ChecksumLines = foreach ($Part in $Parts) {
        $Hash = Get-FileHash -LiteralPath $Part.FullName -Algorithm SHA256
        "$($Hash.Hash.ToLowerInvariant())  $($Part.Name)"
    }
    Set-Content -LiteralPath $ChecksumsPath -Value $ChecksumLines -Encoding ASCII

    $Manifest = @(
        "# Release Assets",
        "",
        "Upload every file in this directory to the GitHub Release.",
        "",
        "- Archive format: split 7z",
        "- Volume size: $VolumeSize",
        "- GitHub Release limit: each asset must be smaller than 2 GiB",
        "- First volume to open/extract: $($Parts[0].Name)",
        "- Checksum file: SHA256SUMS.txt",
        "",
        "## Files",
        ""
    )
    foreach ($Part in $Parts) {
        $Manifest += ('- `{0}` ({1} bytes)' -f $Part.Name, $Part.Length)
    }
    $Manifest += '- `SHA256SUMS.txt`'
    Set-Content -LiteralPath $ManifestPath -Value $Manifest -Encoding ASCII
}

$Bandizip = Resolve-Bandizip -ExplicitPath $BandizipPath

Assert-RepoPath ".pixi\envs\default\python.exe" | Out-Null
Assert-RepoPath "app" | Out-Null
Assert-RepoPath "configs" | Out-Null
Assert-RepoPath "scripts" | Out-Null
Assert-RepoPath "VoxCPM\src\voxcpm\__init__.py" | Out-Null
Assert-RepoPath "start_portable.bat" | Out-Null

$MainModelExists = Assert-RepoPath "models\OpenBMB__VoxCPM2\model.safetensors" -Optional
if (-not $MainModelExists -and -not $AllowMissingModels) {
    throw "缺少主模型 models\OpenBMB__VoxCPM2\model.safetensors。若要打环境空包，请加 -AllowMissingModels。"
}

$AsrModelExists = Assert-RepoPath "models\iic__SenseVoiceSmall\model.pt" -Optional
$IncludeAsr = $AsrModelExists -and -not $ExcludeAsr

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
if (((Test-Path $ArchiveRoot) -or (Test-Path $ExtractRoot) -or (Test-Path $StagingRoot)) -and -not $Force) {
    throw "输出目录已存在内容: $OutputRoot。请加 -Force 覆盖 archive/extracted/.staging。"
}

Reset-Directory $ArchiveRoot
Reset-Directory $StagingRoot
if (-not $SkipExtract) {
    Reset-Directory $ExtractRoot
}

Write-Host "准备 portable 文件目录..."
Copy-Directory ".pixi\envs\default"
Copy-Directory "app"
Copy-Directory "configs"
Copy-Directory "scripts"
Copy-Directory "VoxCPM"

if (-not $ExcludeDocs -and (Assert-RepoPath "docs" -Optional)) {
    Copy-Directory "docs"
}

if ($MainModelExists) {
    Copy-Directory "models\OpenBMB__VoxCPM2"
}
if ($IncludeAsr) {
    Copy-Directory "models\iic__SenseVoiceSmall"
}

New-PortableDirectory "models"
Copy-FileIfExists "models\.gitkeep"

foreach ($RuntimeDir in @("runtime\cache", "runtime\logs", "runtime\outputs", "runtime\temp")) {
    New-PortableDirectory $RuntimeDir
}
Copy-FileIfExists "runtime\cache\.gitkeep"
Copy-FileIfExists "runtime\logs\.gitkeep"
Copy-FileIfExists "runtime\outputs\.gitkeep"

if ($IncludeLocalVoices) {
    if (Assert-RepoPath "runtime\voices" -Optional) {
        Copy-Directory "runtime\voices"
    }
} else {
    New-PortableDirectory "runtime\voices"
    Copy-FileIfExists "runtime\voices\.gitkeep"
    foreach ($VoiceDir in @(
        "runtime\voices\voxcpm2-design",
        "runtime\voices\voxcpm2-clone",
        "runtime\voices\voxcpm2-ultimate-clone"
    )) {
        if (Assert-RepoPath $VoiceDir -Optional) {
            Copy-Directory $VoiceDir
        }
    }
}

foreach ($File in @(
    "README.md",
    "README_zh.md",
    "License",
    "pixi.toml",
    "pixi.lock",
    "start_portable.bat"
)) {
    Copy-FileIfExists $File
}

Repair-StagedEditableInstalls

Write-Host "使用 Bandizip: $Bandizip"
Write-Host "输出目录: $OutputRoot"
Write-Host "压缩格式: 7z"
Write-Host "分卷大小: $VolumeSize"
Write-Host "包含主模型: $MainModelExists"
Write-Host "包含 ASR 模型: $IncludeAsr"
Write-Host "包含本地自定义 voices: $IncludeLocalVoices"
Write-Host ""

Push-Location $StagingRoot
try {
    $Arguments = @(
        "c",
        "-fmt:7z",
        "-v:$VolumeSize",
        "-l:$CompressionLevel",
        "-y",
        $ArchivePath,
        $RepoName
    )
    & $Bandizip @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Bandizip 压缩失败，退出码: $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

$FirstArchivePart = Get-FirstArchivePart
Write-Host ""
Write-Host "测试压缩包完整性..."
& $Bandizip t $FirstArchivePart
if ($LASTEXITCODE -ne 0) {
    throw "Bandizip 完整性测试失败，退出码: $LASTEXITCODE"
}

Assert-GitHubReleaseAssetSizes
Write-ReleaseMetadata

if (-not $SkipExtract) {
    Write-Host ""
    Write-Host "解压压缩包到: $ExtractRoot"
    & $Bandizip x -y "-o:$ExtractRoot" $FirstArchivePart
    if ($LASTEXITCODE -ne 0) {
        throw "Bandizip 解压失败，退出码: $LASTEXITCODE"
    }
}

Remove-Item -LiteralPath $StagingRoot -Recurse -Force

Write-Host ""
Write-Host "打包完成。"
Write-Host "压缩包目录: $ArchiveRoot"
if (-not $SkipExtract) {
    Write-Host "解压目录: $ExtractRoot"
}

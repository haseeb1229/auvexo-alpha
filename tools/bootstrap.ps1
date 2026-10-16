param([switch]$SkipPostgres)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$toolRoot = Join-Path $repoRoot '.local/toolchains'
New-Item -ItemType Directory -Force -Path $toolRoot, (Join-Path $repoRoot '.local/python'), (Join-Path $repoRoot '.local/uv-cache') | Out-Null
function Get-VerifiedArchive {
    param([string]$Url, [string]$Path, [string]$Sha256)
    if (-not (Test-Path -LiteralPath $Path)) {
        & curl.exe --fail --location --retry 2 --connect-timeout 20 --max-time 600 --output $Path $Url
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha256) {
        throw "Hash mismatch: $Path. Do not execute this archive."
    }
}
$uvArchive = Join-Path $toolRoot 'uv-wheel.zip'
Get-VerifiedArchive 'https://files.pythonhosted.org/packages/2a/8e/d23278bb327d2a75dc1d033c81b7fe23bbb28e363e02e7f306abd047924a/uv-0.13.1-py3-none-win_amd64.whl' $uvArchive '4f693cd4feb52f08f30474c4612f24be2050472609be65b9960b635f286da284'
$uvRoot = Join-Path $toolRoot 'uv-wheel'
$uvPath = Join-Path $uvRoot 'uv-0.13.1.data/scripts/uv.exe'
if (-not (Test-Path -LiteralPath $uvPath)) { Expand-Archive -LiteralPath $uvArchive -DestinationPath $uvRoot }
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repoRoot '.local/python'
$env:UV_CACHE_DIR = Join-Path $repoRoot '.local/uv-cache'
& $uvPath python install 3.13.16 --no-bin
if ($LASTEXITCODE -ne 0) { throw 'Python install failed' }
& $uvPath sync --locked
if ($LASTEXITCODE -ne 0) { throw 'Locked install failed' }
if (-not $SkipPostgres) {
    $pgArchive = Join-Path $toolRoot 'postgresql.zip'
    Get-VerifiedArchive 'https://get.enterprisedb.com/postgresql/postgresql-17.11-1-windows-x64-binaries.zip' $pgArchive '6eabdf00d2893713b75db4336a23c3fdf505f056e217ec6e2e95d901750cfea3'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $pgRoot = [IO.Path]::GetFullPath((Join-Path $toolRoot 'postgres'))
    $archive = [IO.Compression.ZipFile]::OpenRead($pgArchive)
    try {
        foreach ($entry in $archive.Entries) {
            # Server/client tools only; no pgAdmin, StackBuilder or global installer.
            if ($entry.FullName -notmatch '^pgsql/(bin/|lib/|share/|[^/]*[Ll]icense[^/]*)') { continue }
            $target = [IO.Path]::GetFullPath((Join-Path $pgRoot $entry.FullName))
            if (-not $target.StartsWith($pgRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe archive path' }
            if ($entry.FullName.EndsWith('/')) { New-Item -ItemType Directory -Force -Path $target | Out-Null; continue }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            if (-not (Test-Path -LiteralPath $target)) { [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target) }
        }
    } finally { $archive.Dispose() }
}
Write-Output 'Toolchain ready. Run tools/dev.ps1 start-db, migrate, then check.'

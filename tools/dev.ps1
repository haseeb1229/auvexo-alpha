param([ValidateSet('sync','check','start-db','stop-db','migrate','doctor','serve','recover','measure')][string]$Action = 'check')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repoRoot '.local/python'
$env:UV_CACHE_DIR = Join-Path $repoRoot '.local/uv-cache'
$env:UV_LINK_MODE = 'copy'
$uvPath = Join-Path $repoRoot '.local/toolchains/uv-wheel/uv-0.13.1.data/scripts/uv.exe'
if (-not (Test-Path -LiteralPath $uvPath)) { throw 'Install the verified uv toolchain per docs/phase1/SETUP.md.' }
function Invoke-Checked { param([string[]]$Arguments) & $uvPath @Arguments; if ($LASTEXITCODE -ne 0) { throw "Command failed: uv $($Arguments -join ' ')" } }
switch ($Action) {
    'sync' { Invoke-Checked @('sync','--locked','--group','provider') }
    'check' {
        Invoke-Checked @('run','--frozen','ruff','format','--check','src','tests','tools','migrations')
        Invoke-Checked @('run','--frozen','ruff','check','src','tests','tools','migrations')
        Invoke-Checked @('run','--frozen','mypy')
        # PostgreSQL tests run only against a disposable cluster, never port 55432.
        Invoke-Checked @('run','--frozen','python','tools/disposable_pg.py','test','-q')
        node tools/check-docs.mjs
        if ($LASTEXITCODE -ne 0) { throw 'Documentation check failed' }
    }
    'start-db' { Invoke-Checked @('run','--frozen','python','tools/local_db.py','start') }
    'stop-db' { Invoke-Checked @('run','--frozen','python','tools/local_db.py','stop') }
    'migrate' { Invoke-Checked @('run','--frozen','python','tools/local_db.py','migrate') }
    'recover' { Invoke-Checked @('run','--frozen','python','tools/verify_recovery.py') }
    'measure' { Invoke-Checked @('run','--frozen','python','tools/measure_foundation.py') }
    'doctor' { Invoke-Checked @('run','--frozen','python','tools/local_db.py','doctor') }
    'serve' { Invoke-Checked @('run','--frozen','python','tools/local_db.py','serve') }
}

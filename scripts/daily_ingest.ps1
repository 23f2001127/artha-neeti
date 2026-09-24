<#
    Resumes annual-report ingestion; meant to run once a day.

    Gemini's free tier allows about 1,000 embeddings a day, roughly one or two
    reports. ingest.py skips finished reports and redoes partial ones, so a
    daily run works through the corpus unattended. Output is appended to
    logs/ingest_<date>.log. Scheduling is described in
    mcp_servers/filings_rag_mcp/README.md.

        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\daily_ingest.ps1
#>

$ErrorActionPreference = 'Stop'

# repo root = parent of this script's folder
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python   = Join-Path $RepoRoot 'venv\Scripts\python.exe'
$LogDir   = Join-Path $RepoRoot 'logs'
$LogFile  = Join-Path $LogDir ("ingest_{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
if (-not (Test-Path $Python)) { throw "venv Python not found at $Python" }

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'
Add-Content -Path $LogFile -Encoding utf8 -Value ""
Add-Content -Path $LogFile -Encoding utf8 -Value "===== daily_ingest run: $stamp ====="

Set-Location $RepoRoot

# cmd.exe does the redirect so native stdout+stderr land in the file cleanly
# (PowerShell 5.1 wraps native stderr in ErrorRecords under `2>&1`).
& cmd.exe /c "`"$Python`" -m mcp_servers.filings_rag_mcp.ingest >> `"$LogFile`" 2>&1"
$code = $LASTEXITCODE

# ingest.py exit codes: 0 = corpus complete, 2 = stopped on daily quota wall
# (normal, expected most days), 130 = interrupted, other = real error.
$note = switch ($code) {
    0       { "ingestion reports the full corpus is complete - this task can now be disabled" }
    2       { "stopped on the Gemini daily embedding quota (expected) - will resume tomorrow" }
    130     { "interrupted" }
    default { "exited $code - check the log for a real error" }
}
Add-Content -Path $LogFile -Encoding utf8 -Value ("===== done: exit $code - $note =====")
exit $code

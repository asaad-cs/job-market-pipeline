# dbt_run.ps1 — load .env into shell, then run dbt with all arguments passed through.
#
# Usage (from the dbt/ directory):
#   .\dbt_run.ps1 debug
#   .\dbt_run.ps1 run
#   .\dbt_run.ps1 run --select stg_careerjet__raw_jobs
#   .\dbt_run.ps1 test
#
# profiles.yml lives in dbt/  (gitignored).
# dbt_project.yml lives in dbt/job_market_pipeline/  (the project root).
# This script passes --profiles-dir pointing to dbt/ and --project-dir
# pointing to dbt/job_market_pipeline/ so both are found correctly.

$scriptDir  = $PSScriptRoot                               # dbt/
$projectDir = Join-Path $scriptDir "job_market_pipeline"  # dbt/job_market_pipeline/
$envFile    = Join-Path $scriptDir "../.env"              # repo root .env

if (-not (Test-Path $envFile)) {
    Write-Error ".env not found at $envFile — copy .env.example to .env and fill in values."
    exit 1
}

if (-not (Test-Path (Join-Path $scriptDir "profiles.yml"))) {
    Write-Error "profiles.yml not found in $scriptDir — copy profiles.yml.example to profiles.yml."
    exit 1
}

# Load .env variables into the current process environment
Get-Content $envFile |
    Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' } |
    ForEach-Object {
        $parts = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
    }

$dbt = "C:\Users\Hammo\AppData\Local\Python\pythoncore-3.14-64\Scripts\dbt.exe"
& $dbt @args --profiles-dir $scriptDir --project-dir $projectDir

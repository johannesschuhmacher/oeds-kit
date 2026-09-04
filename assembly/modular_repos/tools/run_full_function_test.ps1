param(
    [int]$DockerTimeoutSeconds = 900
)

$ErrorActionPreference = "Stop"

$scriptRoot = Resolve-Path $PSScriptRoot
$modularRoot = Resolve-Path (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $modularRoot "..")
$python = Join-Path $repoRoot ".venv/Scripts/python.exe"
$crawlerSrc = Join-Path $modularRoot "modules/oeds-crawler-pack/src"
$schedulerSrc = Join-Path $modularRoot "modules/oeds-scheduler-ui/src"
$postSrc = Join-Path $modularRoot "modules/oeds-post-scripts/src"
$postRoot = Join-Path $modularRoot "modules/oeds-post-scripts"
$modulePythonPath = "$crawlerSrc;$schedulerSrc;$postSrc;$postRoot"
$outputRoot = Join-Path $modularRoot ".tmp/full-function-test"
$results = New-Object System.Collections.Generic.List[object]

function Assert-LastExitCode {
    param(
        [string]$Message
    )
    if ($LASTEXITCODE -ne 0) {
        throw "$Message failed with exit code $LASTEXITCODE"
    }
}

function Invoke-WithPythonPath {
    param(
        [string]$PythonPath,
        [scriptblock]$Action
    )
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $PythonPath
        & $Action
    }
    finally {
        $env:PYTHONPATH = $previousPythonPath
    }
}

function Invoke-TestStep {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Output ""
    Write-Output "=== $Name ==="
    $startedAt = Get-Date
    $status = "passed"
    $errorText = ""
    try {
        & $Action
    }
    catch {
        $status = "failed"
        $errorText = $_.Exception.Message
        Write-Output "FAILED: $errorText"
    }
    $finishedAt = Get-Date
    $results.Add([pscustomobject]@{
        Step = $Name
        Status = $status
        Seconds = [math]::Round(($finishedAt - $startedAt).TotalSeconds, 1)
        Error = $errorText
    }) | Out-Null
}

function Invoke-InDirectory {
    param(
        [string]$Path,
        [scriptblock]$Action
    )
    Push-Location $Path
    try {
        & $Action
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-Path $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

Invoke-TestStep "Python version" {
    & $python --version
    Assert-LastExitCode "python --version"
}

Invoke-TestStep "Module scaffold verifier" {
    & $python (Join-Path $modularRoot "tools/verify_modules.py")
    Assert-LastExitCode "verify_modules.py"
}

Invoke-TestStep "Crawler registry audit" {
    $auditPath = Join-Path $outputRoot "crawler-registry-audit.json"
    & $python (Join-Path $modularRoot "tools/audit_registry.py") | Out-File -FilePath $auditPath -Encoding utf8
    Assert-LastExitCode "audit_registry.py"
    Write-Output "wrote $auditPath"
}

Invoke-TestStep "Deployment verifier" {
    & $python (Join-Path $modularRoot "modules/oeds-deployment/tools/verify_deployment.py")
    Assert-LastExitCode "verify_deployment.py"
}

Invoke-TestStep "Python compileall" {
    & $python -m compileall `
        (Join-Path $modularRoot "modules/oeds-post-scripts") `
        (Join-Path $modularRoot "modules/oeds-scheduler-ui/src") `
        (Join-Path $modularRoot "modules/oeds-crawler-pack/src") `
        (Join-Path $modularRoot "tools") `
        -q
    Assert-LastExitCode "compileall"
}

Invoke-TestStep "Crawler-pack tests" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-crawler-pack") {
        Invoke-WithPythonPath $modulePythonPath {
            & $python -m pytest tests
            Assert-LastExitCode "crawler-pack pytest"
        }
    }
}

Invoke-TestStep "Post-scripts tests" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-post-scripts") {
        Invoke-WithPythonPath $modulePythonPath {
            & $python -m pytest tests
            Assert-LastExitCode "post-scripts pytest"
        }
    }
}

Invoke-TestStep "Scheduler/UI tests" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-scheduler-ui") {
        Invoke-WithPythonPath $modulePythonPath {
            & $python -m pytest tests
            Assert-LastExitCode "scheduler-ui pytest"
        }
    }
}

Invoke-TestStep "Post CLI command registry" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-post-scripts") {
        Invoke-WithPythonPath $modulePythonPath {
            & $python -m oeds_post_scripts.cli --list --json
            Assert-LastExitCode "oeds-post --list"
        }
    }
}

Invoke-TestStep "Post CLI gapfill listing" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-post-scripts") {
        Invoke-WithPythonPath $modulePythonPath {
            & $python -m oeds_post_scripts.cli gapfill entsoe-fms --list-tables
            Assert-LastExitCode "oeds-post gapfill entsoe-fms --list-tables"
        }
    }
}

Invoke-TestStep "Post CLI price forecast self-test" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-post-scripts") {
        Invoke-WithPythonPath $modulePythonPath {
            & $python -m oeds_post_scripts.cli forecast day-ahead-price --self-test --model-backend ridge --train-days 30 --backtest-days 1
            Assert-LastExitCode "oeds-post forecast day-ahead-price --self-test"
        }
    }
}

Invoke-TestStep "Post CLI backfill help" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-post-scripts") {
        Invoke-WithPythonPath $modulePythonPath {
            & $python -m oeds_post_scripts.cli backfill entsoe-unavailability --help
            Assert-LastExitCode "oeds-post backfill entsoe-unavailability --help"
        }
    }
}

Invoke-TestStep "Post CLI legacy command print" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-post-scripts") {
        Invoke-WithPythonPath $modulePythonPath {
            & $python -m oeds_post_scripts.cli --print-command gapfill smard
            Assert-LastExitCode "oeds-post --print-command gapfill smard"
        }
    }
}

Invoke-TestStep "Scheduler CLI planning" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-scheduler-ui") {
        Invoke-WithPythonPath $modulePythonPath {
            & $python -m oeds_scheduler_ui.cli `
                --config (Join-Path $repoRoot "CRAWLER_CONFIG.yml") `
                --inventory (Join-Path $modularRoot "docs/crawler-inventory.json") `
                --workspace-root $modularRoot `
                --once
            Assert-LastExitCode "oeds-scheduler --once"
        }
    }
}

Invoke-TestStep "Admin app import" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-scheduler-ui") {
        Invoke-WithPythonPath $modulePythonPath {
            & $python -c "from crawler_admin.app import app; print(app.title, app.version)"
            Assert-LastExitCode "crawler_admin import"
        }
    }
}

Invoke-TestStep "Modular Compose model" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-deployment") {
        docker compose --profile crawlers -f compose.yml -f compose.modular.yml config | Out-Null
        Assert-LastExitCode "modular compose config"
    }
}

Invoke-TestStep "Isolated Compose model" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-deployment") {
        docker compose -f compose.yml -f compose.modular.yml -f compose.test.yml config | Out-Null
        Assert-LastExitCode "test compose config"
    }
}

Invoke-TestStep "Isolated DB smoke" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-deployment") {
        & ".\tools\test_db_smoke.ps1" -TimeoutSeconds $DockerTimeoutSeconds
        Assert-LastExitCode "test_db_smoke.ps1"
    }
}

Invoke-TestStep "Real SMARD crawler and post-run smoke" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-deployment") {
        & ".\tools\test_real_crawler_smoke.ps1" -TimeoutSeconds $DockerTimeoutSeconds -RunPostScripts
        Assert-LastExitCode "test_real_crawler_smoke.ps1"
    }
}

Invoke-TestStep "Active enabled crawlers smoke" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-deployment") {
        & ".\tools\test_active_crawlers_smoke.ps1" -TimeoutSeconds $DockerTimeoutSeconds -IncludeEntsoeFms
        Assert-LastExitCode "test_active_crawlers_smoke.ps1"
    }
}

Invoke-TestStep "Modular stack smoke" {
    Invoke-InDirectory (Join-Path $modularRoot "modules/oeds-deployment") {
        & ".\tools\test_stack_smoke.ps1" -TimeoutSeconds $DockerTimeoutSeconds
        Assert-LastExitCode "test_stack_smoke.ps1"
    }
}

Invoke-TestStep "No isolated Docker leftovers" {
    $containers = docker ps -a --filter "name=oeds-modular-test" --format "{{.Names}}"
    $volumes = docker volume ls --filter "name=oeds-modular-test" --format "{{.Name}}"
    $networks = docker network ls --filter "name=oeds-modular-test" --format "{{.Name}}"
    if ($containers -or $volumes -or $networks) {
        throw "leftover Docker resources: containers=[$containers] volumes=[$volumes] networks=[$networks]"
    }
    Write-Output "no oeds-modular-test Docker resources remain"
}

Invoke-TestStep "Clean local test caches" {
    $root = (Resolve-Path $modularRoot).Path
    Get-ChildItem -Path $root -Recurse -Force -Directory |
        Where-Object { $_.Name -in @("__pycache__", ".pytest_cache") } |
        ForEach-Object {
            if ($_.FullName.StartsWith($root)) {
                Remove-Item -LiteralPath $_.FullName -Recurse -Force
            }
            else {
                throw "refusing to remove outside modular_repos: $($_.FullName)"
            }
        }
    Write-Output "local test caches cleaned"
}

Write-Output ""
Write-Output "=== Full Function Test Summary ==="
$results | Format-Table -AutoSize

$failed = @($results | Where-Object { $_.Status -ne "passed" })
if ($failed.Count -gt 0) {
    exit 1
}

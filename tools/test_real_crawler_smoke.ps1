param(
    [int]$TimeoutSeconds = 900,
    [string]$StartDate = "2024-06-02 22:00:00",
    [switch]$RunPostScripts
)

$ErrorActionPreference = "Stop"

$deploymentRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$composeArgs = @(
    "-f", "compose.yml",
    "-f", "compose.modular.yml",
    "-f", "compose.test.yml"
)
$container = "oeds-modular-test-open-data"
$runtimeDir = ".tmp/runtime-real-crawler"
$runtimeRoot = Join-Path $deploymentRoot $runtimeDir
$configPath = Join-Path $runtimeRoot "CRAWLER_CONFIG.yml"
$started = $false
$previousComposeProjectName = $env:COMPOSE_PROJECT_NAME
$previousRuntimeDir = $env:OEDS_RUNTIME_DIR
$previousSmokeCode = $env:OEDS_CRAWLER_SMOKE_CODE

function Assert-LastExitCode {
    param(
        [string]$Message
    )
    if ($LASTEXITCODE -ne 0) {
        throw "$Message failed with exit code $LASTEXITCODE"
    }
}

function Wait-ForOpenData {
    param(
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $state = docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $container 2>$null
        if ($state -eq "healthy") {
            return
        }
        Start-Sleep -Seconds 5
    }

    docker compose @composeArgs logs --no-color open-data | Select-Object -Last 120
    throw "open-data did not become healthy within $TimeoutSeconds seconds"
}

function Write-SmardSmokeConfig {
    param(
        [string]$Path,
        [string]$StartDate,
        [bool]$RunPostScripts
    )

    $runPostScriptsValue = if ($RunPostScripts) { "true" } else { "false" }
    $postRunScripts = if ($RunPostScripts) {
        @"
  post_run_scripts:
    - "scripts/gapfill_smard.py"
"@
    } else {
        "  post_run_scripts: []"
    }

    $config = @"
default:
  email:
    mailhost: ""
    fromaddr: ""
    toaddrs: []
    subject: "OEDS Crawler :crawler_name Critical Error Notification"
    username: ""
    password: ""
  enable: false
  schedule: "* * * * *"
  post_run_scripts: []
  database_uri: "postgresql://opendata:opendata@open-data:5432/opendata?options=--search_path="
smard:
  enable: true
  schema_name: "smard"
  schedule: "* * * * *"
  default_start_date: "$StartDate"
  run_post_scripts: $runPostScriptsValue
$postRunScripts
"@

    $config | Set-Content -Path $Path -Encoding utf8
}

$pythonCode = @'
import json
from pathlib import Path

from oeds_scheduler_ui.application import SchedulerApplication
from oeds_scheduler_ui.runtime import CrawlerJobRunner

app = SchedulerApplication(
    config_path=Path("/app/CRAWLER_CONFIG.yml"),
    inventory_path=Path("/app/modular_repos/docs/crawler-inventory.json"),
    workspace_root=Path("/app/modular_repos"),
)

plans = [plan for plan in app.plan_result.plans if plan.crawler_name == "smard"]
if len(plans) != 1:
    raise SystemExit(f"expected exactly one smard plan, got {len(plans)}")

result = CrawlerJobRunner(app.factory).run(plans[0])
payload = {
    "job_id": result.job_id,
    "crawler_success": result.crawler_success,
    "post_run_success": result.post_run_success,
    "success": result.success,
    "error": result.error,
    "post_run_results": [
        {
            "command": item.command,
            "returncode": item.returncode,
            "success": item.success,
            "error": item.error,
        }
        for item in result.post_run_results
    ],
}
print(json.dumps(payload, sort_keys=True))
raise SystemExit(0 if result.success else 1)
'@

Push-Location $deploymentRoot
try {
    $env:COMPOSE_PROJECT_NAME = "oeds-modular-test"

    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot "crawler/data") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot "logs") | Out-Null
    Write-SmardSmokeConfig -Path $configPath -StartDate $StartDate -RunPostScripts ([bool]$RunPostScripts)

    $env:OEDS_RUNTIME_DIR = $runtimeDir
    $env:OEDS_CRAWLER_SMOKE_CODE = $pythonCode

    docker compose @composeArgs build scheduler
    Assert-LastExitCode "docker compose build scheduler"

    docker compose @composeArgs up -d open-data
    Assert-LastExitCode "docker compose up open-data"
    $started = $true
    Wait-ForOpenData -TimeoutSeconds $TimeoutSeconds

    docker compose @composeArgs run --rm --no-deps -e OEDS_CRAWLER_SMOKE_CODE scheduler python -c "import os; exec(os.environ['OEDS_CRAWLER_SMOKE_CODE'])"
    Assert-LastExitCode "real crawler smoke"

    $sql = @"
DO `$`$
DECLARE
  smard_rows integer;
  price_rows integer;
  metadata_rows integer;
BEGIN
  IF to_regclass('smard.smard') IS NULL THEN
    RAISE EXCEPTION 'missing smard.smard table';
  END IF;
  IF to_regclass('smard.prices') IS NULL THEN
    RAISE EXCEPTION 'missing smard.prices table';
  END IF;

  SELECT COUNT(*) INTO smard_rows FROM smard.smard;
  SELECT COUNT(*) INTO price_rows FROM smard.prices;
  SELECT COUNT(*) INTO metadata_rows FROM public.metadata WHERE schema_name = 'smard';

  IF smard_rows <= 0 THEN
    RAISE EXCEPTION 'smard.smard has no rows';
  END IF;
  IF price_rows <= 0 THEN
    RAISE EXCEPTION 'smard.prices has no rows';
  END IF;
  IF metadata_rows <> 1 THEN
    RAISE EXCEPTION 'expected one smard metadata row, got %', metadata_rows;
  END IF;
END
`$`$;
SELECT
  (SELECT COUNT(*) FROM smard.smard) AS smard_rows,
  (SELECT COUNT(*) FROM smard.prices) AS price_rows,
  (SELECT COUNT(*) FROM public.metadata WHERE schema_name = 'smard') AS metadata_rows;
"@

    $sql | docker compose @composeArgs exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1
    Assert-LastExitCode "real crawler DB assertions"

    if ($RunPostScripts) {
        $postSql = @"
DO `$`$
DECLARE
  gapfilled_rows integer;
BEGIN
  IF to_regclass('smard.smard_gapfilled') IS NULL THEN
    RAISE EXCEPTION 'missing smard.smard_gapfilled table';
  END IF;
  SELECT COUNT(*) INTO gapfilled_rows FROM smard.smard_gapfilled;
  IF gapfilled_rows <= 0 THEN
    RAISE EXCEPTION 'smard.smard_gapfilled has no rows';
  END IF;
END
`$`$;
SELECT COUNT(*) AS smard_gapfilled_rows FROM smard.smard_gapfilled;
"@
        $postSql | docker compose @composeArgs exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1
        Assert-LastExitCode "real crawler post-run assertions"
    }

    Write-Output "real crawler smoke passed"
}
finally {
    if ($started) {
        docker compose @composeArgs down -v --remove-orphans
    }
    $env:COMPOSE_PROJECT_NAME = $previousComposeProjectName
    $env:OEDS_RUNTIME_DIR = $previousRuntimeDir
    $env:OEDS_CRAWLER_SMOKE_CODE = $previousSmokeCode
    Pop-Location
}

param(
    [int]$TimeoutSeconds = 1800,
    [switch]$IncludeEntsoeFms
)

$ErrorActionPreference = "Stop"

$deploymentRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $deploymentRoot "..\..\..")
$composeArgs = @(
    "--profile", "crawlers",
    "-f", "compose.yml",
    "-f", "compose.modular.yml",
    "-f", "compose.test.yml"
)
$container = "oeds-modular-test-open-data"
$runtimeDir = ".tmp/runtime-active-crawlers"
$runtimeRoot = Join-Path $deploymentRoot $runtimeDir
$configPath = Join-Path $runtimeRoot "CRAWLER_CONFIG.yml"
$started = $false
$previousComposeProjectName = $env:COMPOSE_PROJECT_NAME
$previousRuntimeDir = $env:OEDS_RUNTIME_DIR
$previousSmokeCode = $env:OEDS_ACTIVE_CRAWLER_SMOKE_CODE

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

function Write-ActiveCrawlerSmokeConfig {
    param(
        [string]$Path,
        [bool]$IncludeEntsoeFms
    )

    $entsoeFmsSection = if ($IncludeEntsoeFms) {
        @"
entsoe_fms:
  enable: true
  schema_name: "entsoe_fms"
  schedule: "* * * * *"
  fms_package_window_months: 1
  fms_package_write_mode: "full_upsert"
  run_post_scripts: false
  target_data_items:
    - "EnergyPrices_12.1.D_r3"
"@
    } else {
        ""
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
entsoe_api:
  enable: true
  schema_name: "entsoe_api"
  schedule: "* * * * *"
  target_datasets:
    - "day_ahead_prices"
  country_code: "DE_LU"
  lookback_days: 1
  lookahead_days: 1
  request_pause_seconds: 0.1
  run_post_scripts: false
power_system_data:
  enable: true
  schema_name: "power_system_data"
  schedule: "* * * * *"
  run_post_scripts: false
weather_forecast:
  enable: true
  schema_name: "weather"
  schedule: "* * * * *"
  forecast_hours: 1
  past_hours: 0
  run_post_scripts: false
  locations:
    - location_id: "berlin"
      name: "Berlin"
      country_code: "DE"
      country_name: "Germany"
      region: "Berlin"
      location_type: "load_center"
      latitude: 52.52
      longitude: 13.405
      aggregation_weight: 1.0
      enabled: true
$entsoeFmsSection
"@

    $config | Set-Content -Path $Path -Encoding utf8
}

$expectedCrawlerNames = @("entsoe_api", "power_system_data", "weather_forecast")
if ($IncludeEntsoeFms) {
    $expectedCrawlerNames += "entsoe_fms"
}
$expectedCrawlerNamesJson = $expectedCrawlerNames | ConvertTo-Json -Compress

$pythonCode = @"
import json
from pathlib import Path

from oeds_scheduler_ui.application import SchedulerApplication
from oeds_scheduler_ui.runtime import CrawlerJobRunner

expected = set(json.loads('$expectedCrawlerNamesJson'))
app = SchedulerApplication(
    config_path=Path("/app/CRAWLER_CONFIG.yml"),
    inventory_path=Path("/app/modular_repos/docs/crawler-inventory.json"),
    workspace_root=Path("/app/modular_repos"),
)
plans = [plan for plan in app.plan_result.plans if plan.crawler_name in expected]
seen = {plan.crawler_name for plan in plans}
missing = sorted(expected - seen)
if missing:
    raise SystemExit(
        f"missing active crawler plan(s): {', '.join(missing)}; "
        f"skipped={app.plan_result.skipped!r}; errors={app.plan_result.errors!r}"
    )

runner = CrawlerJobRunner(app.factory)
payload = []
for plan in sorted(plans, key=lambda item: item.crawler_name):
    result = runner.run(plan)
    payload.append(
        {
            "job_id": result.job_id,
            "crawler_name": result.crawler_name,
            "crawler_success": result.crawler_success,
            "post_run_success": result.post_run_success,
            "success": result.success,
            "error": result.error,
        }
    )

print(json.dumps(payload, sort_keys=True))
raise SystemExit(0 if all(item["success"] for item in payload) else 1)
"@

Push-Location $deploymentRoot
try {
    $env:COMPOSE_PROJECT_NAME = "oeds-modular-test"

    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    $runtimeCrawlerData = Join-Path $runtimeRoot "crawler/data"
    New-Item -ItemType Directory -Force -Path $runtimeCrawlerData | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot "logs") | Out-Null
    Write-ActiveCrawlerSmokeConfig -Path $configPath -IncludeEntsoeFms ([bool]$IncludeEntsoeFms)

    $sourceEnv = Join-Path $repoRoot "crawler/.env"
    if (Test-Path $sourceEnv) {
        Copy-Item -LiteralPath $sourceEnv -Destination (Join-Path $runtimeRoot "crawler/.env") -Force
    }
    Copy-Item -LiteralPath (Join-Path $repoRoot "crawler/data/mapping_eic_to_location.py") -Destination $runtimeCrawlerData -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot "crawler/data/mapping_p_to_g.json") -Destination $runtimeCrawlerData -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot "crawler/data/mapping_g_to_p.json") -Destination $runtimeCrawlerData -Force

    $env:OEDS_RUNTIME_DIR = $runtimeDir
    $env:OEDS_ACTIVE_CRAWLER_SMOKE_CODE = $pythonCode

    docker compose @composeArgs build scheduler
    Assert-LastExitCode "docker compose build scheduler"

    docker compose @composeArgs up -d open-data
    Assert-LastExitCode "docker compose up open-data"
    $started = $true
    Wait-ForOpenData -TimeoutSeconds $TimeoutSeconds

    docker compose @composeArgs run --rm --no-deps -e OEDS_ACTIVE_CRAWLER_SMOKE_CODE scheduler python -c "import os; exec(os.environ['OEDS_ACTIVE_CRAWLER_SMOKE_CODE'])"
    Assert-LastExitCode "active crawler smoke"

    $sql = @"
DO `$`$
DECLARE
  entsoe_price_rows integer;
  power_rows integer;
  weather_rows integer;
BEGIN
  IF to_regclass('entsoe_api.day_ahead_prices') IS NULL THEN
    RAISE EXCEPTION 'missing entsoe_api.day_ahead_prices table';
  END IF;
  IF to_regclass('power_system_data.powersystemdata') IS NULL THEN
    RAISE EXCEPTION 'missing power_system_data.powersystemdata table';
  END IF;
  IF to_regclass('weather.hourly_forecast') IS NULL THEN
    RAISE EXCEPTION 'missing weather.hourly_forecast table';
  END IF;

  SELECT COUNT(*) INTO entsoe_price_rows FROM entsoe_api.day_ahead_prices;
  SELECT COUNT(*) INTO power_rows FROM power_system_data.powersystemdata;
  SELECT COUNT(*) INTO weather_rows FROM weather.hourly_forecast;

  IF entsoe_price_rows <= 0 THEN
    RAISE EXCEPTION 'entsoe_api.day_ahead_prices has no rows';
  END IF;
  IF power_rows <= 0 THEN
    RAISE EXCEPTION 'power_system_data.powersystemdata has no rows';
  END IF;
  IF weather_rows <= 0 THEN
    RAISE EXCEPTION 'weather.hourly_forecast has no rows';
  END IF;
END
`$`$;
SELECT
  (SELECT COUNT(*) FROM entsoe_api.day_ahead_prices) AS entsoe_api_day_ahead_price_rows,
  (SELECT COUNT(*) FROM power_system_data.powersystemdata) AS power_system_data_rows,
  (SELECT COUNT(*) FROM weather.hourly_forecast) AS weather_hourly_forecast_rows;
"@

    $sql | docker compose @composeArgs exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1
    Assert-LastExitCode "active crawler DB assertions"

    if ($IncludeEntsoeFms) {
        $fmsSql = @"
DO `$`$
DECLARE
  fms_price_rows integer;
BEGIN
  IF to_regclass('entsoe_fms."EnergyPrices"') IS NULL THEN
    RAISE EXCEPTION 'missing entsoe_fms."EnergyPrices" table';
  END IF;
  SELECT COUNT(*) INTO fms_price_rows FROM entsoe_fms."EnergyPrices";
  IF fms_price_rows <= 0 THEN
    RAISE EXCEPTION 'entsoe_fms."EnergyPrices" has no rows';
  END IF;
END
`$`$;
SELECT COUNT(*) AS entsoe_fms_energy_prices_rows FROM entsoe_fms."EnergyPrices";
"@
        $fmsSql | docker compose @composeArgs exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1
        Assert-LastExitCode "ENTSO-E FMS DB assertions"
    }

    Write-Output "active crawler smoke passed"
}
finally {
    if ($started) {
        docker compose @composeArgs down -v --remove-orphans
    }
    $env:COMPOSE_PROJECT_NAME = $previousComposeProjectName
    $env:OEDS_RUNTIME_DIR = $previousRuntimeDir
    $env:OEDS_ACTIVE_CRAWLER_SMOKE_CODE = $previousSmokeCode
    if (Test-Path $runtimeRoot) {
        Remove-Item -LiteralPath $runtimeRoot -Recurse -Force
    }
    Pop-Location
}

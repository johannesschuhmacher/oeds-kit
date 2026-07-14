param(
    [int]$TimeoutSeconds = 900
)

$ErrorActionPreference = "Stop"

$deploymentRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$composeArgs = @(
    "-f", "compose.yml",
    "-f", "compose.modular.yml",
    "-f", "compose.test.yml"
)
$profiledComposeArgs = @("--profile", "crawlers") + $composeArgs
$runtimeDir = ".tmp/runtime-stack"
$runtimeRoot = Join-Path $deploymentRoot $runtimeDir
$configPath = Join-Path $runtimeRoot "CRAWLER_CONFIG.yml"
$started = $false
$previousRuntimeDir = $env:OEDS_RUNTIME_DIR

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
        $state = docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" "oeds-modular-test-open-data" 2>$null
        if ($state -eq "healthy") {
            return
        }
        Start-Sleep -Seconds 5
    }

    docker compose @composeArgs logs --no-color open-data | Select-Object -Last 120
    throw "open-data did not become healthy within $TimeoutSeconds seconds"
}

function Wait-ForHttpOk {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 10
            if ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 400) {
                return
            }
        }
        catch {
            Start-Sleep -Seconds 5
            continue
        }
        Start-Sleep -Seconds 5
    }

    docker compose @profiledComposeArgs ps
    docker compose @profiledComposeArgs logs --no-color open-postgrest grafana crawler-admin | Select-Object -Last 160
    throw "$Name did not return HTTP 2xx/3xx within $TimeoutSeconds seconds"
}

function Write-StackSmokeConfig {
    param(
        [string]$Path
    )

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
  schedule: "0 4 * * *"
  post_run_scripts: []
  database_uri: "postgresql://opendata:opendata@open-data:5432/opendata?options=--search_path="
smard:
  enable: false
  schema_name: "smard"
  schedule: "0 4 * * *"
  post_run_scripts:
    - "scripts/gapfill_smard.py"
"@

    $config | Set-Content -Path $Path -Encoding utf8
}

Push-Location $deploymentRoot
try {
    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot "crawler/data") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot "logs") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot "crawler_admin_state") | Out-Null
    Write-StackSmokeConfig -Path $configPath

    $env:OEDS_RUNTIME_DIR = $runtimeDir

    docker compose @profiledComposeArgs build crawler-admin
    Assert-LastExitCode "docker compose build crawler-admin"

    docker compose @profiledComposeArgs up -d open-data open-postgrest grafana crawler-admin
    Assert-LastExitCode "docker compose up stack"
    $started = $true

    Wait-ForOpenData -TimeoutSeconds $TimeoutSeconds
    Wait-ForHttpOk -Name "PostgREST" -Url "http://127.0.0.1:13001/" -TimeoutSeconds $TimeoutSeconds
    Wait-ForHttpOk -Name "Grafana" -Url "http://127.0.0.1:13006/api/health" -TimeoutSeconds $TimeoutSeconds
    Wait-ForHttpOk -Name "Crawler admin" -Url "http://127.0.0.1:13010/" -TimeoutSeconds $TimeoutSeconds

    Write-Output "modular stack smoke passed"
}
finally {
    if ($started) {
        docker compose @profiledComposeArgs down -v --remove-orphans
    }
    $env:OEDS_RUNTIME_DIR = $previousRuntimeDir
    Pop-Location
}

param(
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"

$deploymentRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$composeArgs = @(
    "-f", "compose.yml",
    "-f", "compose.modular.yml",
    "-f", "compose.test.yml"
)
$container = "oeds-modular-test-open-data"
$started = $false

Push-Location $deploymentRoot
try {
    docker compose @composeArgs up -d open-data
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed with exit code $LASTEXITCODE"
    }
    $started = $true

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $healthy = $false
    while ((Get-Date) -lt $deadline) {
        $state = docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $container 2>$null
        if ($state -eq "healthy") {
            $healthy = $true
            break
        }
        Start-Sleep -Seconds 5
    }

    if (-not $healthy) {
        docker compose @composeArgs logs --no-color open-data | Select-Object -Last 120
        throw "open-data did not become healthy within $TimeoutSeconds seconds"
    }

    $sql = @"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'readonly') THEN
    RAISE EXCEPTION 'missing readonly role';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
    RAISE EXCEPTION 'missing postgis extension';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proname = 'linear_interpolate'
  ) THEN
    RAISE EXCEPTION 'missing public.linear_interpolate';
  END IF;
END
`$`$;
SELECT 'init assertions passed' AS status;
"@

    $sql | docker compose @composeArgs exec -T open-data psql -U opendata -d opendata -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) {
        throw "psql assertions failed with exit code $LASTEXITCODE"
    }

    Write-Output "isolated DB smoke passed"
}
finally {
    if ($started) {
        docker compose @composeArgs down -v --remove-orphans
    }
    Pop-Location
}

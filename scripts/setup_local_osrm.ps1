$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dataDirectory = Join-Path $env:LOCALAPPDATA "LastMileDeliveryPlatform\osrm"
$mapName = "southern-zone-latest.osm.pbf"
$mapPath = Join-Path $dataDirectory $mapName
$partialMapPath = "$mapPath.partial"
$mapUrl = "https://download.geofabrik.de/asia/india/$mapName"
$volumeName = "lmd-osrm-data"
$osrmImage = "ghcr.io/project-osrm/osrm-backend:v5.27.1"

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed: docker $($Arguments -join ' ')"
    }
}

New-Item -ItemType Directory -Force -Path $dataDirectory | Out-Null

if (-not (Test-Path -LiteralPath $mapPath)) {
    Write-Host "Downloading the South India OpenStreetMap extract (about 533 MB)..."
    & curl.exe --fail --location --retry 3 --output $partialMapPath $mapUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Map download failed. The partial download is at $partialMapPath."
    }
    if ((Get-Item -LiteralPath $partialMapPath).Length -lt 100MB) {
        throw "Downloaded map is unexpectedly small; refusing to prepare it."
    }
    Move-Item -LiteralPath $partialMapPath -Destination $mapPath -Force
}

Invoke-Docker -Arguments @("pull", $osrmImage)
Invoke-Docker -Arguments @("volume", "create", $volumeName)

$volumeState = & docker run --rm --volume "${volumeName}:/data" alpine:3.22 sh -c `
    "if [ -f /data/.prepared ]; then echo prepared; else echo missing; fi"
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the OSRM Docker volume."
}
$isPrepared = $volumeState -contains "prepared"

if (-not $isPrepared) {
    $dockerDataDirectory = $dataDirectory.Replace("\", "/")
    Invoke-Docker -Arguments @(
        "run", "--rm",
        "--volume", "${volumeName}:/data",
        "--mount", "type=bind,source=$dockerDataDirectory,target=/input,readonly",
        "alpine:3.22", "sh", "-c", "cp /input/$mapName /data/$mapName"
    )
    Invoke-Docker -Arguments @(
        "run", "--rm", "--volume", "${volumeName}:/data",
        $osrmImage, "osrm-extract", "-p", "/opt/car.lua", "/data/$mapName"
    )
    Invoke-Docker -Arguments @(
        "run", "--rm", "--volume", "${volumeName}:/data",
        $osrmImage, "osrm-partition", "/data/southern-zone-latest.osrm"
    )
    Invoke-Docker -Arguments @(
        "run", "--rm", "--volume", "${volumeName}:/data",
        $osrmImage, "osrm-customize", "/data/southern-zone-latest.osrm"
    )
    Invoke-Docker -Arguments @(
        "run", "--rm", "--volume", "${volumeName}:/data",
        "alpine:3.22", "sh", "-c", "touch /data/.prepared"
    )
}

Push-Location $repoRoot
try {
    Invoke-Docker -Arguments @("compose", "--profile", "infra", "up", "-d", "osrm")
}
finally {
    Pop-Location
}

$ready = $false
$lastError = "OSRM did not become ready before the timeout."
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $response = Invoke-RestMethod -UseBasicParsing `
            -Uri "http://127.0.0.1:5000/nearest/v1/driving/78.4867,17.385?number=1" `
            -TimeoutSec 5
        if ($response.code -eq "Ok") {
            $ready = $true
            break
        }
        $lastError = "OSRM returned code '$($response.code)'."
    }
    catch {
        $lastError = $_.Exception.Message
    }
    Start-Sleep -Seconds 2
}

if (-not $ready) {
    throw "OSRM failed its local readiness check: $lastError"
}

Write-Host "Local OSRM is ready at http://127.0.0.1:5000."

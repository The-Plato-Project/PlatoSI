[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'plato-common.ps1')
$inventory = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'docs\morphology-inventory.json') | ConvertFrom-Json
$headers = @{ 'User-Agent' = 'PlatoSI-morphology-downloader' }

foreach ($source in $inventory.sources) {
    foreach ($file in $source.files) {
        $relative = "data/greek-morphology/$($source.id)/$($file.source_path)"
        $destination = Join-Path $root ($relative.Replace('/', '\'))
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        if ((Test-Path -LiteralPath $destination) -and (Get-GitBlobSha1 $destination) -eq $file.git_blob_sha1) {
            continue
        }
        $temp = "$destination.download"
        try {
            $repo = $source.repository.Replace('https://github.com/', '')
            $uri = "https://raw.githubusercontent.com/$repo/$($source.revision)/$($file.source_path)"
            Invoke-WebRequest -Headers $headers -Uri $uri -OutFile $temp
            if ((Get-GitBlobSha1 $temp) -ne $file.git_blob_sha1) {
                throw "Downloaded bytes do not match the pinned Git blob: $relative"
            }
            Move-Item -LiteralPath $temp -Destination $destination -Force
        } finally {
            if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp }
        }
        Write-Host "Downloaded $relative"
    }
}
& (Join-Path $PSScriptRoot 'validate-morphology.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

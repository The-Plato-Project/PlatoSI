[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$revision = 'ae135f548e0399d43cd09d45fed129cbec0e9b5c'
$repository = 'helmadik/LSJLogeion'
$headers = @{ 'User-Agent' = 'PlatoSI-LSJ-downloader' }
$tree = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$repository/git/trees/$($revision)?recursive=1"
if ($tree.truncated) { throw 'GitHub returned a truncated LSJ tree.' }

$entries = @($tree.tree | Where-Object {
    $_.type -eq 'blob' -and ($_.path -match '^greatscott\d+\.xml$' -or $_.path -in @('README.md', 'LICENSE.md'))
} | Sort-Object path)
if (@($entries | Where-Object { $_.path -match '^greatscott\d+\.xml$' }).Count -eq 0) {
    throw 'No LSJ XML files found in the pinned source tree.'
}
foreach ($required in @('README.md', 'LICENSE.md')) {
    if (@($entries | Where-Object { $_.path -eq $required }).Count -ne 1) {
        throw "Missing source metadata file: $required"
    }
}

. (Join-Path $PSScriptRoot 'plato-common.ps1')
$files = @(
    foreach ($entry in $entries) {
        [ordered]@{
            source_path = $entry.path
            local_path = "data/lsj-logeion/$($entry.path)"
            git_blob_sha1 = $entry.sha
            size = $entry.size
        }
    }
)
foreach ($file in $files) {
    $destination = Join-Path $root ($file.local_path.Replace('/', '\'))
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    if ((Test-Path -LiteralPath $destination) -and (Get-GitBlobSha1 $destination) -eq $file.git_blob_sha1) {
        continue
    }
    $temp = "$destination.download"
    try {
        Invoke-WebRequest -Headers $headers -Uri "https://raw.githubusercontent.com/$repository/$revision/$($file.source_path)" -OutFile $temp
        if ((Get-GitBlobSha1 $temp) -ne $file.git_blob_sha1) {
            throw "Downloaded bytes do not match the upstream Git blob: $($file.source_path)"
        }
        Move-Item -LiteralPath $temp -Destination $destination -Force
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp }
    }
    Write-Host "Downloaded $($file.local_path)"
}

$inventory = [ordered]@{
    repository = "https://github.com/$repository"
    revision = $revision
    selection = 'All greatscott XML files, README.md, and LICENSE.md from the pinned repository tree.'
    format = 'UTF-8 TEI P4-style XML; lexical entries are div2 elements with head children.'
    attribution = 'Perseus Tufts and Helma Dik/Logeion, as requested by the upstream README.'
    license = 'CC BY-SA 4.0, as stated in the upstream LICENSE.md.'
    files = $files
}
$inventory | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 (Join-Path $root 'docs\lsj-inventory.json')
& (Join-Path $PSScriptRoot 'validate-lsj.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$revision = 'a6eb0cc3e6f6e382934a2c8b33577d2fb4371e00'
$repository = 'PerseusDL/canonical-greekLit'
$headers = @{ 'User-Agent' = 'PlatoSI-corpus-downloader' }
$api = "https://api.github.com/repos/$repository/git/trees"
$raw = "https://raw.githubusercontent.com/$repository/$revision"

function Get-Tree($sha, $recursive = $false) {
    $suffix = ''
    if ($recursive) { $suffix = '?recursive=1' }
    $tree = Invoke-RestMethod -Headers $headers -Uri "$api/$sha$suffix"
    if ($tree.truncated) { throw "GitHub returned a truncated tree for $sha." }
    return $tree
}

function Get-ChildTree($tree, $name) {
    $found = @($tree.tree | Where-Object { $_.path -eq $name -and $_.type -eq 'tree' })
    if ($found.Count -ne 1) { throw "Expected one directory named $name in Git tree." }
    return Get-Tree $found[0].sha
}

$rootTree = Get-Tree $revision
$dataTree = Get-ChildTree $rootTree 'data'
$platoEntry = @($dataTree.tree | Where-Object { $_.path -eq 'tlg0059' -and $_.type -eq 'tree' })
if ($platoEntry.Count -ne 1) { throw 'Expected one tlg0059 directory in the source tree.' }
$platoTree = Get-Tree $platoEntry[0].sha $true
$entries = @($platoTree.tree | Where-Object {
    $_.type -eq 'blob' -and ($_.path -match '(^|/)__cts__\.xml$' -or $_.path -match '\.perseus-grc[^.]*\.xml$')
} | Sort-Object path)
if ($entries.Count -eq 0) { throw 'No Plato XML files found in the pinned source tree.' }

$files = @(
    foreach ($entry in $entries) {
        [ordered]@{
            source_path = "data/tlg0059/$($entry.path)"
            local_path = "data/tlg0059/$($entry.path)"
            git_blob_sha1 = $entry.sha
            size = $entry.size
        }
    }
    foreach ($name in @('README.md', 'license.md')) {
        $entry = @($rootTree.tree | Where-Object { $_.path -eq $name -and $_.type -eq 'blob' })
        if ($entry.Count -ne 1) { throw "Missing source licensing file: $name" }
        [ordered]@{
            source_path = $name
            local_path = "data/upstream/$name"
            git_blob_sha1 = $entry[0].sha
            size = $entry[0].size
        }
    }
)

. (Join-Path $PSScriptRoot 'plato-common.ps1')
foreach ($file in $files) {
    $destination = Join-Path $root ($file.local_path.Replace('/', '\'))
    $parent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if ((Test-Path -LiteralPath $destination) -and (Get-GitBlobSha1 $destination) -eq $file.git_blob_sha1) {
        continue
    }
    $temp = "$destination.download"
    try {
        Invoke-WebRequest -Headers $headers -Uri "$raw/$($file.source_path)" -OutFile $temp
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
    selection = 'All __cts__.xml files and Perseus Greek edition XML files in data/tlg0059; translations excluded.'
    files = $files
}
$inventory | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 (Join-Path $root 'docs\corpus-inventory.json')
& (Join-Path $PSScriptRoot 'validate-plato.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

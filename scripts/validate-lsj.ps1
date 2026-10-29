[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'plato-common.ps1')
$inventory = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'docs\lsj-inventory.json') | ConvertFrom-Json
$issues = New-Object System.Collections.Generic.List[object]
$results = New-Object System.Collections.Generic.List[object]
$seenIds = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([System.StringComparer]::Ordinal)
$duplicateIds = New-Object System.Collections.Generic.List[object]
$verified = 0
$parsed = 0
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)

function Add-Issue($severity, $path, $message) {
    $issues.Add([ordered]@{ severity = $severity; path = $path; message = $message })
}

foreach ($file in $inventory.files) {
    $path = Join-Path $root ($file.local_path.Replace('/', '\'))
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Add-Issue 'error' $file.local_path 'File is missing.'
        continue
    }
    if ((Get-GitBlobSha1 $path) -ne $file.git_blob_sha1) {
        Add-Issue 'error' $file.local_path 'File does not match the pinned upstream Git blob.'
    } else {
        $verified++
    }
    try {
        $reader = New-Object System.IO.StreamReader($path, $utf8, $false)
        try { $content = $reader.ReadToEnd() } finally { $reader.Dispose() }
    } catch [System.Text.DecoderFallbackException] {
        Add-Issue 'error' $file.local_path "Invalid UTF-8: $($_.Exception.Message)"
        continue
    }
    if ($content.Contains([char]0xFFFD)) {
        Add-Issue 'warning' $file.local_path 'File contains Unicode replacement characters.'
    }
    if ($file.local_path -notmatch '\.xml$') { continue }
    try {
        $settings = New-Object System.Xml.XmlReaderSettings
        $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
        $settings.XmlResolver = $null
        $stringReader = New-Object System.IO.StringReader($content)
        $reader = [System.Xml.XmlReader]::Create($stringReader, $settings)
        try {
            $xml = New-Object System.Xml.XmlDocument
            $xml.XmlResolver = $null
            $xml.Load($reader)
        } finally {
            $reader.Dispose()
            $stringReader.Dispose()
        }
    } catch [System.Xml.XmlException] {
        Add-Issue 'error' $file.local_path "XML is not well-formed: $($_.Exception.Message)"
        continue
    }
    if ($xml.DocumentElement.Name -ne 'tei.2') {
        Add-Issue 'error' $file.local_path 'Unexpected XML root; expected tei.2.'
        continue
    }
    $parsed++
    $entries = $xml.SelectNodes('/tei.2/text/div1/div2')
    $otherDivisions = $xml.SelectNodes('//div2[not(parent::div1[parent::text])]')
    foreach ($division in $otherDivisions) {
        if (-not $division.SelectSingleNode('ancestor::front')) {
            Add-Issue 'warning' $file.local_path 'Found a div2 outside the entry path and front matter; it is excluded from the entry count.'
        }
    }
    $greek = 0
    $missingHead = 0
    $nonGreekHead = 0
    $missingId = 0
    $missingType = 0
    $samples = New-Object System.Collections.Generic.List[object]
    $types = @{}
    foreach ($entry in $entries) {
        $type = $entry.GetAttribute('type')
        if (-not $type) { $missingType++ }
        if (-not $types.ContainsKey($type)) { $types[$type] = 0 }
        $types[$type]++
        $head = $entry.SelectSingleNode('./head')
        $id = $entry.GetAttribute('id')
        if (-not $id) {
            $missingId++
        } elseif ($seenIds.ContainsKey($id)) {
            $duplicateIds.Add([ordered]@{
                id = $id
                first_path = $seenIds[$id].path
                first_head = $seenIds[$id].head
                duplicate_path = $file.local_path
                duplicate_head = if ($head) { $head.InnerText.Trim() } else { '' }
            })
        } else {
            $seenIds.Add($id, [ordered]@{
                path = $file.local_path
                head = if ($head) { $head.InnerText.Trim() } else { '' }
            })
        }
        $problem = ''
        if (-not $head -or -not $head.InnerText.Trim()) {
            $missingHead++
            $problem = 'Missing or empty head element.'
        } elseif ($head.InnerText -notmatch '(?=[\u0370-\u03FF\u1F00-\u1FFF])\p{L}') {
            $nonGreekHead++
            $problem = 'Head contains no Greek-block letter.'
        } else {
            $greek++
        }
        if ($problem -and $samples.Count -lt 10) {
            $samples.Add([ordered]@{
                id = $entry.GetAttribute('id')
                head = if ($head) { $head.InnerText.Trim() } else { '' }
                problem = $problem
            })
        }
    }
    if ($missingHead -gt 0 -or $nonGreekHead -gt 0) {
        Add-Issue 'warning' $file.local_path "$missingHead entries have missing or empty heads; $nonGreekHead have no Greek-block letter in the head. See file results for examples."
    }
    if ($missingId -gt 0) { Add-Issue 'warning' $file.local_path "$missingId entries have no id attribute." }
    if ($missingType -gt 0) { Add-Issue 'warning' $file.local_path "$missingType entries have no type attribute." }
    $results.Add([ordered]@{
        path = $file.local_path
        entries = $entries.Count
        entries_by_type = @(
            foreach ($type in @($types.Keys | Sort-Object)) {
                [ordered]@{ type = $type; count = $types[$type] }
            }
        )
        excluded_div2_elements = $otherDivisions.Count
        heads_with_greek_letters = $greek
        missing_or_empty_heads = $missingHead
        heads_without_greek_letters = $nonGreekHead
        missing_entry_ids = $missingId
        missing_entry_types = $missingType
        problem_examples = @($samples.ToArray())
    })
}

if ($duplicateIds.Count -gt 0) {
    Add-Issue 'warning' 'data/lsj-logeion' "$($duplicateIds.Count) entry ID occurrences duplicate earlier entries. See duplicate_entry_ids."
}
$xmlExpected = @($inventory.files | Where-Object { $_.local_path -match '\.xml$' }).Count
$entryCount = 0
$greekCount = 0
foreach ($result in $results) {
    $entryCount += $result.entries
    $greekCount += $result.heads_with_greek_letters
}
$errors = @($issues | Where-Object { $_.severity -eq 'error' })
$warnings = @($issues | Where-Object { $_.severity -eq 'warning' })
$manifest = [ordered]@{
    repository = $inventory.repository
    revision = $inventory.revision
    selection = $inventory.selection
    format = $inventory.format
    attribution = $inventory.attribution
    license = $inventory.license
    validation_scope = 'Git blob integrity, strict UTF-8 decoding, XML well-formedness, TEI root, div2 headword and entry ID checks. Not TEI schema validation, lexicographic accuracy or coverage validation.'
    expected_files = @($inventory.files).Count
    verified_files = $verified
    expected_xml_files = $xmlExpected
    parsed_xml_files = $parsed
    counts_complete = ($parsed -eq $xmlExpected -and $errors.Count -eq 0)
    lexical_entries = $entryCount
    heads_with_greek_letters = $greekCount
    duplicate_entry_id_occurrences = $duplicateIds.Count
    duplicate_entry_ids = @($duplicateIds.ToArray())
    files = @($results.ToArray())
    issues = @($issues.ToArray())
    coverage_notes = @(
        'This is the edited Logeion LSJ repository, not all Logeion dictionaries or the website.',
        'The upstream README describes ongoing corrections and says only a few supplement changes have been incorporated.'
    )
}
$manifest | ConvertTo-Json -Depth 15 | Set-Content -Encoding UTF8 (Join-Path $root 'docs\lsj-manifest.json')
Write-Host "Verified $verified/$(@($inventory.files).Count) files; parsed $parsed/$xmlExpected XML files; $entryCount entries; $greekCount heads with Greek letters."
Write-Host "Validation: $($errors.Count) errors, $($warnings.Count) warnings. See docs\lsj-manifest.json."
foreach ($issue in $issues) { Write-Host "$($issue.severity): $($issue.path): $($issue.message)" }
if ($errors.Count -gt 0) { exit 1 }

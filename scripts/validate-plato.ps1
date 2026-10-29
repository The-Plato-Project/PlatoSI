[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'plato-common.ps1')
$inventory = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'docs\corpus-inventory.json') | ConvertFrom-Json
$issues = New-Object System.Collections.Generic.List[object]
$documents = @{}
$verified = 0

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
    if ($file.local_path -notmatch '\.xml$') { continue }
    try {
        $settings = New-Object System.Xml.XmlReaderSettings
        $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
        $settings.XmlResolver = $null
        $reader = [System.Xml.XmlReader]::Create($path, $settings)
        try {
            $xml = New-Object System.Xml.XmlDocument
            $xml.XmlResolver = $null
            $xml.Load($reader)
            $documents[$file.local_path] = $xml
        } finally {
            $reader.Dispose()
        }
    } catch [System.Xml.XmlException] {
        Add-Issue 'error' $file.local_path "XML is not well-formed: $($_.Exception.Message)"
    }
}

$works = @(
    foreach ($metadataPath in @($documents.Keys | Where-Object { $_ -match '^data/tlg0059/[^/]+/__cts__\.xml$' } | Sort-Object)) {
        $metadata = $documents[$metadataPath]
        $ns = New-Object System.Xml.XmlNamespaceManager($metadata.NameTable)
        $ns.AddNamespace('cts', 'http://chs.harvard.edu/xmlns/cts')
        $work = $metadata.SelectSingleNode('/cts:work', $ns)
        if (-not $work) {
            Add-Issue 'error' $metadataPath 'CTS work metadata has no work element.'
            continue
        }
        $titleNode = $work.SelectSingleNode('cts:title', $ns)
        $title = if ($titleNode) { $titleNode.InnerText.Trim() } else { '' }
        $editions = @(
            foreach ($edition in $work.SelectNodes('cts:edition', $ns)) {
                if ($edition.GetAttribute('lang', 'http://www.w3.org/XML/1998/namespace') -ne 'grc') { continue }
                $urn = $edition.GetAttribute('urn')
                $id = ($urn -split ':')[-1]
                $directory = $metadataPath.Substring(0, $metadataPath.LastIndexOf('/'))
                $editionPath = "$directory/$id.xml"
                $label = $edition.SelectSingleNode('cts:label', $ns)
                $description = $edition.SelectSingleNode('cts:description', $ns)
                $citations = @()
                $milestones = @()
                if (-not $documents.ContainsKey($editionPath)) {
                    Add-Issue 'error' $editionPath "Greek edition declared in CTS metadata is missing or invalid: $urn"
                } else {
                    $text = $documents[$editionPath]
                    $tns = New-Object System.Xml.XmlNamespaceManager($text.NameTable)
                    $tns.AddNamespace('tei', 'http://www.tei-c.org/ns/1.0')
                    $textNode = $text.SelectSingleNode('/tei:TEI/tei:text', $tns)
                    $body = $text.SelectSingleNode('/tei:TEI/tei:text/tei:body', $tns)
                    if ($textNode -and $textNode.GetAttribute('lang', 'http://www.w3.org/XML/1998/namespace') -ne 'grc') {
                        Add-Issue 'warning' $editionPath 'TEI text language is not marked grc.'
                    }
                    if (-not $body) {
                        Add-Issue 'error' $editionPath 'TEI text has no body.'
                    } else {
                        if ($body.InnerText -notmatch '[\u0370-\u03FF\u1F00-\u1FFF]') {
                            Add-Issue 'error' $editionPath 'TEI body contains no characters in the Greek Unicode blocks.'
                        }
                        if ($body.GetAttribute('base', 'http://www.w3.org/XML/1998/namespace') -ne $urn) {
                            Add-Issue 'warning' $editionPath "TEI body xml:base differs from CTS edition URN $urn."
                        }
                    }
                    $citations = @($text.SelectNodes('//tei:encodingDesc/tei:refsDecl', $tns) | ForEach-Object { $_.OuterXml })
                    if ($citations.Count -eq 0) { Add-Issue 'warning' $editionPath 'No TEI refsDecl citation declaration found.' }
                    $milestones = @($text.SelectNodes('//tei:text//tei:milestone[@unit]', $tns) |
                        ForEach-Object { $_.GetAttribute('unit') } | Sort-Object -Unique)
                }
                [ordered]@{
                    urn = $urn
                    label = if ($label) { $label.InnerText.Trim() } else { '' }
                    description = if ($description) { $description.InnerText.Trim() } else { '' }
                    path = $editionPath
                    citation_declarations_xml = $citations
                    milestone_units = $milestones
                }
            }
        )
        if ($editions.Count -eq 0) { Add-Issue 'warning' $metadataPath 'No Greek edition declared in CTS work metadata.' }
        [ordered]@{
            urn = $work.GetAttribute('urn')
            title = $title
            metadata_path = $metadataPath
            editions = $editions
        }
    }
)

foreach ($file in @($inventory.files | Where-Object { $_.local_path -match '\.perseus-grc[^.]*\.xml$' })) {
    $matches = @($works | ForEach-Object { $_.editions } | Where-Object { $_.path -eq $file.local_path })
    if ($matches.Count -ne 1) { Add-Issue 'error' $file.local_path "Greek XML is referenced by $($matches.Count) CTS editions, expected one." }
}

$manifest = [ordered]@{
    repository = $inventory.repository
    revision = $inventory.revision
    validation_scope = 'Git blob integrity and XML well-formedness; CTS metadata linkage, TEI language, body content and identifier, and citation declarations. Not TEI/EpiDoc schema validation or scholarly completeness.'
    expected_files = @($inventory.files).Count
    verified_files = $verified
    parsed_xml_files = $documents.Count
    work_count = $works.Count
    edition_count = @($works | ForEach-Object { $_.editions }).Count
    works = $works
    issues = @($issues.ToArray())
}
$manifest | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 (Join-Path $root 'docs\corpus-manifest.json')
$errors = @($issues | Where-Object { $_.severity -eq 'error' })
$warnings = @($issues | Where-Object { $_.severity -eq 'warning' })
Write-Host "Verified $verified/$(@($inventory.files).Count) files; parsed $($documents.Count) XML files; $($works.Count) works; $($manifest.edition_count) Greek editions."
Write-Host "Validation: $($errors.Count) errors, $($warnings.Count) warnings. See docs\corpus-manifest.json."
foreach ($issue in $issues) { Write-Host "$($issue.severity): $($issue.path): $($issue.message)" }
if ($errors.Count -gt 0) { exit 1 }

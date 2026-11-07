[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'plato-common.ps1')
$inventory = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'docs\morphology-inventory.json') | ConvertFrom-Json
$samples = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'docs\morphology-samples.json') | ConvertFrom-Json
$issues = New-Object System.Collections.Generic.List[object]
$fileResults = New-Object System.Collections.Generic.List[object]
$sampleResults = New-Object System.Collections.Generic.List[object]
$treebankMatches = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([System.StringComparer]::Ordinal)
$verifiedPlatoPaths = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$verified = 0
$expected = 0
$treebank = $null

function Add-Issue($severity, $path, $message) {
    $issues.Add([ordered]@{ severity = $severity; path = $path; message = $message })
}
function Read-SecureXml($path) {
    $reader = New-Object System.IO.StreamReader($path, $utf8, $false)
    try {
        $settings = New-Object System.Xml.XmlReaderSettings
        $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
        $settings.XmlResolver = $null
        $xmlReader = [System.Xml.XmlReader]::Create($reader, $settings)
        try {
            $xml = New-Object System.Xml.XmlDocument
            $xml.XmlResolver = $null
            $xml.Load($xmlReader)
            return $xml
        } finally { $xmlReader.Dispose() }
    } finally { $reader.Dispose() }
}
foreach ($sample in $samples) {
    $key = $sample.form.Normalize([System.Text.NormalizationForm]::FormC)
    if ($treebankMatches.ContainsKey($key)) { throw "Duplicate sample form: $key" }
    $treebankMatches.Add($key, (New-Object System.Collections.Generic.List[object]))
}

foreach ($source in $inventory.sources) {
    foreach ($file in $source.files) {
        $expected++
        $relative = "data/greek-morphology/$($source.id)/$($file.source_path)"
        $path = Join-Path $root ($relative.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            Add-Issue 'error' $relative 'File is missing.'
            continue
        }
        $fileIntegrity = (Get-GitBlobSha1 $path) -eq $file.git_blob_sha1
        if (-not $fileIntegrity) {
            Add-Issue 'error' $relative 'File does not match the pinned upstream Git blob.'
        } else {
            $verified++
        }
        if ($file.source_path -match '\.pdf$') { continue }
        if ($file.format -eq 'xml' -or $file.format -eq 'treebank') {
            try {
                $xml = Read-SecureXml $path
            } catch [System.Xml.XmlException] {
                Add-Issue 'error' $relative "XML or UTF-8 is invalid: $($_.Exception.Message)"
                continue
            } catch [System.Text.DecoderFallbackException] {
                Add-Issue 'error' $relative "Invalid UTF-8: $($_.Exception.Message)"
                continue
            }
            if ($file.format -eq 'treebank') {
                if ($xml.DocumentElement.Name -ne 'treebank') {
                    Add-Issue 'error' $relative 'Expected a treebank root.'
                    continue
                }
                $words = $xml.SelectNodes('/treebank/body/sentence/word')
                $missingForm = 0; $missingLemma = 0; $missingTag = 0; $artificial = 0
                $naturalMissingLemma = 0; $naturalMissingTag = 0; $placeholderTags = 0
                $annotationExamples = New-Object System.Collections.Generic.List[object]
                foreach ($word in $words) {
                    $form = $word.GetAttribute('form')
                    $lemma = $word.GetAttribute('lemma')
                    $tag = $word.GetAttribute('postag')
                    if (-not $form) { $missingForm++ }
                    if (-not $lemma) { $missingLemma++ }
                    if (-not $tag) { $missingTag++ }
                    if ($word.HasAttribute('artificial')) { $artificial++ }
                    else {
                        if (-not $lemma) { $naturalMissingLemma++ }
                        if (-not $tag) { $naturalMissingTag++ }
                        if ($tag -match '^-+$') { $placeholderTags++ }
                        if ((-not $lemma -or -not $tag -or $tag -match '^-+$') -and $annotationExamples.Count -lt 20) {
                            $annotationExamples.Add([ordered]@{
                                form = $form; lemma = $lemma; tag = $tag
                                sentence_id = $word.ParentNode.GetAttribute('id'); citation = $word.GetAttribute('cite')
                            })
                        }
                    }
                    $normalized = $form.Normalize([System.Text.NormalizationForm]::FormC)
                    if ($treebankMatches.ContainsKey($normalized)) {
                        $treebankMatches[$normalized].Add([ordered]@{
                            form = $form; lemma = $lemma; tag = $tag
                            sentence_id = $word.ParentNode.GetAttribute('id')
                            citation = $word.GetAttribute('cite')
                        })
                    }
                }
                if ($words.Count -eq 0) { Add-Issue 'error' $relative 'Treebank contains no word elements.' }
                if ($missingForm -or $naturalMissingLemma -or $naturalMissingTag -or $placeholderTags) {
                    Add-Issue 'warning' $relative "Non-artificial nodes: $naturalMissingLemma empty lemmas, $naturalMissingTag empty tags, $placeholderTags all-placeholder tags; $missingForm nodes have empty forms."
                }
                $treebank = [ordered]@{
                    path = $relative; cts = $xml.DocumentElement.GetAttribute('cts')
                    word_nodes = $words.Count; artificial_word_nodes = $artificial
                    missing_forms = $missingForm; missing_lemmas = $missingLemma; missing_tags = $missingTag
                    non_artificial_empty_lemmas = $naturalMissingLemma
                    non_artificial_empty_tags = $naturalMissingTag
                    non_artificial_placeholder_tags = $placeholderTags
                    annotation_problem_examples = @($annotationExamples.ToArray())
                }
            } else {
                $fileResults.Add([ordered]@{ path = $relative; format = $file.format; root = $xml.DocumentElement.Name })
            }
        } else {
            try {
                $reader = New-Object System.IO.StreamReader($path, $utf8, $false)
                try { $null = $reader.ReadToEnd() } finally { $reader.Dispose() }
            } catch [System.Text.DecoderFallbackException] {
                Add-Issue 'error' $relative "Invalid UTF-8: $($_.Exception.Message)"
            }
        }
    }
}

# Verify only the Plato files needed by the retained treebank/sample checks.
$corpusInventoryPath = Join-Path $root 'docs\corpus-inventory.json'
if (Test-Path -LiteralPath $corpusInventoryPath) {
    $corpusInventory = Get-Content -Raw -Encoding UTF8 $corpusInventoryPath | ConvertFrom-Json
    foreach ($samplePath in @($samples.plato_path | Select-Object -Unique)) {
        $entry = @($corpusInventory.files | Where-Object { $_.local_path -ceq $samplePath })
        $path = Join-Path $root ($samplePath.Replace('/', '\'))
        if ($entry.Count -eq 1 -and (Test-Path -LiteralPath $path -PathType Leaf) -and
            (Get-GitBlobSha1 $path) -eq $entry[0].git_blob_sha1) {
            $null = $verifiedPlatoPaths.Add($samplePath)
        }
    }
}

$platoDocuments = @{}
foreach ($sample in $samples) {
    $path = Join-Path $root ($sample.plato_path.Replace('/', '\'))
    $attested = $null
    if (-not $verifiedPlatoPaths.Contains($sample.plato_path)) {
        if (-not $platoDocuments.ContainsKey($sample.plato_path)) {
            Add-Issue 'warning' $sample.plato_path 'Plato source is unavailable or unverified; sample attestation cannot be checked.'
            $platoDocuments[$sample.plato_path] = $null
        }
    } else {
        if (-not $platoDocuments.ContainsKey($sample.plato_path)) {
            $plato = Read-SecureXml $path
            $ns = New-Object System.Xml.XmlNamespaceManager($plato.NameTable)
            $ns.AddNamespace('tei', 'http://www.tei-c.org/ns/1.0')
            $body = $plato.SelectSingleNode('/tei:TEI/tei:text/tei:body', $ns)
            if (-not $body) { throw "Missing TEI body in $($sample.plato_path)" }
            $platoDocuments[$sample.plato_path] = $body.InnerText.Normalize([System.Text.NormalizationForm]::FormC)
        }
        $pattern = '(?<![\p{L}\p{M}])' + [regex]::Escape($sample.form.Normalize([System.Text.NormalizationForm]::FormC)) + '(?![\p{L}\p{M}])'
        $attested = [regex]::IsMatch($platoDocuments[$sample.plato_path], $pattern, [System.Text.RegularExpressions.RegexOptions]::CultureInvariant)
        if (-not $attested) { Add-Issue 'error' $sample.plato_path "Sample form not found as a token: $($sample.form)" }
    }
    $key = $sample.form.Normalize([System.Text.NormalizationForm]::FormC)
    $treebankHits = @($treebankMatches[$key].ToArray())
    $treebankExpectedFound = $null
    if ($sample.treebank_expected) {
        $treebankExpectedFound = @($treebankHits | Where-Object { $_.lemma.Normalize([System.Text.NormalizationForm]::FormC) -ceq $sample.expected_lemma.Normalize([System.Text.NormalizationForm]::FormC) }).Count -gt 0
        if (-not $treebankExpectedFound) { Add-Issue 'error' 'docs/morphology-samples.json' "Expected Euthyphro treebank mapping not found for $($sample.form)." }
    }
    $sampleResults.Add([ordered]@{
        form = $sample.form; reference = $sample.reference; plato_path = $sample.plato_path
        attested_in_plato = $attested; expected_lemma = $sample.expected_lemma
        euthyphro_treebank_matches = $treebankHits
        expected_treebank_lemma_found = $treebankExpectedFound
    })
}

$errors = @($issues | Where-Object { $_.severity -eq 'error' })
$warnings = @($issues | Where-Object { $_.severity -eq 'warning' })
$manifest = [ordered]@{
    sources = @($inventory.sources | ForEach-Object {
        [ordered]@{ id = $_.id; repository = $_.repository; revision = $_.revision; description = $_.description; license_note = $_.license_note }
    })
    validation_scope = 'Pinned Git blob hashes; strict UTF-8 for text; XML well-formedness; treebank attribute completeness; exact NFC sample matches and Plato attestation. Not linguistic accuracy, exhaustive coverage or XML schema validation.'
    expected_files = $expected; verified_files = $verified
    source_files = @($fileResults.ToArray())
    euthyphro_treebank = $treebank
    sample_tests = @($sampleResults.ToArray())
    limitations = @(
        'The AGDT selection provides contextual annotations for Euthyphro only, not the full Platonic corpus; its README reports remaining annotation issues.'
    )
    issues = @($issues.ToArray())
}
$manifest | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 (Join-Path $root 'docs\morphology-manifest.json')
Write-Host "Verified $verified/$expected source files. Validation: $($errors.Count) errors, $($warnings.Count) warnings."
foreach ($issue in $issues) { Write-Host "$($issue.severity): $($issue.path): $($issue.message)" }
foreach ($sample in $sampleResults) {
    Write-Host "$($sample.form): $(@($sample.euthyphro_treebank_matches).Count) Euthyphro annotations; Plato attested=$($sample.attested_in_plato)."
}
if ($errors.Count -gt 0) { exit 1 }

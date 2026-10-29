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
$matchesByForm = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([System.StringComparer]::Ordinal)
$treebankMatches = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([System.StringComparer]::Ordinal)
$mergedForms = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
$verifiedPlatoPaths = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
$mergedListValid = $false
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
    if ($matchesByForm.ContainsKey($key)) { throw "Duplicate sample form: $key" }
    $matchesByForm.Add($key, (New-Object System.Collections.Generic.List[object]))
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
        if ($file.format -eq 'wlt' -or $file.format -eq 'wltf') {
            $count = 0
            $malformed = 0
            $greek = 0
            $badExamples = New-Object System.Collections.Generic.List[object]
            try {
                $reader = New-Object System.IO.StreamReader($path, $utf8, $false)
                try {
                    while (($line = $reader.ReadLine()) -ne $null) {
                        $count++
                        $fields = @($line.Trim() -split '\s+')
                        $fieldCount = if ($file.format -eq 'wltf') { 4 } else { 3 }
                        if ($fields.Count -ne $fieldCount -or -not $fields[0] -or
                            ($file.format -eq 'wltf' -and $fields[3] -notmatch '^\d+$')) {
                            $malformed++
                            if ($badExamples.Count -lt 10) { $badExamples.Add([ordered]@{ line = $count; text = $line }) }
                            continue
                        }
                        if ($fields[0] -match '(?=[\u0370-\u03FF\u1F00-\u1FFF])\p{L}') { $greek++ }
                        $form = $fields[0].Normalize([System.Text.NormalizationForm]::FormC)
                        if ($file.source_path -eq 'glem/list_proiel_perseus_merged_word_lemma_POS_nofreq') {
                            $null = $mergedForms.Add($form)
                        }
                        if ($matchesByForm.ContainsKey($form)) {
                            $matchesByForm[$form].Add([ordered]@{
                                source_path = $relative
                                line = $count
                                form = $fields[0]
                                lemma = $fields[1]
                                tag = $fields[2]
                                frequency = if ($file.format -eq 'wltf') { [int]$fields[3] } else { $null }
                            })
                        }
                    }
                } finally { $reader.Dispose() }
            } catch [System.Text.DecoderFallbackException] {
                Add-Issue 'error' $relative "Invalid UTF-8: $($_.Exception.Message)"
                continue
            }
            if ($malformed -gt 0) { Add-Issue 'warning' $relative "$malformed lines do not match the expected column format." }
            if ($count -eq 0) { Add-Issue 'error' $relative 'Word list is empty.' }
            if ($file.source_path -eq 'glem/list_proiel_perseus_merged_word_lemma_POS_nofreq') {
                $mergedListValid = $fileIntegrity -and $malformed -eq 0 -and $count -gt 0
            }
            $fileResults.Add([ordered]@{
                path = $relative; format = $file.format; lines = $count
                lines_with_greek_form = $greek; malformed_lines = $malformed
                malformed_examples = @($badExamples.ToArray())
            })
        } elseif ($file.format -eq 'xml' -or $file.format -eq 'treebank') {
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

$coverage = $null
$corpusInventoryPath = Join-Path $root 'docs\corpus-inventory.json'
if ($mergedListValid -and $mergedForms.Count -gt 0 -and (Test-Path -LiteralPath $corpusInventoryPath)) {
    $corpusInventory = Get-Content -Raw -Encoding UTF8 $corpusInventoryPath | ConvertFrom-Json
    $editions = @($corpusInventory.files | Where-Object { $_.local_path -match '\.perseus-grc[^.]*\.xml$' })
    $unique = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $uniqueMatched = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $coverageFiles = New-Object System.Collections.Generic.List[object]
    $total = 0; $matched = 0
    foreach ($edition in $editions) {
        $path = Join-Path $root ($edition.local_path.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-GitBlobSha1 $path) -ne $edition.git_blob_sha1) {
            Add-Issue 'warning' $edition.local_path 'Plato edition missing or changed; excluded from coverage measurement.'
            continue
        }
        try {
            $plato = Read-SecureXml $path
        } catch [System.Xml.XmlException] {
            Add-Issue 'warning' $edition.local_path "Invalid XML; excluded from coverage measurement: $($_.Exception.Message)"
            continue
        }
        $ns = New-Object System.Xml.XmlNamespaceManager($plato.NameTable)
        $ns.AddNamespace('tei', 'http://www.tei-c.org/ns/1.0')
        $body = $plato.SelectSingleNode('/tei:TEI/tei:text/tei:body', $ns)
        if (-not $body) {
            Add-Issue 'warning' $edition.local_path 'TEI body missing; excluded from coverage measurement.'
            continue
        }
        $null = $verifiedPlatoPaths.Add($edition.local_path)
        $text = $body.InnerText.Normalize([System.Text.NormalizationForm]::FormC)
        $tokens = [regex]::Matches($text, '(?:(?=[\u0370-\u03FF\u1F00-\u1FFF])\p{L}|\p{M})+')
        $fileMatched = 0
        foreach ($token in $tokens) {
            $form = $token.Value
            $null = $unique.Add($form)
            if ($mergedForms.Contains($form)) {
                $fileMatched++
                $null = $uniqueMatched.Add($form)
            }
        }
        $total += $tokens.Count
        $matched += $fileMatched
        $coverageFiles.Add([ordered]@{ path = $edition.local_path; tokens = $tokens.Count; matched_tokens = $fileMatched })
    }
    $coverage = [ordered]@{
        method = 'NFC and case-sensitive exact matching against the GLEM merged list. Greek-block letters and combining marks are tokenized as runs; apostrophes, punctuation, Latin letters and digits split tokens. This is orthographic overlap, not validated contextual analyses.'
        expected_editions = $editions.Count; measured_editions = $coverageFiles.Count
        complete = ($editions.Count -gt 0 -and $coverageFiles.Count -eq $editions.Count)
        tokens = $total; matched_tokens = $matched
        distinct_forms = $unique.Count; matched_distinct_forms = $uniqueMatched.Count
        editions = @($coverageFiles.ToArray())
    }
} else {
    Add-Issue 'warning' 'docs/corpus-inventory.json' 'Plato coverage unavailable: corpus inventory or a valid GLEM merged list is missing.'
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
    $hits = @($matchesByForm[$key].ToArray())
    $expectedFound = $null
    if ($sample.expected_lemma) {
        $expectedFound = @($hits | Where-Object { $_.lemma.Normalize([System.Text.NormalizationForm]::FormC) -ceq $sample.expected_lemma.Normalize([System.Text.NormalizationForm]::FormC) }).Count -gt 0
        if (-not $expectedFound) { Add-Issue 'error' 'docs/morphology-samples.json' "Expected source mapping not found for $($sample.form)." }
    }
    $treebankHits = @($treebankMatches[$key].ToArray())
    $treebankExpectedFound = $null
    if ($sample.treebank_expected) {
        $treebankExpectedFound = @($treebankHits | Where-Object { $_.lemma.Normalize([System.Text.NormalizationForm]::FormC) -ceq $sample.expected_lemma.Normalize([System.Text.NormalizationForm]::FormC) }).Count -gt 0
        if (-not $treebankExpectedFound) { Add-Issue 'error' 'docs/morphology-samples.json' "Expected Euthyphro treebank mapping not found for $($sample.form)." }
    }
    $sampleResults.Add([ordered]@{
        form = $sample.form; reference = $sample.reference; plato_path = $sample.plato_path
        attested_in_plato = $attested; expected_lemma = $sample.expected_lemma
        expected_lemma_found = $expectedFound
        glem_matches = $hits; euthyphro_treebank_matches = $treebankHits
        expected_treebank_lemma_found = $treebankExpectedFound
    })
}

$errors = @($issues | Where-Object { $_.severity -eq 'error' })
$warnings = @($issues | Where-Object { $_.severity -eq 'warning' })
$manifest = [ordered]@{
    sources = @($inventory.sources | ForEach-Object {
        [ordered]@{ id = $_.id; repository = $_.repository; revision = $_.revision; description = $_.description; license_note = $_.license_note }
    })
    validation_scope = 'Pinned Git blob hashes; strict UTF-8 for text; XML well-formedness; word-list column counts; treebank attribute completeness; exact NFC sample matches and Plato attestation. Not linguistic accuracy, exhaustive coverage or XML schema validation.'
    expected_files = $expected; verified_files = $verified
    word_lists_and_tagset = @($fileResults.ToArray())
    euthyphro_treebank = $treebank
    plato_exact_form_overlap = $coverage
    sample_tests = @($sampleResults.ToArray())
    limitations = @(
        'GLEM lists contain candidate form-lemma-tag associations, not a context-aware analyzer; they do not supply text citations per row and may omit forms or contain ambiguity.',
        'The AGDT selection provides contextual annotations for Euthyphro only, not the full Platonic corpus; its README reports remaining annotation issues.',
        'The corpus-wide exact form overlap is sensitive to case, accents, punctuation, editions and tokenization; a match is not proof of a contextually correct analysis.',
        'GLEM software declares GPL-3.0-only; rights for the derived data and upstream components need clarification before redistribution or commercial use.'
    )
    issues = @($issues.ToArray())
}
$manifest | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 (Join-Path $root 'docs\morphology-manifest.json')
Write-Host "Verified $verified/$expected source files. Validation: $($errors.Count) errors, $($warnings.Count) warnings."
foreach ($issue in $issues) { Write-Host "$($issue.severity): $($issue.path): $($issue.message)" }
foreach ($sample in $sampleResults) {
    Write-Host "$($sample.form): $(@($sample.glem_matches).Count) GLEM matches, $(@($sample.euthyphro_treebank_matches).Count) Euthyphro annotations; Plato attested=$($sample.attested_in_plato)."
}
if ($errors.Count -gt 0) { exit 1 }

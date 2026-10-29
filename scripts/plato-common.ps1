function Get-GitBlobSha1([string] $path) {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    $header = [System.Text.Encoding]::ASCII.GetBytes("blob $($bytes.Length)`0")
    $hash = [System.Security.Cryptography.SHA1]::Create()
    try {
        $null = $hash.TransformBlock($header, 0, $header.Length, $header, 0)
        $null = $hash.TransformFinalBlock($bytes, 0, $bytes.Length)
        return ([BitConverter]::ToString($hash.Hash)).Replace('-', '').ToLowerInvariant()
    } finally {
        $hash.Dispose()
    }
}

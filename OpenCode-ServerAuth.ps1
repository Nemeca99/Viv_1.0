$script:OpenCodePasswordPath = Join-Path $env:LOCALAPPDATA 'LocalCoder\opencode-server-password.dpapi'

function New-OpenCodeServerPassword {
    $directory = Split-Path -Parent $script:OpenCodePasswordPath
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    if (Test-Path -LiteralPath $script:OpenCodePasswordPath) {
        $null = Get-OpenCodeServerPassword
        return
    }

    $random = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($random) }
    finally { $rng.Dispose() }
    $clear = [Convert]::ToBase64String($random)
    [Array]::Clear($random, 0, $random.Length)
    $secure = ConvertTo-SecureString -String $clear -AsPlainText -Force
    $encrypted = ConvertFrom-SecureString -SecureString $secure
    $temporary = "$($script:OpenCodePasswordPath).$([guid]::NewGuid().ToString('N')).tmp"
    [System.IO.File]::WriteAllText($temporary, $encrypted, [System.Text.UTF8Encoding]::new($false))
    try {
        [System.IO.File]::Move($temporary, $script:OpenCodePasswordPath)
    } catch {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path -LiteralPath $script:OpenCodePasswordPath)) { throw }
    }
    $clear = $null
    $secure.Dispose()
    $null = Get-OpenCodeServerPassword
}

function Get-OpenCodeServerPassword {
    if (-not (Test-Path -LiteralPath $script:OpenCodePasswordPath)) {
        throw "OpenCode server password is not initialized. Start the visible server launcher first."
    }
    $encrypted = [System.IO.File]::ReadAllText($script:OpenCodePasswordPath).Trim()
    $secure = ConvertTo-SecureString -String $encrypted
    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
        $secure.Dispose()
    }
}

# localize-framer-images.ps1
# Find all framerusercontent.com image URLs in HTML, download locally, and rewrite the HTML.

param(
    [switch]$DryRun,    # Show actions; don't write files
    [switch]$Recursive  # Include *.html in subfolders
)

# Work from this script's folder
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $Root

# Ensure images folder exists
$ImagesDir = Join-Path $Root "assets\images"
if (-not (Test-Path $ImagesDir)) {
    New-Item -ItemType Directory -Force -Path $ImagesDir | Out-Null
}

# Collect HTML files
if ($Recursive) {
    $HtmlFiles = Get-ChildItem -Path $Root -Filter *.html -File -Recurse
} else {
    $HtmlFiles = Get-ChildItem -Path $Root -Filter *.html -File
}

if (-not $HtmlFiles) {
    Write-Host "No HTML files found." -ForegroundColor Yellow
    exit 0
}

# Regex: framerusercontent.com + image extensions (+ optional ?query)
# IMPORTANT: @' and '@ must be on separate lines with nothing else.
$UrlRegex = @'
(?i)https?://[^"' \s]*framerusercontent\.com[^"' \s]*\.(?:png|jpe?g|webp|gif|svg|ico|avif)(?:\?[^"' \s]*)?
'@

function Get-LocalFilenameFromUrl([string]$Url) {
    try {
        $Uri = [Uri]$Url
        $Base = [System.IO.Path]::GetFileName($Uri.AbsolutePath)
    } catch {
        $Base = ""
    }
    if ([string]::IsNullOrWhiteSpace($Base)) {
        # Fallback: hash as name
        $sha1  = [System.Security.Cryptography.SHA1]::Create()
        $bytes = [Text.Encoding]::UTF8.GetBytes($Url)
        $hash  = ($sha1.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join ""
        return "framer-$($hash.Substring(0,10)).bin"
    }

    # If URL has query params, append a short hash to avoid collisions
    try {
        $Uri = [Uri]$Url
        if ($Uri.Query) {
            $sha1  = [System.Security.Cryptography.SHA1]::Create()
            $bytes = [Text.Encoding]::UTF8.GetBytes($Url)
            $hash  = ($sha1.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join ""
            $name  = [System.IO.Path]::GetFileNameWithoutExtension($Base)
            $ext   = [System.IO.Path]::GetExtension($Base)
            return "$name.$($hash.Substring(0,6))$ext"
        }
    } catch { }

    return $Base
}

foreach ($File in $HtmlFiles) {
    Write-Host "Processing $($File.FullName) ..." -ForegroundColor Cyan

    # Read with auto-encoding and guard against null
    try {
        $Html = Get-Content -Raw -Path $File.FullName
    } catch {
        $Html = $null
    }
    if (-not $Html) {
        Write-Host "  Skipping (couldn’t read or empty): $($File.Name)" -ForegroundColor DarkYellow
        continue
    }

    $Original = $Html
    $Matches  = [regex]::Matches($Html, $UrlRegex)
    if ($Matches.Count -eq 0) {
        Write-Host "  No framerusercontent.com image URLs found." -ForegroundColor DarkGray
        continue
    }

    # De-duplicate URLs
    $Urls = New-Object System.Collections.Generic.HashSet[string]
    foreach ($m in $Matches) { [void]$Urls.Add($m.Value) }

    foreach ($Url in $Urls) {
        $LocalName = Get-LocalFilenameFromUrl $Url
        $LocalRel  = "assets/images/$LocalName"
        $LocalPath = Join-Path $Root $LocalRel

        if ($DryRun) {
            Write-Host "  DRYRUN: would download -> $LocalRel" -ForegroundColor Yellow
        } else {
            if (-not (Test-Path $LocalPath)) {
                try {
                    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $LocalPath -ErrorAction Stop
                    Write-Host "  OK: $Url -> $LocalRel" -ForegroundColor Green
                } catch {
                    Write-Host "  ERROR: failed to download $Url" -ForegroundColor Red
                    continue
                }
            } else {
                Write-Host "  Exists: $LocalRel" -ForegroundColor DarkYellow
            }
        }

        # Replace every occurrence of the remote URL with the local relative path
        $Html = $Html.Replace($Url, $LocalRel)
    }

    if ($Html -ne $Original) {
        if ($DryRun) {
            Write-Host "  DRYRUN: would update HTML: $($File.Name)" -ForegroundColor Yellow
        } else {
            Set-Content -Path $File.FullName -Value $Html -Encoding UTF8
            Write-Host "  Updated: $($File.Name)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  No changes in: $($File.Name)" -ForegroundColor DarkGray
    }
}

Write-Host "Done." -ForegroundColor Green

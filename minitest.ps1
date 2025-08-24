#requires -Version 5.1
<#
Suno MINITEST Runner (ligger i C:\Brittpop, jobbar i minitest\)
#>

$BaseDir = 'C:\Brittpop'
$MiniDir = Join-Path $BaseDir 'minitest'
$RawBase = 'https://raw.githubusercontent.com/goransuperagi/BrittPOP/refs/heads/main'

if (-not (Test-Path -LiteralPath $MiniDir)) {
    New-Item -ItemType Directory -Path $MiniDir | Out-Null
}
Set-Location -LiteralPath $MiniDir

Write-Host "=== Skapar .env med hårdkodade värden ==="
@"
SUNO_API=https://api.suno.example/v1
SUNO_API_KEY=c10f2086b410e1bfb4db5d1bb3136dcf
TIMEOUT_CREATE=30
TIMEOUT_POLL=30
TIMEOUT_DOWNLOAD=180
SUNO_CALLBACK_URL=https://example.com/callback
"@ | Set-Content -LiteralPath ".env" -Encoding UTF8

$env:SUNO_API          = 'https://api.suno.example/v1'
$env:SUNO_API_KEY      = 'c10f2086b410e1bfb4db5d1bb3136dcf'
$env:TIMEOUT_CREATE    = '30'
$env:TIMEOUT_POLL      = '30'
$env:TIMEOUT_DOWNLOAD  = '180'
$env:SUNO_CALLBACK_URL = 'https://example.com/callback'

Write-Host "=== Skriver testprompt: sunoprompt_aktiv.json ==="
@"
{
  "meta": { "default_count": 1 },
  "prompts": [
    {
      "title": "MiniTest Song",
      "prompt": "Uptempo 60s pop-rock; short intro<5s; hook@18s; tambourine + handclaps; bright guitars; positive feel about first day of school.",
      "count": 1
    }
  ]
}
"@ | Set-Content -LiteralPath 'sunoprompt_aktiv.json' -Encoding UTF8

function Ensure-File($Name) {
    if (-not (Test-Path -LiteralPath $Name)) {
        $url = "$RawBase/$Name"
        Write-Host "Hämtar $Name från $url"
        Invoke-WebRequest -Uri $url -OutFile $Name
    }
}

Ensure-File -Name 'create_songs.py'
Ensure-File -Name 'poll_songs.py'

Write-Host "`n=== KÖR: create_songs.py ==="
$process = Start-Process -FilePath "python" -ArgumentList "create_songs.py" -NoNewWindow -PassThru -Wait
if ($process.ExitCode -ne 0) {
    Write-Host "[FEL] create_songs.py misslyckades. Se log.txt" -ForegroundColor Red
    Read-Host "Tryck Enter för att stänga"
    exit 1
}

Write-Host "`n=== KÖR: poll_songs.py ==="
$process = Start-Process -FilePath "python" -ArgumentList "poll_songs.py" -NoNewWindow -PassThru -Wait
if ($process.ExitCode -ne 0) {
    Write-Host "[FEL] poll_songs.py misslyckades. Se log.txt" -ForegroundColor Red
    Read-Host "Tryck Enter för att stänga"
    exit 1
}

Write-Host "`n=== KLART ===" -ForegroundColor Green
Write-Host "Kontrollera MP3-filer i: $MiniDir\out"
Read-Host "Tryck Enter för att stänga"
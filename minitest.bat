@echo off
REM === Suno MINITEST Runner (ligger i C:\Brittpop, jobbar i minitest\) ===
setlocal enabledelayedexpansion

set "BASEDIR=C:\Brittpop"
set "MINIDIR=%BASEDIR%\minitest"
set "RAWBASE=https://raw.githubusercontent.com/goransuperagi/BrittPOP/refs/heads/main"

if not exist "%MINIDIR%" mkdir "%MINIDIR%"
cd /d "%MINIDIR%"

echo === Skapar .env med hårdkodade värden ===
> ".env" echo SUNO_API=https://api.suno.example/v1
>> ".env" echo SUNO_API_KEY=c10f2086b410e1bfb4db5d1bb3136dcf
>> ".env" echo TIMEOUT_CREATE=30
>> ".env" echo TIMEOUT_POLL=30
>> ".env" echo TIMEOUT_DOWNLOAD=180
>> ".env" echo SUNO_CALLBACK_URL=https://example.com/callback

set "SUNO_API=https://api.suno.example/v1"
set "SUNO_API_KEY=c10f2086b410e1bfb4db5d1bb3136dcf"
set "TIMEOUT_CREATE=30"
set "TIMEOUT_POLL=30"
set "TIMEOUT_DOWNLOAD=180"
set "SUNO_CALLBACK_URL=https://example.com/callback"

echo === Skriver testprompt: sunoprompt_aktiv.json ===
powershell -NoProfile -Command ^
"@'
{
  ""meta"": { ""default_count"": 1 },
  ""prompts"": [
    {
      ""title"": ""MiniTest Song"",
      ""prompt"": ""Uptempo 60s pop-rock; short intro<5s; hook@18s; tambourine + handclaps; bright guitars; positive feel about first day of school."",
      ""count"": 1
    }
  ]
}
'@ | Set-Content -Path 'sunoprompt_aktiv.json' -Encoding UTF8"

echo === Säkerställer Python-skript (hämtar om saknas) ===
if not exist "create_songs.py" (
  echo Hämtar create_songs.py
  powershell -NoProfile -Command "Invoke-WebRequest '%RAWBASE%/create_songs.py' -OutFile 'create_songs.py'"
)
if not exist "poll_songs.py" (
  echo Hämtar poll_songs.py
  powershell -NoProfile -Command "Invoke-WebRequest '%RAWBASE%/poll_songs.py' -OutFile 'poll_songs.py'"
)

echo.
echo === KÖR: create_songs.py ===
python create_songs.py
if errorlevel 1 (
  echo [FEL] create_songs.py misslyckades. Se log.txt
  pause
  exit /b 1
)

echo.
echo === KÖR: poll_songs.py ===
python poll_songs.py
if errorlevel 1 (
  echo [FEL] poll_songs.py misslyckades. Se log.txt
  pause
  exit /b 1
)

echo.
echo === KLART ===
echo Kontrollera MP3-filer i: %MINIDIR%\out
pause

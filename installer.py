# =========================================
# Britt-POP × Suno – Minimal installer
# Laddar själv ner körskript och gör bara nödvändigt setup.
# =========================================
# Varför detta?
#
# All nedladdning nu i installer.py (inte i PowerShell-blocket) ✅.
# 
# installer.py skapar inte extrakod (som tidigare version gjorde), utan bara .env + out\ + hämtar de två körskripten. 
# Dina befintliga skript create_songs.py och poll_songs.py används sedan som tänkt.
#========================================

import os, sys, pathlib, subprocess
from urllib.request import urlopen

ROOT = pathlib.Path.cwd().resolve()
RAW  = "https://raw.githubusercontent.com/goransuperagi/BrittPOP/main"
FILES = ["create_songs.py", "poll_songs.py"]  # lägg till fler här om du senare vill

print("┌─────────────────────────────┐")
print("│  HumanoidGPT Britt-POP      │")
print(f"│  Installerar i: {ROOT}")
print("├─────────────────────────────┤")

# 1) Mappar
(ROOT / "out").mkdir(parents=True, exist_ok=True)

# 2) .env & API-key (behövs för API-anrop)
env_example = (
    "SUNO_API=https://api.suno.example/v1\n"
    "SUNO_API_KEY=\n"
    "TIMEOUT_CREATE=30\n"
    "TIMEOUT_POLL=30\n"
    "TIMEOUT_DOWNLOAD=180\n"
)
env_example_path = ROOT / ".env.example"
env_path = ROOT / ".env"
env_example_path.write_text(env_example, encoding="utf-8")
if not env_path.exists():
    print("\nKlistra in din SUNO API KEY (utan citattecken) och tryck Enter:")
    try:
        api = input().strip()
    except EOFError:
        api = ""
    env = env_example.replace("SUNO_API_KEY=", f"SUNO_API_KEY={api}")
    env_path.write_text(env, encoding="utf-8")
    print("✓ .env skapad.")
else:
    print("• .env finns redan – hoppar över.")

# 3) Hämta körskript från GitHub
def fetch(name: str):
    url = f"{RAW}/{name}"
    dst = ROOT / name
    with urlopen(url) as r:
        dst.write_bytes(r.read())
    print(f"✓ Hämtad: {name}")

for f in FILES:
    try:
        fetch(f)
    except Exception as e:
        print(f"! Misslyckades hämta {f}: {e}")

# 4) Installera minimala Python-beroenden
try:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], shell=False)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "python-dotenv", "tqdm"], shell=False)
    print("✓ Pythonpaket installerade.")
except Exception as e:
    print("! Varning: paketinstallation misslyckades:", e)

# 5) Summering + nästa steg
print("├─────────────────────────────┤")
for name in [".env", ".env.example", "create_songs.py", "poll_songs.py", "out\\"]:
    print(f"• {name}")
print("└─────────────────────────────┘\n")

print("Nästa steg:")
print(r"  1) Skapa din JSON: sunoprompt-aktiv.json (eller använd Single-exemplet i GPT).")
print(r"  2) python create_songs.py")
print(r"  3) python poll_songs.py")
print("Installation klar.")

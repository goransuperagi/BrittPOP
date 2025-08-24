#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, json, shutil, subprocess
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent            # C:\Brittpop
TEST = BASE / "minitest"                          # C:\Brittpop\minitest
TEST.mkdir(parents=True, exist_ok=True)

def cp(src_name: str):
    src = BASE / src_name
    dst = TEST / src_name
    if not src.exists():
        print(f"❌ Hittar inte {src_name} i {BASE}. Lägg filen där.")
        sys.exit(1)
    shutil.copy2(src, dst)

# 1) Kopiera in beroenden (.env, create_songs.py, poll_songs.py)
if (BASE / ".env").exists():
    shutil.copy2(BASE / ".env", TEST / ".env")
cp("create_songs.py")
cp("poll_songs.py")

# 2) Skriv minimal prompt-JSON
prompt = {
    "meta": {"created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "default_count": 1},
    "prompts": [
        {
            "title": "Test Jingle",
            "prompt": "10s upbeat catchy jingle with whistling, simple beat, clean mix",
            "count": 1
        }
    ]
}
with open(TEST / "sunoprompt_aktiv.json", "w", encoding="utf-8") as f:
    json.dump(prompt, f, indent=2)

print(f"Testmiljö skapad i mapp: {TEST}")
print("Startar create_songs.py för testprompten...")

# 3) Kör create i undermappen
try:
    subprocess.run([sys.executable, "create_songs.py"], cwd=str(TEST), check=True)
    print("✅ create_songs.py körd utan fel.")
except subprocess.CalledProcessError as e:
    print(f"✗ create_songs.py misslyckades i testmiljön: {e}")
    sys.exit(2)

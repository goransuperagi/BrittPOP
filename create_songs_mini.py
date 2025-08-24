#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mini-create för pipeline-test:
• Skapar C:\Brittpop\minitest
• Kopierar .env, create_songs.py, poll_songs.py
• Sätter SUNO_API_URL om saknas (old-docs endpoint)
• Skriver minimal sunoprompt_aktiv.json (10s-jingle)
• Kör create_songs.py i undermappen
"""
import os, sys, json, shutil, subprocess
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent            # C:\Brittpop
TEST = BASE / "minitest"                          # C:\Brittpop\minitest
TEST.mkdir(parents=True, exist_ok=True)

def cp_required(name: str):
    src = BASE / name
    dst = TEST / name
    if not src.exists():
        print(f"❌ Hittar inte {name} i {BASE}. Lägg filen där.")
        sys.exit(1)
    shutil.copy2(src, dst)

# 1) Kopiera in beroenden
if (BASE / ".env").exists():
    shutil.copy2(BASE / ".env", TEST / ".env")

cp_required("create_songs.py")
cp_required("poll_songs.py")

# 2) Säkerställ SUNO_API_URL i .env (old-docs endpoint)
env_path = TEST / ".env"
lines = []
if env_path.exists():
    lines = env_path.read_text(encoding="utf-8").splitlines()
else:
    lines = []

def set_kv(lines, key, value):
    found = False
    for i, ln in enumerate(lines):
        if ln.strip().startswith(key + "="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    return lines

# Sätt endpoint om saknas / tom
current_env = "\n".join(lines)
if "SUNO_API_URL=" not in current_env or current_env.strip().endswith("SUNO_API_URL="):
    lines = set_kv(lines, "SUNO_API_URL", "https://api.sunoapi.org/api/v1")
# Bra default-modell för pro-konton (kan ändras i .env i basmappen)
if "SUNO_MODEL=" not in current_env:
    lines = set_kv(lines, "SUNO_MODEL", "V4_5")

env_path.write_text("\n".join(lines) + ("\n" if lines and not lines[-1].endswith("\n") else ""), encoding="utf-8")

# 3) Skriv en minimal prompt-JSON (10s-jingle)
prompt = {
    "meta": {"created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "default_count": 1},
    "prompts": [
        {
            "title": "Test Jingle",
            "prompt": "10s upbeat catchy jingle with whistling, simple beat, clean mix",
            "params": "instrumental=true|length=8-12s",
            "count": 1
        }
    ]
}
(P := TEST / "sunoprompt_aktiv.json").write_text(json.dumps(prompt, indent=2), encoding="utf-8")

print(f"🧪 Testmiljö: {TEST}")
print(f"⚙️  Endpoint: {(TEST / '.env').read_text(encoding='utf-8').splitlines()} (maskerad nyckel ej utskriven)")
print("▶ Kör create_songs.py …")

# 4) Kör create i undermappen
try:
    subprocess.run([sys.executable, "create_songs.py"], cwd=str(TEST), check=True)
    print("✅ create_songs.py körd utan fel.")
except subprocess.CalledProcessError as e:
    print(f"✗ create_songs.py misslyckades i testmiljön: {e}")
    sys.exit(2)

print("ℹ️ Kör därefter:  python .\\poll_songs_mini.py")

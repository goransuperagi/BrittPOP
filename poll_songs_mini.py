#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, shutil, subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent            # C:\Brittpop
TEST = BASE / "minitest"                          # C:\Brittpop\minitest

if not TEST.exists():
    print("❌ Ingen testmapp hittad. Kör create_songs_mini.py först.")
    sys.exit(1)

# Säkerställ att skripten finns i undermappen (kopiera vid behov)
def ensure(name: str):
    if not (TEST / name).exists():
        src = BASE / name
        if not src.exists():
            print(f"❌ Hittar inte {name} i {BASE}. Lägg filen där.")
            sys.exit(1)
        shutil.copy2(src, TEST / name)

ensure("poll_songs.py")
ensure("create_songs.py")  # inte strikt nödvändig, men bra för kompletthet

print("Startar en ny polling-omgång i testmiljön...")
try:
    subprocess.run([sys.executable, "poll_songs.py"], cwd=str(TEST), check=True)
    print("✅ Polling klar. MP3 borde ligga i minitest\\out\\")
except subprocess.CalledProcessError as e:
    print(f"✗ poll_songs.py misslyckades under test: {e}")
    sys.exit(2)

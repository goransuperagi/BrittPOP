#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mini-poll för pipeline-test:
• Säkrar att skripten finns i C:\Brittpop\minitest
• Kör poll_songs.py i undermappen
• Spelar upp senaste MP3 på Windows
"""
import os, sys, shutil, subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
TEST = BASE / "minitest"

if not TEST.exists():
    print("❌ Ingen testmapp hittad. Kör create_songs_mini.py först.")
    sys.exit(1)

def ensure_in_test(name: str):
    if not (TEST / name).exists():
        src = BASE / name
        if not src.exists():
            print(f"❌ Hittar inte {name} i {BASE}. Lägg filen där.")
            sys.exit(1)
        shutil.copy2(src, TEST / name)

ensure_in_test("poll_songs.py")
ensure_in_test("create_songs.py")

print("▶ Startar polling i testmiljön …")
try:
    subprocess.run([sys.executable, "poll_songs.py"], cwd=str(TEST), check=True)
    print("✅ poll_songs.py klar.")
except subprocess.CalledProcessError as e:
    print(f"✗ poll_songs.py misslyckades under test: {e}")
    sys.exit(2)

# Spela upp senaste MP3 (Windows)
out_dir = TEST / "out"
if out_dir.exists():
    mp3s = sorted([p for p in out_dir.glob("*.mp3")], key=lambda p: p.stat().st_mtime, reverse=True)
    if mp3s:
        latest = mp3s[0]
        print(f"🎵 Spelar upp: {latest}")
        try:
            if os.name == "nt":
                os.startfile(str(latest))
        except Exception as e:
            print(f"⚠️ Kunde inte spela upp automatiskt: {e}")
    else:
        print("ℹ️ Ingen MP3 hittad i minitest\\out ännu.")
else:
    print("ℹ️ Mappen minitest\\out saknas.")

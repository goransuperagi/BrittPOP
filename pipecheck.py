#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipecheck.py — Enkel end-to-end-test för Suno-pipelinen på Windows.
Skapar testprompt i C:\Brittpop\pipecheck, kör create → poll och verifierar MP3.
"""

import os, sys, json, time, subprocess, glob

# Fast arbetsmapp
PIPE_DIR = r"C:\Brittpop\pipecheck"
PROMPT_FILE = os.path.join(PIPE_DIR, "sunoprompt_aktiv.json")

def ensure_dir():
    if not os.path.isdir(PIPE_DIR):
        os.makedirs(PIPE_DIR, exist_ok=True)
    os.chdir(PIPE_DIR)

def have_env_key():
    if "SUNO_API_KEY" in os.environ and os.environ["SUNO_API_KEY"].strip():
        return True
    # enkel .env läsning
    env_path = os.path.join(PIPE_DIR, ".env")
    if os.path.isfile(env_path):
        with open(env_path,"r",encoding="utf-8") as f:
            for line in f:
                line=line.strip()
                if not line or line.startswith("#"): 
                    continue
                if line.startswith("SUNO_API_KEY"):
                    k,v = line.split("=",1)
                    if v.strip():
                        return True
    return False

def write_test_prompt():
    data = {
        "meta": {"default_count": 1},
        "prompts": [
            {
                "title": "Test Song",
                "prompt": "Upbeat 60s pop-rock; short intro; catchy chorus; tambourine and handclaps; positive lyrics about sunny days.",
                "count": 1
            }
        ]
    }
    with open(PROMPT_FILE,"w",encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def run_py(cmd):
    print(f"\n=== Kör: {cmd} ===")
    p = subprocess.Popen([sys.executable, cmd], cwd=PIPE_DIR,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    while True:
        line = p.stdout.readline()
        if not line and p.poll() is not None:
            break
        if line:
            print(line.rstrip())
    return p.returncode

def main():
    ensure_dir()
    print(f"== Suno pipeline test i {PIPE_DIR} ==")
    if not have_env_key():
        print("🚫 SUNO_API_KEY saknas. Lägg den i .env i C:\\Brittpop\\pipecheck och kör igen.")
        sys.exit(1)

    # Skriv testprompt
    write_test_prompt()
    print(f"✓ Skrev {PROMPT_FILE}")

    # Kör create
    rc = run_py("create_songs.py")
    if rc != 0:
        print(f"✗ create_songs.py returnerade {rc}. Avbryter test.")
        sys.exit(rc)

    time.sleep(3)

    # Kör poll
    rc = run_py("poll_songs.py")
    if rc != 0:
        print(f"✗ poll_songs.py returnerade {rc}. Avbryter test.")
        sys.exit(rc)

    # Verifiera minst en MP3
    mp3s = glob.glob(os.path.join(PIPE_DIR, "out", "*.mp3"))
    if not mp3s:
        print("✗ Test misslyckades: Ingen MP3 hittades i out/")
        sys.exit(2)

    print(f"✓ Test OK. Hittade {len(mp3s)} MP3 i out/")
    sys.exit(0)

if __name__ == "__main__":
    main()

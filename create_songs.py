#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create-songs.py — ALL-IN-ONE (no installer)
- Default-folder: C:\Brittpop (override: --folder)
- Ensures folder/.env, asks for SUNO_API_KEY if missing
- Ensures packages (requests, python-dotenv)
- Fetches poll_songs.py from GitHub if missing
- Writes default prompt JSON if missing
- Calls Suno API /generate, writes jobid_aktiv.json, archives snapshots
- API KEY =
c10f2086b410e1bfb4db5d1bb3136dcf 
"""

import os, sys, json, time, re, random, argparse, subprocess, pathlib, urllib.request, shutil
from datetime import datetime as dt
from pathlib import Path

# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_FOLDER = Path("C:/Brittpop")
RAW_BASE = "https://raw.githubusercontent.com/goransuperagi/BrittPOP/{ref}/"
REMOTE_POLL = "poll_songs.py"

PROMPT_FILE_ACTIVE = "sunoprompt_aktiv.json"
JOBID_FILE_ACTIVE  = "jobid_aktiv.json"

DEFAULTS_ENV = {
    "SUNO_API_URL": "https://api.suno.ai/v1",
    "SUNO_API_KEY": "",
    "TIMEOUT_CREATE": "60",
}

RETRYABLE = {429, 430, 455, 500, 502, 503, 504}
ERROR_EXPL = {
    400:"Ogiltiga parametrar.",
    401:"Obehörig – fel/avsaknad SUNO_API_KEY.",
    404:"Fel endpoint-URL.",
    413:"Prompt för lång.",
    429:"Rate-limit/slut på krediter.",
    430:"För hög anropsfrekvens.",
    455:"Underhållsläge.",
    500:"Serverfel.",
    502:"Gateway-fel.",
    503:"Tjänsten tillfälligt nere.",
    504:"Gateway timeout."
}

# ── Utils ────────────────────────────────────────────────────────────────
def ts(): return dt.utcnow().strftime("%Y%m%d-%H%M%S")
def now_iso(): return dt.utcnow().replace(microsecond=0).isoformat()+"Z"

def ensure_folder(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    os.chdir(folder)

def have_module(name: str) -> bool:
    try: __import__(name); return True
    except Exception: return False

def ensure_packages():
    missing = []
    if not have_module("requests"): missing.append("requests")
    if not have_module("dotenv"):   missing.append("python-dotenv")
    if not missing: return
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], shell=False)
    except Exception: pass
    for pkg in missing:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg], shell=False)
            print(f"✓ Installerat: {pkg}")
        except Exception as e:
            print(f"! Kunde inte installera {pkg}: {e}")

def load_env_file(env_path: Path):
    env = DEFAULTS_ENV.copy()
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k,v=line.split("=",1); env[k.strip()] = v.strip()
    return env

def save_env_file(env_path: Path, env: dict):
    lines = [f"{k}={env.get(k,'')}" for k in DEFAULTS_ENV.keys()]
    env_path.write_text("\n".join(lines)+"\n", encoding="utf-8")

def fetch_raw(ref: str, remote_name: str, dest_path: Path):
    url = (RAW_BASE.format(ref=ref).rstrip("/") + "/" + remote_name)
    tmp = dest_path.with_suffix(dest_path.suffix + ".tmp")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dest_path)
    print(f"✓ Hämtad: {dest_path.name}")

def default_prompt_json() -> dict:
    return {
      "meta": { "default_count": 1 },
      "prompts": [
        {
          "title": "She Said Yeah",
          "prompt": "Uptempo 60s Merseybeat; VCVCB; intro<5s; hook@18s; 120 BPM; key G; jangly gtrs, tambourine, handclaps, melodic bass, piano stabs, girl-group ooh/ahh; warm analog mono; lyrics about young love; chorus title line 1.",
          "params": "form=VCVCB|intro_max=5s|hook=15-22s|bpm=118-122|key=G|length=150-170s",
          "count": 1
        }
      ]
    }

def write_json(path: Path, obj: dict):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> dict:
    # Acceptera UTF-8 med eller utan BOM (PS Out-File -Encoding UTF8 lägger BOM)
    return json.loads(path.read_text(encoding="utf-8-sig"))



def backoff_delay(attempt, base=1.5, cap=30.0, jitter=0.5):
    import random
    d = min(cap, base * (2 ** attempt))
    return max(0.0, d + random.uniform(-jitter, jitter))

def upsert(items, rec, keys=("index","variant")):
    for it in items:
        if all(it.get(k)==rec.get(k) for k in keys):
            it.update(rec); it["last_update"]=now_iso(); return
    rec["last_update"]=now_iso(); items.append(rec)

def save_status(jobfile: Path, meta, items):
    jobfile.write_text(json.dumps({"meta":meta,"items":items}, indent=2, ensure_ascii=False), encoding="utf-8")

# ── Main ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Britt-POP × Suno – create-songs.py (all-in-one)")
    ap.add_argument("--folder", default=str(DEFAULT_FOLDER), help="Arbetsmapp (default: C:/Brittpop)")
    ap.add_argument("--api-key", default=None, help="Suno API key (överskuggar .env)")
    ap.add_argument("--api-url", default=None, help="Suno API base URL (default: https://api.suno.ai/v1)")
    ap.add_argument("--json", default=PROMPT_FILE_ACTIVE, help="Prompt-JSON (default: sunoprompt_aktiv.json)")
    ap.add_argument("--ref", default="main", help="GitHub ref för hämtning av poll_songs.py (default: main)")
    args = ap.parse_args()

    folder = Path(args.folder)
    ensure_folder(folder)
    Path("out").mkdir(parents=True, exist_ok=True)

    # Paket
    ensure_packages()

    # .env
    from dotenv import load_dotenv
    env_path = Path(".env")
    env = load_env_file(env_path)
    if args.api_url: env["SUNO_API_URL"] = args.api_url.strip()
    key = args.api_key or os.getenv("SUNO_API_KEY") or env.get("SUNO_API_KEY","")
    if not key:
        try:
            key = input("Ange din SUNO_API_KEY: ").strip()
        except KeyboardInterrupt:
            print("\nAvbrutet."); sys.exit(1)
    env["SUNO_API_KEY"] = key
    save_env_file(env_path, env)
    load_dotenv(dotenv_path=env_path)

    # poll_songs.py
    poll_path = Path("poll_songs.py")
    if not poll_path.exists():
        try:
            fetch_raw(args.ref, REMOTE_POLL, poll_path)
        except Exception as e:
            print(f"! Kunde inte hämta {REMOTE_POLL}: {e}")

    # prompt JSON
    prompt_path = Path(args.json)
    if not prompt_path.exists():
        write_json(prompt_path, default_prompt_json())
        print(f"✓ Skapade exempelprompt → {prompt_path}")

    # Läs prompt
    data = read_json(prompt_path)
    prompts = data.get("prompts", [])
    if not prompts:
        print("✖ Inga prompts i JSON."); sys.exit(2)

    # ENV → variabler
    API_KEY = os.getenv("SUNO_API_KEY")
    if not API_KEY:
        print("✖ SUNO_API_KEY saknas i .env – avbryter."); sys.exit(2)
    base_url = (os.getenv("SUNO_API_URL") or DEFAULTS_ENV["SUNO_API_URL"]).rstrip("/")
    GENERATE_URL = base_url + ("/generate" if not base_url.endswith("/generate") else "")

    # HTTP-klient
    import requests
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    default_count = int(data.get("meta",{}).get("default_count",1))
    items=[]; meta={"created_at":now_iso(),"overall_status":"CREATING",
                    "note":"Skapar jobb och skriver status live (jobid_aktiv.json)."}
    save_status(Path(JOBID_FILE_ACTIVE), meta, items)

    total = sum(int(it.get("count", default_count)) for it in prompts)
    created = 0

    print("┌─────────────────────────────────────┐")
    print("│ create-songs.py – Britt-POP × Suno │")
    print("└─────────────────────────────────────┘")
    print(f"• Folder : {folder}")
    print(f"• Endpoint: {GENERATE_URL}")
    print(f"• Prompts : {prompt_path} (tot {total} render(s))\n")

    for idx, it in enumerate(prompts, start=1):
        title  = it.get("title") or f"Prompt_{idx}"
        one    = (it.get("prompt") or "").strip()
        params = (it.get("params") or "").strip()
        count  = int(it.get("count", default_count))
        if not one:
            print(f"  ! Hoppar [{idx}] (saknar prompt)"); 
            continue

        prompt_text = f"{one} || {params}" if params else one

        for var in range(1, count+1):
            rec={"index":idx,"variant":var,"title":title,"prompt_text":prompt_text,
                 "phase":"CREATE","status":"CREATING","http_status":None,"retries":0}
            upsert(items, rec); save_status(Path(JOBID_FILE_ACTIVE), meta, items)

            payload={"prompt":prompt_text}

            for attempt in range(0, 7):
                try:
                    r = requests.post(GENERATE_URL, headers=headers, json=payload, timeout=60)
                    rec["http_status"]=r.status_code
                    if r.status_code == 200:
                        job_id = (r.json() or {}).get("job_id")
                        if job_id:
                            rec.update({"job_id":job_id,"status":"QUEUED"})
                            created += 1
                            print(f"  ✓ [{created}/{total}] Skapade job {job_id}  ({title} v{var})")
                            break
                        else:
                            rec.update({"status":"CREATE_FAILED","error_expl":"Svar saknar job_id"})
                            print("  ! Svar saknar job_id"); break

                    elif r.status_code in RETRYABLE:
                        rec["status"]="RETRYING"
                        rec["error_expl"]=ERROR_EXPL.get(r.status_code,"Tillfälligt fel – försöker igen.")
                        wait = backoff_delay(attempt)
                        print(f"  … HTTP {r.status_code} – {rec['error_expl']} – retry om {wait:.1f}s")
                        upsert(items, rec); save_status(Path(JOBID_FILE_ACTIVE), meta, items)
                        time.sleep(wait); continue

                    else:
                        rec.update({"status":"CREATE_FAILED",
                                    "error_expl":ERROR_EXPL.get(r.status_code,f"Okänt fel ({r.status_code})")})
                        print(f"  ✖ HTTP {r.status_code}: {r.text[:200]}")
                        break

                except Exception as e:
                    rec["status"]="RETRYING"
                    rec["error_expl"]=f"Nätverksfel: {e}"
                    wait = backoff_delay(attempt)
                    print(f"  ✖ Nätverksfel: {e} – retry om {wait:.1f}s")
                    upsert(items, rec); save_status(Path(JOBID_FILE_ACTIVE), meta, items)
                    time.sleep(wait); continue

                finally:
                    upsert(items, rec); save_status(Path(JOBID_FILE_ACTIVE), meta, items)

            if rec.get("status") != "QUEUED":
                print(f"  ! Kunde inte starta ({title} v{var}). Status: {rec.get('status')}")
            time.sleep(0.15)

    # Arkivera
    try:
        Path(f"sp_{ts()}.json").write_text(Path(PROMPT_FILE_ACTIVE).read_text(encoding="utf-8"), encoding="utf-8")
        print(f"\n✓ Arkiverade prompts")
    except Exception as e:
        print("! Kunde inte arkivera prompts:", e)
    try:
        Path(f"jobid_{ts()}.json").write_text(Path(JOBID_FILE_ACTIVE).read_text(encoding="utf-8"), encoding="utf-8")
        print(f"✓ Arkiverade job IDs")
    except Exception as e:
        print("! Kunde inte arkivera job IDs:", e)

    meta["overall_status"]="READY_TO_POLL"; save_status(Path(JOBID_FILE_ACTIVE), meta, items)
    print("\nInfo:")
    print(f"  • {created}/{total} jobb skapade.")
    print("  • Kör:  python .\\poll_songs.py   (hämtar MP3 till .\\out\\)")
    print("  • Live: jobid_aktiv.json")
    print("\nKlart. ✨")

if __name__ == "__main__":
    main()

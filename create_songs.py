#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_songs.py — 100% Golden Path (Suno old‑docs)
• Base URL: https://api.sunoapi.org/api/v1  (override with --api-url or .env)
• Non‑custom payload: {"prompt": "...", "customMode": false}
• Headers include Accept: application/json
• Robust job-id parse: supports job_id / taskId / task_id in root or nested under data/response/sunoData
• Detects API body errors where HTTP=200 but body {code!=0, message}
• Backoff on 429/430/455/5xx; archives snapshots; writes jobid_aktiv.json (for poller)
• Creates default 10‑second instrumental smoke prompt if none exists
"""

from __future__ import annotations
import os, sys, json, time, argparse, subprocess, urllib.request, shutil
from pathlib import Path
from datetime import datetime as dt

# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_FOLDER = Path("C:/Brittpop")
PROMPT_FILE = "sunoprompt_aktiv.json"
JOB_FILE    = "jobid_aktiv.json"
DEFAULT_BASE = "https://api.sunoapi.org/api/v1"
RAW_BASE = "https://raw.githubusercontent.com/goransuperagi/BrittPOP/{ref}/"
REMOTE_POLL = "poll_songs.py"
RETRYABLE = {429,430,455,500,502,503,504}

DEFAULTS_ENV = {
    "SUNO_API_URL": DEFAULT_BASE,
    "SUNO_API_KEY": "",
    "TIMEOUT_CREATE": "60",
}

# ── Helpers ──────────────────────────────────────────────────────────────
def ts(): return dt.utcnow().strftime("%Y%m%d-%H%M%S")

def now_iso(): return dt.utcnow().replace(microsecond=0).isoformat()+"Z"

def ensure_folder(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    os.chdir(d)

def have_module(name: str) -> bool:
    try: __import__(name); return True
    except Exception: return False

def ensure_packages():
    missing=[]
    if not have_module("requests"): missing.append("requests")
    if not have_module("dotenv"):   missing.append("python-dotenv")
    if not missing: return
    try: subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], shell=False)
    except Exception: pass
    for pkg in missing:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg], shell=False)
            print(f"✓ Installerat: {pkg}")
        except Exception as e:
            print(f"! Kunde inte installera {pkg}: {e}")

def load_env_file(p: Path):
    env = DEFAULTS_ENV.copy()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k,v=line.split("=",1); env[k.strip()]=v.strip()
    return env

def save_env_file(p: Path, env: dict):
    p.write_text("\n".join([f"{k}={env.get(k,'')}" for k in DEFAULTS_ENV])+"\n", encoding="utf-8")

def write_json(path: Path, obj: dict):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))

def backoff_delay(attempt, base=1.5, cap=30.0, jitter=0.5):
    import random
    d=min(cap, base*(2**attempt)); return max(0.2, d+random.uniform(-jitter,jitter))

def upsert(items, rec, keys=("index","variant")):
    for it in items:
        if all(it.get(k)==rec.get(k) for k in keys):
            it.update(rec); it["last_update"]=now_iso(); return
    rec["last_update"]=now_iso(); items.append(rec)

def save_status(jobfile: Path, meta, items):
    jobfile.write_text(json.dumps({"meta":meta,"items":items}, indent=2, ensure_ascii=False), encoding="utf-8")

# Robust job id extractor
def extract_job_id(js: dict):
    if not isinstance(js, dict):
        return None
    # direct keys
    for k in ("job_id","taskId","task_id","id"):
        v = js.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # common nests
    for nest in ("data","response","result","payload","record","job","task"):
        sub = js.get(nest)
        if isinstance(sub, dict):
            rid = extract_job_id(sub)
            if rid: return rid
    # lists under known containers
    for nest in ("data","response","sunoData","records","items"):
        sub = js.get(nest)
        if isinstance(sub, list):
            for el in sub:
                if isinstance(el, dict):
                    rid = extract_job_id(el)
                    if rid: return rid
    return None

# Default smoke prompt
DEFAULT_PROMPT = {
  "meta": { "default_count": 1 },
  "prompts": [
    {"title":"SMOKE_MIN","prompt":"10s minimal instrumental jingle, steady beat, clean mix","params":"","count":1}
  ]
}

# ── Main ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="create_songs.py — 100% Golden Path (Suno old‑docs)")
    ap.add_argument("--folder", default=str(DEFAULT_FOLDER), help="Arbetsmapp (default: C:/Brittpop)")
    ap.add_argument("--api-key", default=None, help="Suno API key (överskuggar .env)")
    ap.add_argument("--api-url", default=None, help="Suno API base (default: https://api.sunoapi.org/api/v1)")
    ap.add_argument("--json", default=PROMPT_FILE, help="Prompt-JSON (default: sunoprompt_aktiv.json)")
    ap.add_argument("--ref", default="main", help="GitHub ref för att hämta poll_songs.py om saknas")
    ap.add_argument("--debug", action="store_true", help="Skriv ut 400 tecken av svar vid parse-/API-fel")
    args = ap.parse_args()

    ensure_folder(Path(args.folder))
    Path("out").mkdir(parents=True, exist_ok=True)

    ensure_packages()

    # .env
    env_path = Path(".env")
    env = load_env_file(env_path)
    if args.api_url: env["SUNO_API_URL"] = args.api_url.strip()
    key = args.api_key or os.getenv("SUNO_API_KEY") or env.get("SUNO_API_KEY","")
    if not key:
        try: key = input("Ange din SUNO_API_KEY: ").strip()
        except KeyboardInterrupt: print(); sys.exit(1)
    env["SUNO_API_KEY"] = key; save_env_file(env_path, env)

    # poll_songs.py
    poll_path = Path("poll_songs.py")
    if not poll_path.exists():
        try:
            url = (RAW_BASE.format(ref=args.ref).rstrip("/") + "/" + REMOTE_POLL)
            tmp = poll_path.with_suffix(".tmp")
            with urllib.request.urlopen(url) as r, open(tmp, "wb") as f: shutil.copyfileobj(r,f)
            tmp.replace(poll_path); print("✓ Hämtad: poll_songs.py")
        except Exception as e:
            print(f"! Kunde inte hämta poll_songs.py: {e}")

    # Prompt JSON
    prompt_path = Path(args.json)
    if not prompt_path.exists():
        write_json(prompt_path, DEFAULT_PROMPT)
        print(f"✓ Skapade exempelprompt → {prompt_path}")
    data = read_json(prompt_path)
    prompts = data.get("prompts", [])
    if not prompts:
        print("✖ Inga prompts i JSON."); sys.exit(2)

    # ENV → vars
    API_KEY = env.get("SUNO_API_KEY")
    base = (env.get("SUNO_API_URL") or DEFAULT_BASE).rstrip("/")
    GENERATE_URL = base + ("/generate" if not base.endswith("/generate") else "")

    # HTTP
    import requests
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type":"application/json", "Accept":"application/json"}

    default_count = int(data.get("meta",{}).get("default_count",1))
    items=[]; meta={"created_at":now_iso(),"overall_status":"CREATING","endpoint":GENERATE_URL}
    save_status(Path(JOB_FILE), meta, items)

    total = sum(int(it.get("count", default_count)) for it in prompts)
    created=0

    print("┌─────────────────────────────────────┐")
    print("│ create_songs.py – 100% Golden Path │")
    print("└─────────────────────────────────────┘")
    print(f"• Folder : {Path.cwd()}")
    print(f"• Endpoint: {GENERATE_URL}")
    print(f"• Prompts : {prompt_path} (tot {total} render(s))\n")

    for idx, it in enumerate(prompts, start=1):
        title  = it.get("title") or f"Prompt_{idx}"
        one    = (it.get("prompt") or "").strip()
        params = (it.get("params") or "").strip()
        count  = int(it.get("count", default_count))
        if not one:
            print(f"  ! Hoppar [{idx}] (saknar prompt)"); continue
        prompt_text = f"{one} || {params}" if params else one

        for var in range(1, count+1):
            rec={"index":idx,"variant":var,"title":title,"prompt_text":prompt_text,
                 "phase":"CREATE","status":"CREATING","http_status":None,"retries":0}
            upsert(items, rec); save_status(Path(JOB_FILE), meta, items)

            payload = {"prompt": prompt_text, "customMode": False}

            for attempt in range(0,7):
                try:
                    r = requests.post(GENERATE_URL, headers=headers, json=payload, timeout=int(env.get("TIMEOUT_CREATE","60")))
                    rec["http_status"] = r.status_code
                    if r.status_code == 200:
                        js = r.json() if r.content else {}

                        # ✳️ Suno kan svara 200 men med {code!=0, message} → behandla som fel
                        api_code = js.get("code") if isinstance(js, dict) else None
                        if api_code not in (None, 0, 200, "0", "200"):
                            reason = (js.get("message") or js.get("msg") or js.get("error") or "okänt fel")
                            rec.update({"status":"CREATE_FAILED","error_expl":f"API code {api_code}: {reason}"})
                            print(f"  ✖ API code {api_code}: {reason}")
                            if args.debug: print("    ↳ Debug:", (r.text or "")[:400])
                            break

                        # ✅ Robust extraktion av ID (root/data/response/sunoData/...)
                        job_id = extract_job_id(js)

                        if job_id:
                            rec.update({"job_id": job_id, "status":"QUEUED"}); created += 1
                            print(f"  ✓ [{created}/{total}] Skapade job {job_id}  ({title} v{var})")
                            break
                        else:
                            rec.update({"status":"CREATE_FAILED","error_expl":"Svar saknar job_id/taskId"})
                            print("  ! Svar saknar job_id/taskId")
                            if args.debug:
                                print("    ↳ Nycklar i svar:", list(js.keys()) if isinstance(js,dict) else type(js))
                                print("    ↳ Debug:", (r.text or "")[:400])
                            break

                    elif r.status_code in RETRYABLE:
                        wait = backoff_delay(attempt)
                        print(f"  … HTTP {r.status_code} – retry {attempt+1} om {wait:.1f}s")
                        time.sleep(wait); continue
                    else:
                        print(f"  ✖ HTTP {r.status_code}: {(r.text or '')[:200]}")
                        rec.update({"status":"CREATE_FAILED"}); break
                except Exception as e:
                    wait = backoff_delay(attempt)
                    print(f"  ✖ Nätverksfel: {e} – retry om {wait:.1f}s"); time.sleep(wait); continue
                finally:
                    upsert(items, rec); save_status(Path(JOB_FILE), meta, items)

            if rec.get("status") != "QUEUED":
                print(f"  ! Kunde inte starta ({title} v{var}). Status: {rec.get('status')}")
            time.sleep(0.15)

    # Archive snapshots
    try:
        Path(f"sp_{ts()}.json").write_text(Path(PROMPT_FILE).read_text(encoding="utf-8"), encoding="utf-8")
        Path(f"jobid_{ts()}.json").write_text(Path(JOB_FILE).read_text(encoding="utf-8"), encoding="utf-8")
        print("\n✓ Arkiverade prompts & job IDs")
    except Exception as e:
        print("! Kunde inte arkivera:", e)

    meta["overall_status"] = "READY_TO_POLL"; save_status(Path(JOB_FILE), meta, items)
    print("\nInfo:")
    print(f"  • {created}/{total} jobb skapade.")
    print("  • Kör:  python .\\poll_songs.py   (hämtar MP3 till .\\out\\) — eller poll_songs_suno100.py")
    print("  • Live: jobid_aktiv.json")
    print("\nKlart. ✨")

if __name__ == "__main__":
    main()

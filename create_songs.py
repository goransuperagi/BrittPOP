#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_songs_suno100.py — Golden‑Path enligt https://old-docs.sunoapi.org/
• Skriver/läser .env
• Bas‑URL: https://api.sunoapi.org/api/v1
• Minsta giltiga payload: { "prompt": "..." }  (Non‑custom mode)
• Robust parse: accepterar både {job_id} och {taskId}
• Backoff på 429/430/455/5xx
• Sparar jobben i jobid_aktiv.json  ➜ kompatibel med poll_songs.py
• Skapar default‑prompt om ingen finns (10s instrumental)
"""

from __future__ import annotations
import os, sys, json, time, argparse
from pathlib import Path
from datetime import datetime as dt

# —— Konstanter ——
DEFAULT_FOLDER = Path(r"C:/Brittpop")
PROMPT_FILE = "sunoprompt_aktiv.json"
JOB_FILE    = "jobid_aktiv.json"
DEFAULT_BASE = "https://api.sunoapi.org/api/v1"  # enligt old‑docs
RETRYABLE = {429, 430, 455, 500, 502, 503, 504}

# —— Hjälpare ——
ts = lambda: dt.utcnow().strftime("%Y%m%d-%H%M%S")
now_iso = lambda: dt.utcnow().replace(microsecond=0).isoformat()+"Z"

def ensure_folder(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    os.chdir(folder)

def load_env(env_path: Path) -> dict:
    env = {"SUNO_API_URL": DEFAULT_BASE, "SUNO_API_KEY": ""}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k,v = line.split("=",1); env[k.strip()] = v.strip()
    return env

def save_env(env_path: Path, env: dict):
    env_path.write_text("\n".join([f"{k}={env.get(k,'')}" for k in ("SUNO_API_URL","SUNO_API_KEY")]) + "\n", encoding="utf-8")

def write_json(path: Path, obj: dict):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))

def backoff_delay(attempt, base=1.6, cap=30.0, jitter=0.6):
    import random
    d = min(cap, base * (2 ** attempt))
    return max(0.4, d + random.uniform(-jitter, jitter))

def upsert(items, rec, keys=("index","variant")):
    for it in items:
        if all(it.get(k)==rec.get(k) for k in keys):
            it.update(rec); it["last_update"]=now_iso(); return
    rec["last_update"]=now_iso(); items.append(rec)

def save_status(jobfile: Path, meta, items):
    jobfile.write_text(json.dumps({"meta":meta,"items":items}, indent=2, ensure_ascii=False), encoding="utf-8")

# —— Default‑prompt (smoke) ——
DEFAULT_PROMPT = {
  "meta": { "default_count": 1 },
  "prompts": [
    {
      "title": "SMOKE_MIN",
      "prompt": "10s minimal instrumental jingle, steady beat, clean mix",
      "params": "",
      "count": 1
    }
  ]
}

# —— Main ——

def main():
    ap = argparse.ArgumentParser(description="Suno Golden‑Path – create_songs_suno100.py")
    ap.add_argument("--folder", default=str(DEFAULT_FOLDER), help="Arbetsmapp (default: C:/Brittpop)")
    ap.add_argument("--api-key", default=None, help="Suno API Key (överskuggar .env)")
    ap.add_argument("--api-url", default=None, help=f"Suno API Base URL (default: {DEFAULT_BASE})")
    ap.add_argument("--json", default=PROMPT_FILE, help=f"Prompt‑JSON (default: {PROMPT_FILE})")
    args = ap.parse_args()

    folder = Path(args.folder); ensure_folder(folder)
    Path("out").mkdir(parents=True, exist_ok=True)

    # .env
    env_path = Path(".env")
    env = load_env(env_path)
    if args.api_url: env["SUNO_API_URL"] = args.api_url.strip()
    key = args.api_key or os.getenv("SUNO_API_KEY") or env.get("SUNO_API_KEY","")
    if not key:
        try: key = input("Ange din SUNO_API_KEY: ").strip()
        except KeyboardInterrupt: print(); sys.exit(1)
    env["SUNO_API_KEY"] = key; save_env(env_path, env)

    base_url = (env.get("SUNO_API_URL") or DEFAULT_BASE).rstrip("/")
    generate_url = base_url + ("/generate" if not base_url.endswith("/generate") else "")

    # prompt JSON
    prompt_path = Path(args.json)
    if not prompt_path.exists(): write_json(prompt_path, DEFAULT_PROMPT)
    data = read_json(prompt_path)
    prompts = data.get("prompts", [])
    if not prompts: print("✖ Inga prompts i JSON."); sys.exit(2)

    # HTTP
    import requests
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    default_count = int(data.get("meta",{}).get("default_count",1))
    items=[]; meta={"created_at":now_iso(),"overall_status":"CREATING","endpoint":generate_url}
    save_status(Path(JOB_FILE), meta, items)

    total = sum(int(it.get("count", default_count)) for it in prompts)
    created = 0

    print("┌─────────────────────────────────────┐")
    print("│ create_songs_suno100.py – Suno API │")
    print("└─────────────────────────────────────┘")
    print(f"• Folder : {folder}")
    print(f"• Endpoint: {generate_url}")
    print(f"• Prompts : {prompt_path} (tot {total} render(s))\n")

    for idx, it in enumerate(prompts, start=1):
        title  = it.get("title") or f"Prompt_{idx}"
        one    = (it.get("prompt") or "").strip()
        params = (it.get("params") or "").strip()
        count  = int(it.get("count", default_count))
        if not one: print(f"  ! Hoppar [{idx}] (saknar prompt)"); continue
        prompt_text = f"{one} || {params}" if params else one

        for var in range(1, count+1):
            rec={"index":idx,"variant":var,"title":title,"prompt_text":prompt_text,
                 "phase":"CREATE","status":"CREATING","http_status":None,"retries":0}
            upsert(items, rec); save_status(Path(JOB_FILE), meta, items)

            payload={"prompt": prompt_text}  # Non‑custom mode: endast prompt

            for attempt in range(0,7):
                try:
                    r = requests.post(generate_url, headers=headers, json=payload, timeout=60)
                    rec["http_status"] = r.status_code
                    if r.status_code == 200:
                        js = r.json() if r.content else {}
                        job_id = js.get("job_id") or js.get("taskId") or js.get("task_id")
                        if job_id:
                            rec.update({"job_id": job_id, "status":"QUEUED"})
                            created += 1
                            print(f"  ✓ [{created}/{total}] Skapade job {job_id}  ({title} v{var})")
                            break
                        else:
                            rec.update({"status":"CREATE_FAILED","error_expl":"Svar saknar job_id/taskId"})
                            print("  ! Svar saknar job_id/taskId")
                            break
                    elif r.status_code in RETRYABLE:
                        wait = backoff_delay(attempt)
                        rec.update({"status":"RETRYING","error_expl":f"HTTP {r.status_code} — försöker igen om {wait:.1f}s"})
                        print(f"  … HTTP {r.status_code} – retry {attempt+1} om {wait:.1f}s")
                        upsert(items, rec); save_status(Path(JOB_FILE), meta, items)
                        time.sleep(wait); continue
                    else:
                        txt = (r.text or "")[:200]
                        rec.update({"status":"CREATE_FAILED","error_expl":f"HTTP {r.status_code}: {txt}"})
                        print(f"  ✖ HTTP {r.status_code}: {txt}")
                        break
                except Exception as e:
                    wait = backoff_delay(attempt)
                    rec.update({"status":"RETRYING","error_expl":f"Nätverksfel: {e}"})
                    print(f"  ✖ Nätverksfel: {e} – retry om {wait:.1f}s")
                    upsert(items, rec); save_status(Path(JOB_FILE), meta, items)
                    time.sleep(wait); continue
                finally:
                    upsert(items, rec); save_status(Path(JOB_FILE), meta, items)
            if rec.get("status") != "QUEUED":
                print(f"  ! Kunde inte starta ({title} v{var}). Status: {rec.get('status')}")
            time.sleep(0.15)

    # Arkivera ögonblicksbild
    try:
        Path(f"sp_{ts()}.json").write_text(Path(PROMPT_FILE).read_text(encoding="utf-8"), encoding="utf-8")
        Path(f"jobid_{ts()}.json").write_text(Path(JOB_FILE).read_text(encoding="utf-8"), encoding="utf-8")
        print("\n✓ Arkiverade prompts & job IDs")
    except Exception as e:
        print("! Kunde inte arkivera:", e)

    meta["overall_status"]="READY_TO_POLL"; save_status(Path(JOB_FILE), meta, items)
    print("\nInfo:")
    print(f"  • {created}/{total} jobb skapade.")
    print("  • Kör:  python .\\poll_songs.py   (hämtar MP3 till .\\out\\)")
    print("  • Live: jobid_aktiv.json")
    print("\nKlart. ✨")

if __name__ == "__main__":
    main()

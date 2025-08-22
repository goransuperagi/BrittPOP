# create_songs.py  (v3)
# -*- coding: utf-8 -*-
import os, json, time, re, random, datetime, argparse
from datetime import datetime as dt
from pathlib import Path
import requests
from dotenv import load_dotenv

# ===== ENV =====
# Ladda .env i nuvarande dir
load_dotenv(dotenv_path=Path.cwd() / ".env")

def env_first(*keys, default=None):
    for k in keys:
        v = os.getenv(k)
        if v: return v
    return default

# ===== Utils =====
def ts(): return dt.utcnow().strftime("%Y%m%d-%H%M%S")
def now_iso(): return dt.utcnow().replace(microsecond=0).isoformat() + "Z"
def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def backoff_delay(attempt, base=1.5, cap=30.0, jitter=0.5):
    d = min(cap, base * (2 ** attempt))
    return max(0.0, d + random.uniform(-jitter, jitter))

# ===== CLI =====
ap = argparse.ArgumentParser(description="Britt-POP × Suno – create_songs v3")
ap.add_argument("--json", default="sunoprompt_aktiv.json", help="Prompt-JSON (default: sunoprompt_aktiv.json)")
ap.add_argument("--api-key", default=None, help="Suno API key (överskuggar .env)")
ap.add_argument("--api-url", default=None, help="Suno API base URL (t.ex. https://api.suno.ai/v1)")
args = ap.parse_args()

PROMPT_FILE_ACTIVE = args.json
JOBID_FILE_ACTIVE  = "jobid_aktiv.json"

# ===== Konfiguration från env/CLI =====
API_KEY = args.api_key or env_first("SUNO_API_KEY")
if not API_KEY:
    print("✖ SUNO_API_KEY saknas. Lägg in i .env eller passera via --api-key.")
    raise SystemExit(2)

base_url = args.api_url or env_first("SUNO_API_URL", default="https://api.suno.ai/v1")
base_url = base_url.rstrip("/")
GENERATE_URL = (base_url + "/generate") if not base_url.endswith("/generate") else base_url

RETRYABLE = {429, 430, 455, 500, 502, 503, 504}
ERROR_EXPL = {
    400:"Ogiltiga parametrar (kolla prompt/JSON).",
    401:"Obehörig – fel/avsaknad av API-nyckel.",
    404:"Fel endpoint-URL.",
    413:"Prompt för lång – korta ner.",
    429:"Rate-limit/slut på krediter.",
    455:"Underhållsläge.",
    500:"Serverfel.",
    502:"Gateway-fel.",
    503:"Tjänsten tillfälligt nere.",
    504:"Gateway timeout."
}

def upsert(items, rec, keys=("index","variant")):
    for it in items:
        if all(it.get(k)==rec.get(k) for k in keys):
            it.update(rec); it["last_update"]=now_iso(); return
    rec["last_update"]=now_iso(); items.append(rec)

def main():
    if not Path(PROMPT_FILE_ACTIVE).exists():
        print(f"✖ Saknar {PROMPT_FILE_ACTIVE}.")
        raise SystemExit(2)

    data = json.loads(Path(PROMPT_FILE_ACTIVE).read_text(encoding="utf-8"))
    meta_in = data.get("meta", {})
    prompts = data.get("prompts", [])
    if not prompts:
        print("✖ Inga prompts hittades i JSON.")
        raise SystemExit(2)

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    default_count = int(meta_in.get("default_count", 1))

    items=[]; meta={"created_at":now_iso(),"overall_status":"CREATING",
                    "note":"Jobb skapas och loggas live i jobid_aktiv.json"}
    save_json(JOBID_FILE_ACTIVE, {"meta":meta,"items":items})

    total = sum(int(it.get("count", default_count)) for it in prompts)
    created = 0

    print("┌─────────────────────────────────────┐")
    print("│ create_songs.py – Britt-POP × Suno │")
    print("└─────────────────────────────────────┘")
    print(f"• Endpoint: {GENERATE_URL}")
    print(f"• Läser:    {PROMPT_FILE_ACTIVE}")
    print(f"• Skapar:   {total} render(s)\n")

    for idx, it in enumerate(prompts, start=1):
        title  = it.get("title") or f"Prompt_{idx}"
        one    = (it.get("prompt") or "").strip()
        params = (it.get("params") or "").strip()
        count  = int(it.get("count", default_count))
        if not one:
            print(f"  ! Hoppar över (saknar prompt) [{idx}] {title}")
            continue

        prompt_text = f"{one} || {params}" if params else one

        for var in range(1, count+1):
            rec={"index":idx,"variant":var,"title":title,"prompt_text":prompt_text,
                 "phase":"CREATE","status":"CREATING","http_status":None,"retries":0}
            upsert(items, rec); save_json(JOBID_FILE_ACTIVE, {"meta":meta,"items":items})

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
                        upsert(items, rec); save_json(JOBID_FILE_ACTIVE, {"meta":meta,"items":items})
                        time.sleep(wait); continue
                    else:
                        rec.update({"status":"CREATE_FAILED",
                                    "error_expl":ERROR_EXPL.get(r.status_code,f"Okänt fel ({r.status_code})")})
                        print(f"  ✖ HTTP {r.status_code}: {r.text[:200]}")
                        break
                except requests.RequestException as e:
                    rec["status"]="RETRYING"
                    rec["error_expl"]=f"Nätverksfel: {e}"
                    wait = backoff_delay(attempt)
                    print(f"  ✖ Nätverksfel: {e} – retry om {wait:.1f}s")
                    upsert(items, rec); save_json(JOBID_FILE_ACTIVE, {"meta":meta,"items":items})
                    time.sleep(wait); continue
                finally:
                    upsert(items, rec); save_json(JOBID_FILE_ACTIVE, {"meta":meta,"items":items})

            if rec.get("status") != "QUEUED":
                print(f"  ! Kunde inte starta ({title} v{var}). Status: {rec.get('status')}")

            time.sleep(0.15)

    # Arkiv
    sp_name   = f"sp_{ts()}.json"
    job_name  = f"jobid_{ts()}.json"
    try:
        Path(sp_name).write_text(Path(PROMPT_FILE_ACTIVE).read_text(encoding="utf-8"), encoding="utf-8")
        print(f"\n✓ Arkiverade prompts → {sp_name}")
    except Exception as e:
        print("! Kunde inte arkivera prompts:", e)
    try:
        save_json(job_name, json.loads(Path(JOBID_FILE_ACTIVE).read_text(encoding="utf-8")))
        print(f"✓ Arkiverade job IDs → {job_name}")
    except Exception as e:
        print("! Kunde inte arkivera job IDs:", e)

    meta["overall_status"]="READY_TO_POLL"
    save_json(JOBID_FILE_ACTIVE, {"meta":meta,"items":items})

    print("\nInfo:")
    print(f"  • {created}/{total} jobb skapade.")
    print("  • Kör:  python poll_songs.py  (för att hämta MP3)")
    print("  • Live-status: jobid_aktiv.json")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Britt-POP × Suno — create_songs.py
- Läser sunoprompt_aktiv.json (meta + prompts[])
- Startar jobb mot Suno API och skriver status live i jobid_aktiv.json
- Exponential backoff + jitter och max-retry-policy för robusta anrop
- Arkiverar både prompts (sp_YYYYMMDD-HHMMSS.json) och jobid (jobid_YYYYMMDD-HHMMSS.json)
- Avslutar med overall_status=READY_TO_POLL
"""

import os, json, requests, time, re, datetime, random
from datetime import datetime as dt

# ======= Konfiguration =======
API_KEY  = os.getenv("SUNO_API_KEY")
BASE_URL = os.getenv("SUNO_API_URL", "https://api.suno.ai/v1/generate")

PROMPT_FILE_ACTIVE = "sunoprompt_aktiv.json"   # indata (ska finnas)
JOBID_FILE_ACTIVE  = "jobid_aktiv.json"        # status + job_id skrivs här (live)

# Backoff/Retry-policy (justera vid behov)
MAX_RETRIES_CREATE = int(os.getenv("MAX_RETRIES_CREATE", "6"))   # max försök per POST
BACKOFF_BASE_SEC   = float(os.getenv("BACKOFF_BASE_SEC", "1.5")) # bas (sek)
BACKOFF_CAP_SEC    = float(os.getenv("BACKOFF_CAP_SEC", "30.0")) # tak (sek)
JITTER_SEC         = float(os.getenv("JITTER_SEC", "0.5"))       # slumpjitter +/- (sek)

RETRYABLE = {429, 430, 455, 500, 502, 503, 504}
ERROR_EXPL = {
    400:"Ogiltiga parametrar (kolla prompt/JSON).",
    401:"Obehörig – saknad/fel SUNO_API_KEY.",
    404:"Fel metod/sökväg (endpoint-URL?).",
    405:"Otillåten metod eller rate-limit på endpoint.",
    413:"Prompt för lång – korta ner.",
    429:"Rate-limit eller slut på krediter.",
    430:"För hög anropsfrekvens – sakta ned.",
    455:"Tjänsten i underhåll – försök igen senare.",
    500:"Serverfel – tillfälligt problem.",
    502:"Serverfel – gateway.",
    503:"Tjänsten tillfälligt nere.",
    504:"Gateway timeout – försök igen."
}

# ======= Hjälpfunktioner =======
def ts():
    return dt.utcnow().strftime("%Y%m%d-%H%M%S")

def now_iso():
    return dt.utcnow().replace(microsecond=0).isoformat() + "Z"

def slug(s: str, n: int = 60) -> str:
    s = (s or "").strip() or "track"
    s = re.sub(r'[<>:\"/\\|?*\n\r\t]+',' ',s).strip()
    return (s[:n] or "track").replace(' ','_')

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def write_job_active(meta, items):
    save_json(JOBID_FILE_ACTIVE, {"meta": meta, "items": items})

def upsert_item(items, rec, by=("index","variant")):
    for it in items:
        if all(it.get(k)==rec.get(k) for k in by):
            it.update(rec); it["last_update"]=now_iso(); return it
    rec["last_update"]=now_iso(); items.append(rec); return rec

def backoff_delay(attempt: int) -> float:
    """
    Exponential backoff med jitter:
    delay = min(cap, base * 2^attempt) +/- jitter
    """
    delay = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** attempt))
    jitter = random.uniform(-JITTER_SEC, JITTER_SEC)
    return max(0.0, delay + jitter)

# ======= Huvudlogik =======
def main():
    if not API_KEY:
        print("✖ SUNO_API_KEY saknas. Lägg in i .env och försök igen.")
        raise SystemExit(2)
    if not os.path.exists(PROMPT_FILE_ACTIVE):
        print(f"✖ Saknar {PROMPT_FILE_ACTIVE}. Skapa filen och försök igen.")
        raise SystemExit(2)

    print("┌─────────────────────────────────────┐")
    print("│ create_songs.py – Britt-POP × Suno │")
    print("└─────────────────────────────────────┘")
    print(f"• Läser {PROMPT_FILE_ACTIVE} ...")

    data = load_json(PROMPT_FILE_ACTIVE)   # {meta:{}, prompts:[...]}
    meta_json = data.get("meta", {})
    prompts   = data.get("prompts", [])
    if not prompts:
        print("✖ Inga prompts hittades i JSON (förväntar meta + prompts).")
        raise SystemExit(2)

    default_count = int(meta_json.get("default_count", 1))
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    items=[]; meta={"created_at":now_iso(),"overall_status":"CREATING",
                    "note":"Skapar jobb och skriver status live (jobid_aktiv.json)."}
    write_job_active(meta, items)

    total = sum(int(it.get("count", default_count)) for it in prompts)
    created = 0
    print(f"• Startar jobb mot API: {BASE_URL}")
    print(f"• Antal renderingar som skapas: {total}\n")

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
            # init statuspost
            rec={"index":idx,"variant":var,"title":title,"prompt_text":prompt_text,"phase":"CREATE",
                 "status":"CREATING","http_status":None,"error_code":None,"error_expl":None,
                 "retries":0,"next_retry_at":None}
            upsert_item(items, rec); write_job_active(meta, items)

            payload={"prompt":prompt_text}

            # Retry-loop med exponential backoff
            for attempt in range(0, MAX_RETRIES_CREATE+1):
                try:
                    r = requests.post(BASE_URL, headers=headers, json=payload, timeout=60)
                    rec["http_status"]=r.status_code

                    if r.status_code==200:
                        job_id=(r.json() or {}).get("job_id")
                        if job_id:
                            rec.update({"job_id":job_id,"status":"QUEUED"})
                            created += 1
                            print(f"  ✓ [{created}/{total}] Startade job {job_id}  ({title} v{var})")
                            break
                        else:
                            rec.update({"status":"CREATE_FAILED","error_expl":"Svar saknar job_id"})
                            print("  ! Svar saknar job_id")
                            break

                    elif r.status_code in RETRYABLE:
                        rec["retries"] = attempt
                        rec["error_code"]=r.status_code
                        rec["error_expl"]=ERROR_EXPL.get(r.status_code,"Tillfälligt fel – försöker igen.")
                        # Särfall: 429 med "credit" i text → ON_HOLD_CREDITS, manuell åtgärd
                        if r.status_code==429 and "credit" in (r.text or "").lower():
                            rec["status"]="ON_HOLD_CREDITS"
                            print("  … ON_HOLD_CREDITS – fyll på krediter och kör om.")
                            break
                        # Övriga retrybara → exponential backoff
                        rec["status"]= ("RETRYING_MAINT" if r.status_code==455
                                        else "RETRYING_RATE" if r.status_code in (429,430)
                                        else "RETRYING_SERVER")
                        wait = backoff_delay(attempt)
                        nxt = dt.utcnow() + datetime.timedelta(seconds=wait)
                        rec["next_retry_at"]=nxt.replace(microsecond=0).isoformat()+"Z"
                        print(f"  … {rec['status']} (HTTP {r.status_code}) – {rec['error_expl']} – retry om {wait:.1f}s")
                        upsert_item(items, rec); write_job_active(meta, items)
                        time.sleep(wait)
                        continue

                    else:
                        rec.update({"status":"CREATE_FAILED","error_code":r.status_code,
                                    "error_expl":ERROR_EXPL.get(r.status_code,"Okänt fel")})
                        print(f"  ✖ HTTP {r.status_code}: {r.text[:200]}")
                        break

                except requests.RequestException as e:
                    rec["retries"] = attempt
                    rec.update({"status":"RETRYING_SERVER","error_expl":f"Nätverksfel: {e}"})
                    wait = backoff_delay(attempt)
                    nxt = dt.utcnow() + datetime.timedelta(seconds=wait)
                    rec["next_retry_at"]=nxt.replace(microsecond=0).isoformat()+"Z"
                    print(f"  ✖ Nätverksfel: {e} – retry om {wait:.1f}s")
                    upsert_item(items, rec); write_job_active(meta, items)
                    time.sleep(wait)
                    continue

                finally:
                    upsert_item(items, rec); write_job_active(meta, items)

            # slut på retry-loop
            if rec.get("status") not in ("QUEUED",):
                print(f"  ! Kunde inte starta jobb för ({title} v{var}) efter retries. Status: {rec.get('status')}")

            time.sleep(0.15)  # liten paus för att inte spamma API:t

    # Arkivera prompts & jobid snapshot
    sp_name   = f"sp_{ts()}.json"
    job_name  = f"jobid_{ts()}.json"
    try:
        with open(PROMPT_FILE_ACTIVE, "r", encoding="utf-8") as s, open(sp_name,"w",encoding="utf-8") as d:
            d.write(s.read())
        print(f"\n✓ Arkiverade prompts → {sp_name}")
    except Exception as e:
        print("! Kunde inte arkivera prompts:", e)

    try:
        save_json(job_name, {"meta":meta,"items":items})
        print(f"✓ Arkiverade job IDs → {job_name}")
    except Exception as e:
        print("! Kunde inte arkivera job IDs:", e)

    meta["overall_status"]="READY_TO_POLL"
    write_job_active(meta, items)

    print("\nInfo:")
    print(f"  • {created}/{total} jobb skapade.")
    print("  • Kör:  python poll_songs.py  (för att hämta MP3)")
    print("  • Aktiva statusar hålls i jobid_aktiv.json. Arkivkopior skapade.")

if __name__ == "__main__":
    main()

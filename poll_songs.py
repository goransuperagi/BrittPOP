#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Britt-POP × Suno — poll_songs.py
- Läser jobid_aktiv.json (skriven av create_songs.py)
- Pollar jobben tills completed/failed/canceled
- Exponential backoff + jitter och max-retry-policy
- Hämtar MP3 till out/, sparar jobbrespons per jobb till job/
- Arkiverar jobid_aktiv.json → jobid_YYYYMMDD-HHMMSS.json
- Städar: tar bort jobid_aktiv.json och ev. kvarvarande sunoprompt_aktiv.json
"""

import os, json, time, requests, pathlib, re, datetime, random
from datetime import datetime as dt

# ======= Konfiguration =======
API_KEY  = os.getenv("SUNO_API_KEY")
BASE_URL = os.getenv("SUNO_JOB_URL", "https://api.suno.ai/v1/jobs")

JOBID_FILE_ACTIVE  = "jobid_aktiv.json"
PROMPT_FILE_ACTIVE = "sunoprompt_aktiv.json"

OUT_DIR = pathlib.Path("out")
JOB_DIR = pathlib.Path("job")
OUT_DIR.mkdir(parents=True, exist_ok=True)
JOB_DIR.mkdir(parents=True, exist_ok=True)

# Backoff/Retry-policy
MAX_RETRIES_POLL   = int(os.getenv("MAX_RETRIES_POLL", "1000"))  # många – polling är i sig "lång"
BACKOFF_BASE_SEC   = float(os.getenv("BACKOFF_BASE_SEC", "1.5"))
BACKOFF_CAP_SEC    = float(os.getenv("BACKOFF_CAP_SEC", "30.0"))
JITTER_SEC         = float(os.getenv("JITTER_SEC", "0.5"))

RETRYABLE = {429, 430, 455, 500, 502, 503, 504}
ERROR_EXPL = {
    400:"Ogiltiga parametrar.",
    401:"Obehörig – kontrollera SUNO_API_KEY.",
    404:"Fel sökväg/metod.",
    405:"Otillåten metod eller rate-limit.",
    413:"Payload för stor eller prompt för lång.",
    429:"Rate-limit eller krediter slut.",
    430:"För hög anropsfrekvens.",
    455:"Underhåll – prova igen senare.",
    500:"Serverfel.",
    502:"Gatewayfel.",
    503:"Tjänsten tillfälligt nere.",
    504:"Gateway timeout."
}

# ======= Hjälpfunktioner =======
def ts(): return dt.utcnow().strftime("%Y%m%d-%H%M%S")
def now_iso(): return dt.utcnow().replace(microsecond=0).isoformat()+"Z"

def slug(s: str, n: int = 60) -> str:
    s = (s or "").strip() or "track"
    s = re.sub(r'[<>:\"/\\|?*\n\r\t]+',' ',s).strip()
    return (s[:n] or "track").replace(' ','_')

def backoff_delay(attempt: int) -> float:
    delay = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** attempt))
    jitter = random.uniform(-JITTER_SEC, JITTER_SEC)
    return max(0.0, delay + jitter)

def load_active():
    with open(JOBID_FILE_ACTIVE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_active(obj):
    with open(JOBID_FILE_ACTIVE, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def set_status(items, job_id, **kv):
    for it in items:
        if it.get("job_id")==job_id:
            it.update(kv); it["last_update"]=now_iso(); return it
    return None

def download(url, dst: pathlib.Path):
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk: f.write(chunk)

def archive_and_clean_active():
    # Arkivera jobid_aktiv.json → jobid_YYYYMMDD-HHMMSS.json
    try:
        with open(JOBID_FILE_ACTIVE, "r", encoding="utf-8") as src:
            data = src.read()
        name = f"jobid_{ts()}.json"
        with open(name, "w", encoding="utf-8") as dst:
            dst.write(data)
        print(f"✓ Arkiverade aktiva job IDs → {name}")
    except Exception as e:
        print("! Kunde inte arkivera job IDs:", e)

    # Ta bort aktiva filer
    if pathlib.Path(JOBID_FILE_ACTIVE).exists():
        pathlib.Path(JOBID_FILE_ACTIVE).unlink()
        print(f"• Tog bort {JOBID_FILE_ACTIVE}")
    if pathlib.Path(PROMPT_FILE_ACTIVE).exists():
        pathlib.Path(PROMPT_FILE_ACTIVE).unlink()
        print(f"• Tog bort {PROMPT_FILE_ACTIVE} (aktiv promptfil)")

# ======= Polling per jobb =======
def poll_one(session, job, headers, items, meta) -> bool:
    """
    job: {job_id, index, variant, title?, prompt_text?}
    Returnerar True vid lyckad nedladdning, False om permanent fel.
    Hanterar själv retrybara HTTP med backoff.
    """
    job_id = job.get("job_id")
    title  = job.get("title") or ""
    label  = f"{title} v{job.get('variant')}" if title else f"job {job_id}"

    print(f"\n▶ Börjar polla {label} ({job_id}) ...")
    start = time.time()
    seen_status = None

    # Ställ initial status
    set_status(items, job_id, phase="POLL", status="POLLING")
    save_active({"meta":meta,"items":items})

    attempt = 0
    while attempt <= MAX_RETRIES_POLL:
        try:
            r = session.get(f"{BASE_URL}/{job_id}", headers=headers, timeout=30)
            http = r.status_code

            if http in RETRYABLE:
                # Underhåll/rate-limit/server: försök igen (utan att markera fail)
                st = ("RETRYING_MAINT" if http==455 else
                      "RETRYING_RATE"  if http in (429,430) else
                      "RETRYING_SERVER")
                expl = ERROR_EXPL.get(http, "Tillfälligt fel – försöker igen.")
                wait = backoff_delay(min(attempt, 10))
                nxt  = dt.utcnow() + datetime.timedelta(seconds=wait)
                set_status(items, job_id, http_status=http, status=st,
                           error_code=http, error_expl=expl,
                           retries=attempt, next_retry_at=nxt.replace(microsecond=0).isoformat()+"Z")
                save_active({"meta":meta,"items":items})
                print(f"  … {st} (HTTP {http}) – {expl} – retry om {wait:.1f}s")
                time.sleep(wait)
                attempt += 1
                continue

            if http != 200:
                # Permanent fel (t.ex. 400/401/404/405/413)
                expl = ERROR_EXPL.get(http, "Okänt fel")
                set_status(items, job_id, http_status=http, status="POLL_FAILED",
                           error_code=http, error_expl=expl, retries=attempt)
                save_active({"meta":meta,"items":items})
                print(f"  ✖ POLL_FAILED (HTTP {http}) – {expl}")
                return False

            data = r.json() or {}
            # Spara senaste serverresponsen för transparens
            with open(JOB_DIR / f"{job_id}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            status = data.get("status") or data.get("state") or ""
            if status != seen_status:
                print(f"  • Status: {status}")
                seen_status = status
            set_status(items, job_id, http_status=http, status=status)
            save_active({"meta":meta,"items":items})

            if status.lower() == "completed":
                # Varianter: {"result":{"audio_url":...}} eller {"audio":{"url":...}}
                audio_url = (data.get("result") or {}).get("audio_url") or (data.get("audio") or {}).get("url")
                if not audio_url:
                    print("  ! completed men ingen audio_url i svaret")
                    set_status(items, job_id, status="POLL_FAILED", error_expl="completed utan audio_url")
                    save_active({"meta":meta,"items":items})
                    return False

                base = f"{job.get('index',0):03d}_{slug(title)}_v{job.get('variant','1')}_{job_id}" if title else job_id
                dst = OUT_DIR / f"{base}.mp3"
                print(f"  ↓ Laddar ner MP3 → {dst.name}")
                set_status(items, job_id, status="DOWNLOADING"); save_active({"meta":meta,"items":items})
                download(audio_url, dst)
                elapsed = int(time.time() - start)
                print(f"  ✓ Klar ({elapsed}s). Fil: {dst.resolve()}")
                set_status(items, job_id, status="DONE"); save_active({"meta":meta,"items":items})
                return True

            if status.lower() in {"failed", "canceled"}:
                set_status(items, job_id, status="POLL_FAILED", error_expl=f"Jobb {status}")
                save_active({"meta":meta,"items":items})
                print(f"  ✖ Avslutades med status: {status}")
                return False

            # Fortsätt polla (normal väg)
            time.sleep(2.5)
            attempt += 1

        except requests.RequestException as e:
            # Nätverksfel: behandla som retrybart serverfel
            st = "RETRYING_SERVER"
            wait = backoff_delay(min(attempt, 10))
            nxt  = dt.utcnow() + datetime.timedelta(seconds=wait)
            set_status(items, job_id, http_status=None, status=st,
                       error_code=None, error_expl=f"Nätverksfel: {e}",
                       retries=attempt, next_retry_at=nxt.replace(microsecond=0).isoformat()+"Z")
            save_active({"meta":meta,"items":items})
            print(f"  ✖ Nätverksfel – retry om {wait:.1f}s")
            time.sleep(wait)
            attempt += 1

    # Max-retry passerat
    set_status(items, job_id, status="POLL_FAILED", error_expl="Max retries uppnådda")
    save_active({"meta":meta,"items":items})
    print("  ✖ Max retries uppnådda – ger upp.")
    return False

# ======= Huvudlogik =======
def main():
    if not API_KEY:
        print("✖ SUNO_API_KEY saknas. Lägg in i .env och försök igen.")
        raise SystemExit(2)
    if not os.path.exists(JOBID_FILE_ACTIVE):
        print(f"✖ Saknar {JOBID_FILE_ACTIVE}. Kör create_songs.py först.")
        raise SystemExit(2)

    active = load_active()
    meta = active.get("meta", {})
    items = active.get("items", [])
    jobs  = [j for j in items if j.get("job_id")]
    if not jobs:
        print("✖ Inga job_id i jobid_aktiv.json. Kör create_songs.py först.")
        raise SystemExit(2)

    meta["overall_status"] = "POLLING"
    save_active({"meta":meta,"items":items})

    print("┌──────────────────────────────────┐")
    print("│ poll_songs.py – Britt-POP × Suno │")
    print("└──────────────────────────────────┘")
    print(f"• Antal jobb att polla: {len(jobs)}")

    ok = fail = 0
    headers = {"Authorization": f"Bearer {API_KEY}"}
    with requests.Session() as session:
        for i, job in enumerate(jobs, start=1):
            print(f"\n=== [{i}/{len(jobs)}] ===")
            if poll_one(session, job, headers, items, meta):
                ok += 1
            else:
                fail += 1
            # spara efter varje jobb (progress syns direkt)
            save_active({"meta":meta,"items":items})

    print("\nSammanfattning:")
    print(f"  ✓ Klara: {ok}")
    print(f"  ✖ Misslyckade: {fail}")

    # overall-status & arkiv/städ
    meta["overall_status"] = "DONE"
    save_active({"meta":meta,"items":items})
    archive_and_clean_active()

    print("\nKlart. MP3 finns i ./out, jobbrespons i ./job.")

if __name__ == "__main__":
    main()

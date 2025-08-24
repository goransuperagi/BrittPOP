#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
poll_songs.py — Robust Suno poll med 503-hantering, loggning och tydlig status.
Windows-fokus. Kräver: requests (pip install requests), .env med SUNO_API_KEY.
"""

import os, sys, json, time, datetime, random
import requests

# ---------- Konfiguration & .env ----------

def load_env_envfile():
    if not os.path.isfile(".env"):
        return
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line=line.strip()
                if not line or line.startswith("#"): 
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and v and k not in os.environ:
                        os.environ[k] = v
    except Exception as e:
        print(f"⚠️  Kunde inte läsa .env: {e}")

load_env_envfile()

SUNO_API_BASE = os.getenv("SUNO_API", "https://api.sunoapi.org").rstrip("/")
SUNO_API_POLL = f"{SUNO_API_BASE}/api/v1/generate/record-info?taskId={{job_id}}"

TIMEOUT_POLL     = int(os.getenv("TIMEOUT_POLL", "30"))
TIMEOUT_DOWNLOAD = int(os.getenv("TIMEOUT_DOWNLOAD", "180"))

BACKOFF_BASE_SEC = float(os.getenv("BACKOFF_BASE_SEC", "1.5"))
BACKOFF_CAP_SEC  = float(os.getenv("BACKOFF_CAP_SEC",  "30.0"))
JITTER_SEC       = float(os.getenv("JITTER_SEC",       "0.5"))
MAX_RETRIES_POLL = int(os.getenv("MAX_RETRIES_POLL", "1000"))

STATUS_FILE = "jobid_aktiv.json"
LOG_FILE    = "log.txt"

# ---------- Logg ----------

_log_initialized = False

def _ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def init_log():
    """
    Om logg finns från create -> append.
    Om inte, skapa ny fil.
    """
    global _log_initialized
    mode = "a" if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0 else "w"
    try:
        with open(LOG_FILE, mode, encoding="utf-8") as lf:
            lf.write(f"{_ts()} - === poll_songs.py start ===\n")
            lf.write(f"{_ts()} - API_BASE={SUNO_API_BASE}\n")
        _log_initialized = True
    except Exception as e:
        print(f"⚠️  Kunde inte initiera logg: {e}")

def log(msg):
    global _log_initialized
    s = f"{_ts()} - {msg}"
    print(s)
    try:
        if not _log_initialized:
            init_log()
        with open(LOG_FILE, "a", encoding="utf-8") as lf:
            lf.write(s + "\n")
    except Exception as e:
        print(f"⚠️  Kunde inte skriva till logg: {e}")

# ---------- Hjälp ----------

def ensure_directories():
    for d in ("out", "job"):
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)

def load_api_key():
    ak = os.getenv("SUNO_API_KEY")
    if ak:
        return ak
    load_env_envfile()
    return os.getenv("SUNO_API_KEY")

# ---------- Körning ----------

def main():
    init_log()
    ensure_directories()

    api_key = load_api_key()
    if not api_key:
        log("🚫 SUNO_API_KEY saknas. Kontrollera .env och försök igen.")
        sys.exit(1)

    if not os.path.isfile(STATUS_FILE):
        log(f"🚫 Hittar inte {STATUS_FILE}. Kör create_songs.py först.")
        sys.exit(1)

    # Läs in status
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            job_status = json.load(f)
    except Exception as e:
        log(f"🚫 Kunde inte läsa {STATUS_FILE}: {e}")
        sys.exit(1)

    job_status.setdefault("meta", {})
    job_status["meta"]["overall_status"] = "POLLING"
    job_status["meta"]["note"] = "Pollar Suno efter färdiga låtar..."
    job_status["meta"]["poll_started"] = _ts()

    for item in job_status.get("items", []):
        if item.get("job_id"):
            item["phase"] = "POLL"
            if item.get("status") in ("QUEUED","CREATING"):
                item["status"] = "POLLING"
            item["retries"] = 0
            item["next_retry_at"] = None
            item["last_update"] = _ts()
        else:
            item["phase"] = "CREATE"
            item["last_update"] = _ts()

    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(job_status, f, indent=2)

    headers = {"Authorization": f"Bearer {api_key}"}

    log("▶ Börjar polling av jobb...")

    for item in job_status.get("items", []):
        job_id = item.get("job_id")
        if not job_id:
            continue

        title   = item.get("title", "Untitled")
        variant = item.get("variant", 1)
        index   = item.get("index", 0)
        log(f"▶ Börjar polla {title} v{variant} ({job_id}) ...")

        poll_attempts = 0
        start_time = time.time()

        while poll_attempts < MAX_RETRIES_POLL:
            poll_attempts += 1
            item["retries"] = poll_attempts
            item["last_update"] = _ts()
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(job_status, f, indent=2)

            url = SUNO_API_POLL.format(job_id=job_id)

            try:
                resp = requests.get(url, headers=headers, timeout=TIMEOUT_POLL)
            except Exception as e:
                # nätverksglitch -> försök igen snart
                time.sleep(2.0)
                continue

            code = resp.status_code
            item["http_status"] = code

            if code == 200:
                data = {}
                try:
                    data = resp.json()
                except:
                    pass

                inner = data.get("code")
                if inner and inner != 200:
                    # API rapporterar fel
                    item["status"] = "POLL_FAILED"
                    item["error_code"] = inner
                    item["error_expl"] = data.get("msg") or data.get("message") or "API-rapport fel"
                    item["last_update"] = _ts()
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    log(f"✗ Jobb {job_id} rapporterade API-fel: {item['error_expl']}")
                    break

                content = data.get("data", {})

                # statusfält kan heta status/taskStatus/state; även i response.response
                api_status = content.get("status") or content.get("taskStatus") or content.get("state")
                if not api_status:
                    resp_block = content.get("response", {})
                    api_status = resp_block.get("status") or (content.get("taskStatus"))

                if api_status in ("SUCCESS", "COMPLETED"):
                    log("• Status: completed")
                    # Hämta audioUrl
                    song_data_list = []
                    try:
                        resp_block = content.get("response", {})
                        if "sunoData" in resp_block:
                            song_data_list = resp_block["sunoData"]
                        elif "songs" in content:
                            song_data_list = content["songs"]
                    except Exception:
                        song_data_list = []

                    audio_url = None
                    if song_data_list and isinstance(song_data_list, list):
                        first = song_data_list[0]
                        audio_url = first.get("audioUrl")

                    # Fallback: leta efter http...mp3
                    if not audio_url:
                        text = json.dumps(data)
                        i = text.find("http")
                        if i != -1:
                            j = text.find(".mp3", i)
                            if j != -1:
                                audio_url = text[i:j+4]

                    if not audio_url:
                        item["status"] = "POLL_FAILED"
                        item["error_expl"] = "Kunde inte hitta audioUrl"
                        item["last_update"] = _ts()
                        with open(STATUS_FILE, "w", encoding="utf-8") as f:
                            json.dump(job_status, f, indent=2)
                        log(f"✗ Misslyckades hämta audioUrl för {job_id}")
                        break

                    # Ladda ner
                    fname = f"{index:03d}_{title.strip().replace(' ','_')}_v{variant}_{job_id}.mp3"
                    safe = "".join([c if c.isalnum() or c in "._-" else "_" for c in fname])
                    fpath = os.path.join("out", safe)
                    log(f"↓ Laddar ner MP3 → {safe}")
                    try:
                        rf = requests.get(audio_url, timeout=TIMEOUT_DOWNLOAD)
                        rf.raise_for_status()
                        with open(fpath, "wb") as f:
                            f.write(rf.content)
                    except Exception as e:
                        item["status"] = "POLL_FAILED"
                        item["error_code"] = "DOWNLOAD_ERR"
                        item["error_expl"] = f"Nedladdning misslyckades: {e}"
                        item["last_update"] = _ts()
                        with open(STATUS_FILE, "w", encoding="utf-8") as f:
                            json.dump(job_status, f, indent=2)
                        log(f"✗ Nedladdning misslyckades för {job_id}: {e}")
                        break

                    # Spara serverrespons
                    try:
                        with open(os.path.join("job", f"{job_id}.json"), "w", encoding="utf-8") as jf:
                            json.dump(data, jf, indent=2)
                    except Exception as e:
                        log(f"⚠️  Kunde inte spara serverrespons för {job_id}: {e}")

                    # Markera klar
                    item["status"] = "DONE"
                    item["last_update"] = _ts()
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    elapsed = int(time.time() - start_time)
                    log(f"✓ Klar ({elapsed}s). Fil: {os.path.abspath(fpath)}")
                    break

                elif api_status in ("CREATE_TASK_FAILED", "FAILED"):
                    item["status"] = "POLL_FAILED"
                    item["error_expl"] = "Jobb misslyckades i Suno API"
                    item["last_update"] = _ts()
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    log(f"✗ Jobb {job_id} rapporterades misslyckat av API.")
                    break

                else:
                    log("• Status: running")
                    time.sleep(2.0)
                    continue

            elif code == 401:
                item["status"] = "POLL_FAILED"
                item["error_code"] = 401
                item["error_expl"] = "Ogiltig API-nyckel (401)"
                item["last_update"] = _ts()
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                log(f"🚫 Jobb {job_id}: 401 Unauthorized under polling.")
                break

            elif code in (429, 405):
                sleep_time = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** (poll_attempts-1))) + random.uniform(0, JITTER_SEC)
                item["status"] = "RETRYING_RATE"
                item["error_code"] = 429
                item["next_retry_at"] = _ts()
                item["last_update"] = _ts()
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                log(f"… RETRYING_RATE (HTTP {code}) – retry om {sleep_time:.1f}s")
                time.sleep(sleep_time)
                item["status"] = "POLLING"
                continue

            elif code == 455:
                sleep_time = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** (poll_attempts-1))) + random.uniform(0, JITTER_SEC)
                item["status"] = "RETRYING_MAINT"
                item["error_code"] = 455
                item["next_retry_at"] = _ts()
                item["last_update"] = _ts()
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                log(f"… RETRYING_MAINT (HTTP 455) – retry om {sleep_time:.1f}s")
                time.sleep(sleep_time)
                item["status"] = "POLLING"
                continue

            elif 500 <= code < 600:
                sleep_time = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** (poll_attempts-1))) + random.uniform(0, JITTER_SEC)
                item["status"] = "RETRYING_SERVER"
                item["error_code"] = code
                item["next_retry_at"] = _ts()
                item["last_update"] = _ts()
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                log(f"… RETRYING_SERVER (HTTP {code}) – retry om {sleep_time:.1f}s")
                time.sleep(sleep_time)
                item["status"] = "POLLING"
                continue

            else:
                txt = (resp.text or "").strip()
                item["status"] = "POLL_FAILED"
                item["error_code"] = code
                item["error_expl"] = txt if txt else "Polling misslyckades"
                item["last_update"] = _ts()
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                log(f"✗ Jobb {job_id} polling misslyckades (HTTP {code}): {txt}")
                break

        else:
            # MAX_RETRIES_POLL
            item["status"] = "POLL_FAILED"
            item["error_code"] = "MAX_RETRIES"
            item["error_expl"] = "Timeout - gav upp efter många försök"
            item["last_update"] = _ts()
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(job_status, f, indent=2)
            log(f"✗ Jobb {job_id}: max retries utan resultat.")

    # Klarmarkera & arkivera
    job_status["meta"]["overall_status"] = "DONE"
    job_status["meta"]["note"] = "Polling klar."
    job_status["meta"]["completed_at"] = _ts()

    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(job_status, f, indent=2)

    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    archive = f"jobid_{ts}.json"
    try:
        os.replace(STATUS_FILE, archive)
    except Exception:
        try:
            import shutil
            shutil.copy2(STATUS_FILE, archive)
            os.remove(STATUS_FILE)
        except Exception as e:
            log(f"⚠️  Kunde inte arkivera {STATUS_FILE}: {e}")

    # Ta bort kvarvarande promptfil (create gör en kopia vid arkivering)
    if os.path.isfile("sunoprompt_aktiv.json"):
        try:
            os.remove("sunoprompt_aktiv.json")
        except Exception:
            pass

    log(f"✓ Arkiverade job-status → {archive}")
    log("✓ Städade aktiva statusfiler. Klart!")
    log("=== poll_songs.py klart ===")

if __name__ == "__main__":
    main()
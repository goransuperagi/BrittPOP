#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_songs.py — Robust Suno create med 503-hantering, loggning och tydlig status.
Windows-fokus. Kräver: requests (pip install requests), .env med SUNO_API_KEY.
"""

import os, sys, json, time, datetime, random
import requests

# ---------- Konfiguration & .env ----------

def load_env_envfile():
    """
    Liten .env-läsare: sätter os.environ om nycklar hittas i .env i aktuell katalog.
    Format: KEY=VALUE per rad. Ignorerar tomma rader och kommentarer (#).
    """
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

# Miljövariabler / standarder
SUNO_API_BASE = os.getenv("SUNO_API", "https://api.sunoapi.org").rstrip("/")
SUNO_API_GENERATE = f"{SUNO_API_BASE}/api/v1/generate"
TIMEOUT_CREATE = int(os.getenv("TIMEOUT_CREATE", "30"))

BACKOFF_BASE_SEC   = float(os.getenv("BACKOFF_BASE_SEC", "1.5"))
BACKOFF_CAP_SEC    = float(os.getenv("BACKOFF_CAP_SEC",  "30.0"))
JITTER_SEC         = float(os.getenv("JITTER_SEC",       "0.5"))
MAX_RETRIES_CREATE = int(os.getenv("MAX_RETRIES_CREATE", "6"))

PROMPT_FILE = "sunoprompt_aktiv.json"
STATUS_FILE = "jobid_aktiv.json"
LOG_FILE    = "log.txt"

# ---------- Logg ----------

_log_initialized = False

def _ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def init_log(reset=True):
    global _log_initialized
    mode = "w" if reset else "a"
    try:
        with open(LOG_FILE, mode, encoding="utf-8") as lf:
            lf.write(f"{_ts()} - === create_songs.py start ===\n")
            lf.write(f"{_ts()} - API_BASE={SUNO_API_BASE}  GENERATE={SUNO_API_GENERATE}\n")
        _log_initialized = True
    except Exception as e:
        print(f"⚠️  Kunde inte initiera logg: {e}")

def log(msg):
    global _log_initialized
    s = f"{_ts()} - {msg}"
    print(s)
    try:
        if not _log_initialized:
            init_log(reset=True)
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
    # redundans: försök läsa .env igen (om skriptet körts från annan katalog)
    load_env_envfile()
    return os.getenv("SUNO_API_KEY")

def parse_params(params_str):
    """
    Tolka 'key=value' par separerade med '|' eller ','.
    Returnerar dict.
    """
    out = {}
    if not params_str:
        return out
    # Tillåt båda skiljetecken
    parts = []
    if "|" in params_str:
        parts = params_str.split("|")
    elif "," in params_str:
        parts = params_str.split(",")
    else:
        parts = [params_str]
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def build_payload(entry):
    """
    Bygger payload för /generate baserat på promptpost.
    Standard (non-custom): endast 'prompt' skickas.
    Custom mode om entry innehåller 'customMode': true eller nycklarna 'style'/'instrumental'.
    I custom mode kräver vi 'title' och rekommenderar 'style' om instrumental inte är satt.
    Okända params läggs till i prompt-texten så de inte tappas bort.
    """
    title        = (entry.get("title") or "").strip()
    prompt_text  = (entry.get("prompt") or "").strip()
    params_text  = (entry.get("params") or "").strip()
    style        = entry.get("style")
    instrumental = entry.get("instrumental")
    custom_flag  = entry.get("customMode")

    # Parametrar i params-strängen
    pmap = parse_params(params_text)

    # Kända param-nycklar som vi kan mappa till payload
    # (håller kort för att undvika 400)
    if style is None and "style" in pmap:
        style = pmap["style"]
    if instrumental is None and "instrumental" in pmap:
        # tolka "true"/"false"
        val = pmap["instrumental"].lower()
        instrumental = True if val in ("1","true","yes","y") else False
    if custom_flag is None and "customMode" in pmap:
        val = pmap["customMode"].lower()
        custom_flag = True if val in ("1","true","yes","y") else False

    # Upptäck custom-mode
    is_custom = bool(custom_flag) or (style is not None) or (instrumental is not None)

    # Lägg okända params in i prompten som text-hints (så de inte tappas bort)
    known_keys = {"style", "instrumental", "customMode"}
    unknown = []
    if pmap:
        for k, v in pmap.items():
            if k not in known_keys:
                unknown.append(f"{k}={v}")
    if unknown:
        # Appendera tydligt men kort
        prompt_text = (prompt_text + " || " + " ".join(unknown)).strip()

    if not prompt_text:
        return None, "tom prompt"

    if not is_custom:
        # Non-custom (säkraste vägen)
        payload = {"prompt": prompt_text}
        return payload, None

    # Custom-mode: kräver title
    if not title:
        return None, "customMode kräver title i promptposten"
    payload = {
        "customMode": True,
        "title": title,
        "prompt": prompt_text
    }
    if style is not None:
        payload["style"] = style
    if instrumental is not None:
        payload["instrumental"] = bool(instrumental)
    return payload, None

# ---------- Körning ----------

def main():
    init_log(reset=True)
    ensure_directories()

    api_key = load_api_key()
    if not api_key:
        log("🚫 SUNO_API_KEY saknas. Lägg den i .env (SUNO_API_KEY=...)")
        sys.exit(1)

    if not os.path.isfile(PROMPT_FILE):
        log(f"🚫 Hittar inte {PROMPT_FILE}. Skapa filen och försök igen.")
        sys.exit(1)

    # Läs promptlista
    try:
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            prompt_data = json.load(f)
    except Exception as e:
        log(f"🚫 Kunde inte läsa {PROMPT_FILE}: {e}")
        sys.exit(1)

    prompts = prompt_data.get("prompts", [])
    meta    = prompt_data.get("meta", {})
    default_count = meta.get("default_count", 1)
    if not isinstance(default_count, int) or default_count < 1:
        default_count = 1

    # Statusstruktur
    job_status = {
        "meta": {
            "created_at": _ts(),
            "overall_status": "CREATING",
            "note": "Startar jobb mot Suno API...",
            "api_base": SUNO_API_BASE
        },
        "items": []
    }
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(job_status, f, indent=2)

    total_jobs = 0
    for entry in prompts:
        c = entry.get("count", default_count)
        if not isinstance(c, int) or c < 1:
            c = 1
        total_jobs += c

    log(f"• Startar jobb mot API: {SUNO_API_GENERATE}")
    log(f"• Antal renderingar som skapas: {total_jobs}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    job_counter = 0
    for idx, entry in enumerate(prompts, start=1):
        title       = (entry.get("title") or "Untitled").strip()
        count       = entry.get("count", default_count)
        if not isinstance(count, int) or count < 1:
            count = 1

        for variant in range(1, count + 1):
            job_counter += 1
            # Bygg payload
            payload, perr = build_payload(entry)
            item = {
                "index": idx,
                "variant": variant,
                "title": title,
                "prompt_text": (entry.get("prompt") or "").strip(),
                "job_id": None,
                "phase": "CREATE",
                "status": "CREATING",
                "http_status": None,
                "error_code": None,
                "error_expl": None,
                "retries": 0,
                "next_retry_at": None,
                "last_update": _ts()
            }
            job_status["items"].append(item)
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(job_status, f, indent=2)

            if perr:
                item["status"] = "CREATE_FAILED"
                item["error_code"] = 400
                item["error_expl"] = perr
                item["last_update"] = _ts()
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                log(f"✗ [{job_counter}/{total_jobs}] Skippade (payload-fel): {perr}")
                continue

            # Retry-loop
            attempt = 0
            while attempt < MAX_RETRIES_CREATE:
                attempt += 1
                item["retries"] = attempt - 1
                item["last_update"] = _ts()
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)

                try:
                    log(f"• [{job_counter}/{total_jobs}] Skickar create för \"{title}\" (försök {attempt})...")
                    resp = requests.post(SUNO_API_GENERATE, headers=headers, json=payload, timeout=TIMEOUT_CREATE)
                except Exception as e:
                    item["status"] = "CREATE_FAILED"
                    item["error_code"] = "EXC"
                    item["error_expl"] = f"Nätverksfel: {e}"
                    item["last_update"] = _ts()
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    log(f"✗ [{job_counter}/{total_jobs}] Nätverksfel: {e}")
                    break

                code = resp.status_code
                item["http_status"] = code

                # === Framgång ===
                if code == 200:
                    data = {}
                    try:
                        data = resp.json()
                    except:
                        pass

                    inner = data.get("code")
                    if inner and inner != 200:
                        # API svarade fel trots HTTP 200 (ovanligt men förekommer)
                        msg = data.get("msg") or data.get("message") or "API-rapport fel"
                        item["status"] = "CREATE_FAILED"
                        item["error_code"] = inner
                        item["error_expl"] = msg
                        item["last_update"] = _ts()
                        with open(STATUS_FILE, "w", encoding="utf-8") as f:
                            json.dump(job_status, f, indent=2)
                        log(f"✗ [{job_counter}/{total_jobs}] API fel (code {inner}): {msg}")
                        break

                    task_id = data.get("data", {}).get("taskId")
                    if task_id:
                        item["job_id"] = task_id
                        item["status"] = "QUEUED"
                        item["last_update"] = _ts()
                        with open(STATUS_FILE, "w", encoding="utf-8") as f:
                            json.dump(job_status, f, indent=2)
                        log(f"✓ [{job_counter}/{total_jobs}] Startade job {task_id}  ({title} v{variant})")
                        break
                    else:
                        # 200 utan taskId => behandla som fel
                        msg = data.get("msg") or "Okänt fel (saknar taskId)"
                        item["status"] = "CREATE_FAILED"
                        item["error_code"] = 200
                        item["error_expl"] = msg
                        item["last_update"] = _ts()
                        with open(STATUS_FILE, "w", encoding="utf-8") as f:
                            json.dump(job_status, f, indent=2)
                        log(f"✗ [{job_counter}/{total_jobs}] 200 utan taskId: {msg}")
                        break

                # === Permanenta fel ===
                if code == 401:
                    item["status"] = "CREATE_FAILED"
                    item["error_code"] = 401
                    item["error_expl"] = "Ogiltig API-nyckel (401)"
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    log(f"🚫 [{job_counter}/{total_jobs}] 401 Unauthorized – kontrollera SUNO_API_KEY i .env")
                    job_status["meta"]["overall_status"] = "CREATE_FAILED"
                    job_status["meta"]["note"] = "Fel API-nyckel. Avbröt skapande."
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    sys.exit(1)

                if code == 413:
                    item["status"] = "CREATE_FAILED"
                    item["error_code"] = 413
                    item["error_expl"] = "prompt för lång (413)"
                    item["last_update"] = _ts()
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    log(f"✗ [{job_counter}/{total_jobs}] 413 Payload Too Large – korta prompten.")
                    break

                # === Ratelimit/krediter ===
                if code in (429, 405):
                    text = ""
                    try:
                        text = resp.text or ""
                    except:
                        pass
                    if "credit" in text.lower() or "insufficient" in text.lower():
                        item["status"] = "ON_HOLD_CREDITS"
                        item["error_code"] = 429
                        item["error_expl"] = "Slut på krediter"
                        item["last_update"] = _ts()
                        with open(STATUS_FILE, "w", encoding="utf-8") as f:
                            json.dump(job_status, f, indent=2)
                        log(f"🚫 [{job_counter}/{total_jobs}] Inga krediter kvar – avbryter.")
                        job_status["meta"]["overall_status"] = "ON_HOLD_CREDITS"
                        job_status["meta"]["note"] = "Avbruten - saknar krediter."
                        with open(STATUS_FILE, "w", encoding="utf-8") as f:
                            json.dump(job_status, f, indent=2)
                        sys.exit(1)
                    # vanlig ratelimit -> backoff
                    sleep_time = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** (attempt-1))) + random.uniform(0, JITTER_SEC)
                    item["status"] = "RETRYING_RATE"
                    item["error_code"] = 429
                    item["next_retry_at"] = (_ts())
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    log(f"… RETRYING_RATE (HTTP {code}) – retry om {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                    item["status"] = "CREATING"
                    continue

                # === Underhåll ===
                if code == 455:
                    sleep_time = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** (attempt-1))) + random.uniform(0, JITTER_SEC)
                    item["status"] = "RETRYING_MAINT"
                    item["error_code"] = 455
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    log(f"… RETRYING_MAINT (HTTP 455) – underhåll – retry om {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                    item["status"] = "CREATING"
                    continue

                # === Serverfel (inkl. 503) ===
                if 500 <= code < 600:
                    sleep_time = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** (attempt-1))) + random.uniform(0, JITTER_SEC)
                    item["status"] = "RETRYING_SERVER"
                    item["error_code"] = code
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    log(f"… RETRYING_SERVER (HTTP {code}) – retry om {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                    item["status"] = "CREATING"
                    continue

                # === Övriga fel (400, 404, m.fl.) ===
                msg = (resp.text or "").strip()
                item["status"] = "CREATE_FAILED"
                item["error_code"] = code
                item["error_expl"] = msg if msg else "Okänt fel"
                item["last_update"] = _ts()
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                log(f"✗ [{job_counter}/{total_jobs}] HTTP {code} – {msg}")
                break

            # Max retries? markera misslyckat
            if item["status"] in ("CREATING", "RETRYING_RATE", "RETRYING_MAINT", "RETRYING_SERVER"):
                item["status"] = "CREATE_FAILED"
                item["error_code"] = "MAX_RETRIES"
                item["error_expl"] = "Max försök uppnådda"
                item["last_update"] = _ts()
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                log(f"✗ [{job_counter}/{total_jobs}] Misslyckades efter max försök.")

    # Summera
    all_failed = all(itm["status"] in ("CREATE_FAILED","ON_HOLD_CREDITS") for itm in job_status["items"]) or (len(job_status["items"])==0)
    if all_failed:
        job_status["meta"]["overall_status"] = "CREATE_FAILED"
        job_status["meta"]["note"] = "Inga jobb startades. Se fel i listan."
    else:
        job_status["meta"]["overall_status"] = "READY_TO_POLL"
        job_status["meta"]["note"] = "Skapade jobb - redo för polling."
    job_status["meta"]["last_create"] = _ts()

    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(job_status, f, indent=2)

    # Arkivera
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    archive_prompt = f"sp_{ts}.json"
    archive_jobids = f"jobid_{ts}.json"
    try:
        # kopiera promptfilen (behåll original om man vill loopa manuellt)
        if os.path.isfile(PROMPT_FILE):
            import shutil
            shutil.copy2(PROMPT_FILE, archive_prompt)
        with open(archive_jobids, "w", encoding="utf-8") as f:
            json.dump(job_status, f, indent=2)
        log(f"✓ Arkiverade prompts → {archive_prompt}")
        log(f"✓ Arkiverade job IDs → {archive_jobids}")
    except Exception as e:
        log(f"⚠️  Arkivering misslyckades: {e}")

    log("=== create_songs.py klart ===")

if __name__ == "__main__":
    main()
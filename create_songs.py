import os, sys, json, time, datetime, random
import requests  # Kräv denna modul (pip install requests) för HTTP-anrop

# Konstanter för exponential backoff (kan justeras via .env om så önskas)
BACKOFF_BASE_SEC = float(os.getenv("BACKOFF_BASE_SEC", 1.5))
BACKOFF_CAP_SEC  = float(os.getenv("BACKOFF_CAP_SEC", 30.0))
JITTER_SEC       = float(os.getenv("JITTER_SEC", 0.5))
MAX_RETRIES_CREATE = int(os.getenv("MAX_RETRIES_CREATE", 6))

# Suno API-slutpunkt (generera musik)
SUNO_API_URL = "https://api.suno.ai/api/v1/generate"  # alternativt api.sunoapi.org, bägge fungerar

def load_api_key():
    """Läs API-nyckel från miljövariabel eller .env-fil."""
    api_key = os.getenv("SUNO_API_KEY")
    if api_key:
        return api_key
    # Om inte satt som miljövariabel, försök läsa .env-fil
    if os.path.isfile(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("SUNO_API_KEY"):
                        # Hämta nyckeln efter '=' och eventuella citationstecken
                        key = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                        if key:
                            return key
        except Exception as e:
            print(f"Fel: Kunde inte läsa .env-fil ({e})")
    return None

def ensure_directories():
    """Skapa utdata-mappar om de inte finns."""
    if not os.path.isdir("out"):
        os.makedirs("out")
    if not os.path.isdir("job"):
        os.makedirs("job")

# Ladda API-nyckel och validera
API_KEY = load_api_key()
if not API_KEY:
    print("🚫 SUNO_API_KEY saknas. Vänligen ange API-nyckel i .env.")
    sys.exit(1)

# Kontrollera att promptfilen finns
PROMPT_FILE = "sunoprompt_aktiv.json"
if not os.path.isfile(PROMPT_FILE):
    print(f"🚫 Hittar inte {PROMPT_FILE}. Skapa filen med dina låtprompter och försök igen.")
    sys.exit(1)

# Skapa utdata-mappar om de saknas
ensure_directories()

# Läs in promptlistan
with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    prompt_data = json.load(f)

prompts = prompt_data.get("prompts", [])
meta = prompt_data.get("meta", {})
default_count = meta.get("default_count", 1)
if not isinstance(default_count, int):
    default_count = 1

# Förbered jobid_aktiv.json struktur
job_status = {
    "meta": {
        "created_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_status": "CREATING",
        "note": "Startar jobb mot Suno API..."
    },
    "items": []
}

# Spara initial statusfil
with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
    json.dump(job_status, f, indent=2)

total_jobs = 0
# Räkna totala antal renderingar (varianter) som ska skapas
for entry in prompts:
    count = entry.get("count", None)
    if count is None:
        count = default_count
    if not isinstance(count, int) or count < 1:
        count = 1
    total_jobs += count

print(f"• Startar jobb mot API: {SUNO_API_URL}")
print(f"• Antal renderingar som skapas: {total_jobs}")

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

job_counter = 0  # räknare för hur många jobb som påbörjats
for idx, entry in enumerate(prompts, start=1):
    title = entry.get("title", "Untitled").strip()
    prompt_text = entry.get("prompt", "").strip()
    params_text = entry.get("params", "").strip()
    count = entry.get("count", None)
    if count is None:
        count = default_count
    if not isinstance(count, int) or count < 1:
        count = 1

    for variant in range(1, count + 1):
        job_counter += 1
        item = {
            "index": idx,
            "variant": variant,
            "title": title,
            "prompt_text": prompt_text + (" || " + params_text if params_text else ""),
            "job_id": None,
            "phase": "CREATE",
            "status": "CREATING",
            "http_status": None,
            "error_code": None,
            "error_expl": None,
            "retries": 0,
            "next_retry_at": None,
            "last_update": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        # Lägg till item i statuslistan och skriv till fil
        job_status["items"].append(item)
        with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
            json.dump(job_status, f, indent=2)

        # Förbered API-anrop
        payload = {
            "prompt": prompt_text  # använd prompt-texten; params hanteras ev. av modellen implicit
        }
        # Inkludera titel om customMode (men vi kör prompt baserat läge)
        # payload["title"] = title  # valfritt, inte nödvändigt om customMode=False
        # payload["customMode"] = False  # standard (bara prompt behövs)

        attempt = 0
        wait = BACKOFF_BASE_SEC
        # Loop för retries vid temporära fel
        while attempt < MAX_RETRIES_CREATE:
            attempt += 1
            item["retries"] = attempt - 1  # retries räknar antalet gjorda omförsök (innan nuvarande)
            item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            # Uppdatera statusfil (innan anrop)
            with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                json.dump(job_status, f, indent=2)
            try:
                response = requests.post(SUNO_API_URL, headers=headers, json=payload, timeout=30)
            except Exception as e:
                # Om nätverksfel/exception, markera som create_failed
                item["status"] = "CREATE_FAILED"
                item["error_code"] = "EXCEPTION"
                item["error_expl"] = "Nätverksfel vid API-anrop"
                item["http_status"] = None
                item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                # Skriv status och hoppa ur
                with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                print(f"✗ [{job_counter}/{total_jobs}] Misslyckades (nätverksfel).")
                break

            code = response.status_code
            item["http_status"] = code

            # Kolla olika svarskoder
            if code == 200:
                # Förväntat: API anrop lyckades, hämta job_id
                data = response.json()
                # API kan returnera JSON med "data": {"taskId": "..."}
                task_id = None
                if isinstance(data, dict):
                    # vissa fel kan också komma med code != 200 i JSON även om HTTP 200
                    inner_code = data.get("code")
                    if inner_code and inner_code != 200:
                        # API svarade med fel trots HTTP 200 (t.ex. felaktiga parametrar)
                        # Behandla som fel (ex: 413 prompt för lång kan komma så här)
                        code = inner_code
                    else:
                        task_id = data.get("data", {}).get("taskId")
                if task_id:
                    # Spara job_id och markera som köad för polling
                    item["job_id"] = task_id
                    item["status"] = "QUEUED"
                    item["error_code"] = None
                    item["error_expl"] = None
                    item["phase"] = "CREATE"
                    item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    # Uppdatera fil och terminal
                    with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    print(f"✓ [{job_counter}/{total_jobs}] Startade job {task_id}  ({title} v{variant})")
                    break  # gå vidare till nästa jobb
                else:
                    # Om inget task_id trots 200, hantera som okänt fel
                    err_msg = data.get("msg") if isinstance(data, dict) else "Okänt fel"
                    item["status"] = "CREATE_FAILED"
                    item["error_code"] = code
                    item["error_expl"] = err_msg
                    item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    print(f"✗ [{job_counter}/{total_jobs}] Jobb ej startat. Fel: {err_msg}")
                    break

            elif code == 401:
                # Felaktig API-nyckel
                item["status"] = "CREATE_FAILED"
                item["error_code"] = 401
                item["error_expl"] = "korrigera .env (ogiltig API-nyckel)"
                item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                print(f"🚫 [{job_counter}/{total_jobs}] 401 Unauthorized – API-nyckel saknas/ogiltig.")
                # Vid 401 avbryter vi resten direkt, alla kommer misslyckas
                # Sätt overall_status till FAILED och avsluta.
                job_status["meta"]["overall_status"] = "CREATE_FAILED"
                job_status["meta"]["note"] = "Fel API-nyckel. Avbröt skapande."
                with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                sys.exit(1)

            elif code == 429 or code == 405:
                # Rate-limit eller slut på krediter. 
                # API kan använda 429 för båda (eller 405 för ratelimit enligt dokumentation).
                error_text = ""
                try:
                    data = response.json()
                    error_text = str(data)
                except:
                    error_text = response.text or ""
                # Kontrollera om svaret nämner "credit"
                if "credit" in error_text.lower() or "insufficient" in error_text.lower():
                    # Slut på krediter
                    item["status"] = "ON_HOLD_CREDITS"
                    item["error_code"] = 429
                    item["error_expl"] = "fyll på krediter (slut på Suno-krediter)"
                    item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    print(f"🚫 [{job_counter}/{total_jobs}] ON_HOLD_CREDITS – inga krediter kvar. Avbryter.")
                    # Bryt här – inga fler försök för denna eller efterföljande jobb
                    # (Alla återstående jobb markeras ej startade pga kreditbrist)
                    # Markera kommande jobb som inställda om några kvar?
                    # (Här förenklat: vi avbryter helt)
                    job_status["meta"]["overall_status"] = "ON_HOLD_CREDITS"
                    job_status["meta"]["note"] = "Avbruten - saknar krediter."
                    with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    sys.exit(1)
                else:
                    # Vanlig rate-limit: försök igen efter en backoff
                    item["status"] = "RETRYING_RATE"
                    # Beräkna backoff med jitter
                    sleep_time = min(BACKOFF_CAP_SEC, wait * (2 ** (attempt-1)))
                    sleep_time = sleep_time + random.uniform(0, JITTER_SEC)
                    item["next_retry_at"] = (datetime.datetime.utcnow() + datetime.timedelta(seconds=sleep_time)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    item["error_code"] = 429
                    item["error_expl"] = None
                    item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    # Uppdatera statusfil innan väntan
                    with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    print(f"… RETRYING_RATE (HTTP {code}) – Rate-limit – retry om {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                    # Återställ status till CREATING inför nästa försök
                    item["status"] = "CREATING"
                    continue  # försök igen

            elif code == 455:
                # Underhåll pågår - tillfälligt fel, försök igen senare
                item["status"] = "RETRYING_MAINT"
                sleep_time = min(BACKOFF_CAP_SEC, wait * (2 ** (attempt-1)))
                sleep_time = sleep_time + random.uniform(0, JITTER_SEC)
                item["next_retry_at"] = (datetime.datetime.utcnow() + datetime.timedelta(seconds=sleep_time)).strftime("%Y-%m-%dT%H:%M:%SZ")
                item["error_code"] = 455
                item["error_expl"] = None
                item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                print(f"… RETRYING_MAINT (HTTP 455) – Underhåll – retry om {sleep_time:.1f}s")
                time.sleep(sleep_time)
                item["status"] = "CREATING"
                continue

            elif 500 <= code < 600:
                # Serverfel, försök igen
                item["status"] = "RETRYING_SERVER"
                sleep_time = min(BACKOFF_CAP_SEC, wait * (2 ** (attempt-1)))
                sleep_time = sleep_time + random.uniform(0, JITTER_SEC)
                item["next_retry_at"] = (datetime.datetime.utcnow() + datetime.timedelta(seconds=sleep_time)).strftime("%Y-%m-%dT%H:%M:%SZ")
                item["error_code"] = code
                item["error_expl"] = None
                item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                print(f"… RETRYING_SERVER (HTTP {code}) – Serverfel – retry om {sleep_time:.1f}s")
                time.sleep(sleep_time)
                item["status"] = "CREATING"
                continue

            elif code == 413:
                # Prompt för lång eller annan parameter överskrider gräns
                item["status"] = "CREATE_FAILED"
                item["error_code"] = 413
                item["error_expl"] = "korta prompten (413 Request Too Large)"
                item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                print(f"✗ [{job_counter}/{total_jobs}] 413 Payload Too Large – prompten är för lång.")
                break

            else:
                # Övriga fel (400, 404, etc) – hanteras som permanent fel
                err_text = ""
                try:
                    err_json = response.json()
                    # hämta ev. meddelande
                    if isinstance(err_json, dict):
                        err_text = err_json.get("msg") or err_json.get("message") or str(err_json)
                    else:
                        err_text = str(err_json)
                except:
                    err_text = response.text or ""
                item["status"] = "CREATE_FAILED"
                item["error_code"] = code
                item["error_expl"] = err_text if err_text else "Okänt fel"
                item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                print(f"✗ [{job_counter}/{total_jobs}] HTTP {code} – Jobb misslyckades: {err_text}")
                break
        # while-loop slut (retry attempts)

        # Om MAX_RETRIES_CREATE överskreds utan success:
        if item["status"] in ("CREATING", "RETRYING_RATE", "RETRYING_MAINT", "RETRYING_SERVER"):
            # Markera som misslyckat om vi brutit ut med status kvar i retriable state
            item["status"] = "CREATE_FAILED"
            if item["error_code"] is None:
                item["error_code"] = "MAX_RETRIES"
            if item["error_expl"] is None:
                item["error_expl"] = "Max antal försök uppnått"
            item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
                json.dump(job_status, f, indent=2)
            print(f"✗ [{job_counter}/{total_jobs}] Misslyckades efter maximalt antal försök.")

# När alla jobb har behandlats:
# Uppdatera overall_status beroende på resultat
all_failed = all(itm["status"] in ["CREATE_FAILED", "ON_HOLD_CREDITS"] for itm in job_status["items"])
if all_failed:
    job_status["meta"]["overall_status"] = "CREATE_FAILED"
    job_status["meta"]["note"] = "Inga jobb startades. Se fel i listan."
else:
    job_status["meta"]["overall_status"] = "READY_TO_POLL"
    job_status["meta"]["note"] = "Skapade jobb - redo för polling."

job_status["meta"]["last_create"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

# Skriv slutligt jobid_aktiv.json efter create-fasen
with open("jobid_aktiv.json", "w", encoding="utf-8") as f:
    json.dump(job_status, f, indent=2)

# Arkivera sunoprompt_aktiv.json och jobid_aktiv-listan med tidsstämplar
timestamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
archive_prompt = f"sp_{timestamp}.json"
archive_jobids = f"jobid_{timestamp}.json"
try:
    os.replace(PROMPT_FILE, archive_prompt)
except:
    # om os.replace inte fungerar (t.ex. olika diskar), försök copy+remove
    try:
        import shutil
        shutil.copy2(PROMPT_FILE, archive_prompt)
        os.remove(PROMPT_FILE)
    except Exception as e:
        print(f"⚠️ Kunde inte arkivera {PROMPT_FILE}: {e}")
        # fortsätt ändå
try:
    with open(archive_jobids, "w", encoding="utf-8") as f:
        json.dump(job_status, f, indent=2)
except Exception as e:
    print(f"⚠️ Kunde inte arkivera jobid_aktiv.json: {e}")

print(f"✓ Arkiverade prompts → {archive_prompt}")
print(f"✓ Arkiverade job IDs → {archive_jobids}")

# Klart med create-fasen

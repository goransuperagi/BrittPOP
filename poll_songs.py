import os, sys, json, time, datetime, random
import requests

# Konstanter för exponential backoff (kan justeras via .env)
BACKOFF_BASE_SEC = float(os.getenv("BACKOFF_BASE_SEC", 1.5))
BACKOFF_CAP_SEC  = float(os.getenv("BACKOFF_CAP_SEC", 30.0))
JITTER_SEC       = float(os.getenv("JITTER_SEC", 0.5))
MAX_RETRIES_POLL = int(os.getenv("MAX_RETRIES_POLL", 1000))

# Ladda API-nyckel (samma funktion som i create_songs.py)
def load_api_key():
    api_key = os.getenv("SUNO_API_KEY")
    if api_key:
        return api_key
    if os.path.isfile(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("SUNO_API_KEY"):
                        key = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                        if key:
                            return key
        except:
            pass
    return None

API_KEY = load_api_key()
if not API_KEY:
    print("🚫 SUNO_API_KEY saknas. Kontrollera .env och försök igen.")
    sys.exit(1)

STATUS_FILE = "jobid_aktiv.json"
if not os.path.isfile(STATUS_FILE):
    print(f"🚫 Hittar inte {STATUS_FILE}. Kör först create_songs.py för att starta jobb.")
    sys.exit(1)

# Skapa utdata-mappar om de inte finns
if not os.path.isdir("out"):
    os.makedirs("out")
if not os.path.isdir("job"):
    os.makedirs("job")

# Läs in jobid_aktiv-status
with open(STATUS_FILE, "r", encoding="utf-8") as f:
    job_status = json.load(f)

# Sätt overall_status = POLLING och uppdatera notering
job_status["meta"]["overall_status"] = "POLLING"
job_status["meta"]["note"] = "Pollar Suno efter färdiga låtar..."
job_status["meta"]["poll_started"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

# Uppdatera alla items phase till POLL om de har ett job_id
for item in job_status.get("items", []):
    if item.get("job_id"):
        item["phase"] = "POLL"
        # Endast om status var QUEUED, sätt till POLLING
        if item.get("status") in ["QUEUED", "CREATING"]:
            item["status"] = "POLLING"
        item["retries"] = 0
        item["next_retry_at"] = None
        item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        # Inget job_id (t.ex. ON_HOLD_CREDITS eller CREATE_FAILED) -> hoppa över polling
        item["phase"] = "CREATE"
        # Låt status vara oförändrad (CREATE_FAILED / ON_HOLD_CREDITS)
        item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

# Spara uppdaterad statusfil
with open(STATUS_FILE, "w", encoding="utf-8") as f:
    json.dump(job_status, f, indent=2)

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

print("▶ Börjar polling av jobb...")

for item in job_status.get("items", []):
    job_id = item.get("job_id")
    if not job_id:
        # Hoppa över poster som saknar jobb-id (de lyckades aldrig starta)
        continue

    title = item.get("title", "Untitled")
    variant = item.get("variant", 1)
    index = item.get("index", 0)
    print(f"▶ Börjar polla {title} v{variant} ({job_id}) ...")

    poll_attempts = 0
    status_obtained = None
    start_time = time.time()

    # Poll-loop för detta jobb
    while poll_attempts < MAX_RETRIES_POLL:
        poll_attempts += 1
        item["retries"] = poll_attempts
        item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        # Uppdatera statusfil varje iteration med aktuell retries/last_update
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(job_status, f, indent=2)
        try:
            resp = requests.get(f"https://api.suno.ai/api/v1/generate/record-info?taskId={job_id}",
                                headers=headers, timeout=15)
        except Exception as e:
            # Nätverksfel vid polling, vänta lite och försök igen
            item["status"] = "POLLING"
            # notera ej permanent fel, så inget error_code/expl
            time.sleep(2.0)
            continue

        code = resp.status_code
        item["http_status"] = code

        if code == 200:
            data = {}
            try:
                data = resp.json()
            except:
                data = {}
            # Kolla om API-svar indikerar färdig status
            api_status = None
            error_code = None
            error_msg = None
            if isinstance(data, dict):
                # Vissa API-svar har "code" och "msg"
                inner_code = data.get("code")
                if inner_code and inner_code != 200:
                    # API-returnerad fel trots HTTP 200 (t.ex. slut på tid?)
                    error_code = inner_code
                    error_msg = data.get("msg") or data.get("message")
                content = data.get("data", {})
                api_status = content.get("status") or content.get("taskStatus") or content.get("state")
                # Ibland kanske "status" kan vara None om ej hittas
                if not api_status:
                    # kolla i "response" om sådant fält finns
                    resp_content = content.get("response", {})
                    api_status = content.get("taskStatus") or resp_content.get("status")

            else:
                api_status = None

            # Om API-svaret har explicit felkod
            if error_code:
                # Behandla som fail
                code = error_code

            if api_status:
                # Skriv ut status (endast "running" vs "completed" förenklat)
                if api_status in ["SUCCESS", "COMPLETED"]:
                    print("• Status: completed")
                    status_obtained = "completed"
                elif api_status in ["CREATE_TASK_FAILED", "FAILED"]:
                    print("• Status: failed (API)")
                    status_obtained = "failed"
                else:
                    # Fortfarande pågående
                    print("• Status: running")
                # Om status inte klar och inte fail, fortsätt polling
            else:
                # Om vi inte fick en status i svaret alls, behandla som att det inte är klart
                print("• Status: running")

            if status_obtained == "completed":
                # Klart - ladda ner låt
                item["status"] = "DOWNLOADING"
                item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                # Hämta URL för MP3 från svaret
                song_data_list = []
                try:
                    # Plocka ut sunoData-listan från svaret
                    content = data.get("data", {})
                    response_block = content.get("response", {})
                    if "sunoData" in response_block:
                        song_data_list = response_block["sunoData"]
                    elif "songs" in content:
                        song_data_list = content["songs"]
                except Exception as e:
                    song_data_list = []
                # Använd första låten om flera returneras
                audio_url = None
                if song_data_list and isinstance(song_data_list, list):
                    first_song = song_data_list[0]
                    audio_url = first_song.get("audioUrl")
                # Fallback om data-struktur annorlunda
                if not audio_url:
                    # försök hitta "audioUrl" i JSON genom att genomsöka
                    text = json.dumps(data)
                    idx = text.find("http")
                    if idx != -1:
                        # Ta ut första URL som slutar med .mp3
                        start = text.find("http", idx)
                        end = text.find(".mp3", start)
                        if end != -1:
                            audio_url = text[start:end+4]
                if not audio_url:
                    item["status"] = "POLL_FAILED"
                    item["error_code"] = None
                    item["error_expl"] = "Kunde inte hitta audioUrl"
                    item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    print(f"✗ Misslyckades hämta ljudURL för job {job_id}")
                    break

                # Ladda ner MP3-filen
                filename = f"{index:03d}_{title.strip().replace(' ', '_')}_v{variant}_{job_id}.mp3"
                # Rensa olämpliga tecken i filnamn
                safe_filename = "".join([c if c.isalnum() or c in "._-" else "_" for c in filename])
                file_path = os.path.join("out", safe_filename)
                print(f"↓ Laddar ner MP3 → {safe_filename}")
                try:
                    res_file = requests.get(audio_url, timeout=120)
                    res_file.raise_for_status()
                    with open(file_path, "wb") as f:
                        f.write(res_file.content)
                except Exception as e:
                    item["status"] = "POLL_FAILED"
                    item["error_code"] = "DOWNLOAD_ERR"
                    item["error_expl"] = "Nedladdning misslyckades"
                    item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    with open(STATUS_FILE, "w", encoding="utf-8") as f:
                        json.dump(job_status, f, indent=2)
                    print(f"✗ Nedladdning misslyckades för job {job_id}: {e}")
                    break

                # Spara hela server-responsen i job/<jobid>.json
                try:
                    with open(os.path.join("job", f"{job_id}.json"), "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                except Exception as e:
                    print(f"⚠️ Kunde inte spara serverrespons för job {job_id}: {e}")

                # Markera som klar
                item["status"] = "DONE"
                item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                # Skriv uppdatering till statusfil
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                elapsed = time.time() - start_time
                print(f"✓ Klar ({int(elapsed)}s). Fil: {os.path.abspath(file_path)}")
                break

            elif status_obtained == "failed":
                # API rapporterar att genereringen misslyckats
                item["status"] = "POLL_FAILED"
                item["error_code"] = None
                item["error_expl"] = "Jobb misslyckades i Suno API"
                item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(job_status, f, indent=2)
                print(f"✗ Jobb {job_id} rapporterades misslyckat av API.")
                break

            # Annars (om inte completed/failed) fortsätt polling efter en kort paus
            time.sleep(2.0)
            continue

        elif code == 401:
            # Obehörighet under polling (borde inte hända om nyckel var korrekt tidigare)
            item["status"] = "POLL_FAILED"
            item["error_code"] = 401
            item["error_expl"] = "korrigera .env (ogiltig API-nyckel)"
            item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(job_status, f, indent=2)
            print(f"🚫 Jobb {job_id}: 401 Unauthorized under polling. Avbryter.")
            break  # hoppa ur polling för detta jobb

        elif code == 429 or code == 405:
            # Rate limit under polling - försök igen
            item["status"] = "RETRYING_RATE"
            sleep_time = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** (poll_attempts-1)))
            sleep_time = sleep_time + random.uniform(0, JITTER_SEC)
            item["next_retry_at"] = (datetime.datetime.utcnow() + datetime.timedelta(seconds=sleep_time)).strftime("%Y-%m-%dT%H:%M:%SZ")
            item["error_code"] = 429
            item["error_expl"] = None
            item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(job_status, f, indent=2)
            print(f"… RETRYING_RATE (HTTP {code}) – Rate-limit – retry om {sleep_time:.1f}s")
            time.sleep(sleep_time)
            # Återställ status till POLLING inför nästa försök
            item["status"] = "POLLING"
            continue

        elif code == 455:
            # Underhåll under polling
            item["status"] = "RETRYING_MAINT"
            sleep_time = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** (poll_attempts-1)))
            sleep_time = sleep_time + random.uniform(0, JITTER_SEC)
            item["next_retry_at"] = (datetime.datetime.utcnow() + datetime.timedelta(seconds=sleep_time)).strftime("%Y-%m-%dT%H:%M:%SZ")
            item["error_code"] = 455
            item["error_expl"] = None
            item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(job_status, f, indent=2)
            print(f"… RETRYING_MAINT (HTTP 455) – Underhåll – retry om {sleep_time:.1f}s")
            time.sleep(sleep_time)
            item["status"] = "POLLING"
            continue

        elif 500 <= code < 600:
            # Serverfel under polling
            item["status"] = "RETRYING_SERVER"
            sleep_time = min(BACKOFF_CAP_SEC, BACKOFF_BASE_SEC * (2 ** (poll_attempts-1)))
            sleep_time = sleep_time + random.uniform(0, JITTER_SEC)
            item["next_retry_at"] = (datetime.datetime.utcnow() + datetime.timedelta(seconds=sleep_time)).strftime("%Y-%m-%dT%H:%M:%SZ")
            item["error_code"] = code
            item["error_expl"] = None
            item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(job_status, f, indent=2)
            print(f"… RETRYING_SERVER (HTTP {code}) – Serverfel – retry om {sleep_time:.1f}s")
            time.sleep(sleep_time)
            item["status"] = "POLLING"
            continue

        else:
            # Andra felkoder (404 etc) - avbryt polling för detta jobb
            err_text = resp.text
            item["status"] = "POLL_FAILED"
            item["error_code"] = code
            item["error_expl"] = err_text.strip() if err_text else "Polling misslyckades"
            item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(job_status, f, indent=2)
            print(f"✗ Jobb {job_id} polling misslyckades (HTTP {code}): {err_text}")
            break

    else:
        # Om MAX_RETRIES_POLL nåtts utan completion
        item["status"] = "POLL_FAILED"
        item["error_code"] = "MAX_RETRIES"
        item["error_expl"] = "Timeout - gav upp efter många försök"
        item["last_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(job_status, f, indent=2)
        print(f"✗ Jobb {job_id} pollade {MAX_RETRIES_POLL} gånger utan resultat, avbryter.")

# När alla jobb har pollats:
job_status["meta"]["overall_status"] = "DONE"
job_status["meta"]["note"] = "Alla låtar hämtade."
job_status["meta"]["completed_at"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

with open(STATUS_FILE, "w", encoding="utf-8") as f:
    json.dump(job_status, f, indent=2)

# Arkivera jobid_aktiv.json med tidsstämpel
timestamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
archive_status = f"jobid_{timestamp}.json"
try:
    os.replace(STATUS_FILE, archive_status)
except:
    try:
        import shutil
        shutil.copy2(STATUS_FILE, archive_status)
        os.remove(STATUS_FILE)
    except Exception as e:
        print(f"⚠️ Kunde inte arkivera {STATUS_FILE}: {e}")

# Ta bort eventuell kvarvarande sunoprompt_aktiv.json om den finns (redan arkiverad av create)
if os.path.isfile("sunoprompt_aktiv.json"):
    try:
        os.remove("sunoprompt_aktiv.json")
    except:
        pass

print(f"✓ Arkiverade job-status → {archive_status}")
print("✓ Städade bort aktiva statusfiler. Klart!")

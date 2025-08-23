# poll_songs.py  (v4) – matchar installer v4 & create v3/v4
# Läser .env, pollar status för job_id i jobid_aktiv.json, laddar ned audio till .\out\
import os, sys, time, json, pathlib, argparse, mimetypes
from datetime import datetime as dt
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv

ROOT = pathlib.Path.cwd()
ENV_PATH = ROOT / ".env"
OUT_DIR = ROOT / "out"
JOB_ACTIVE = ROOT / "jobid_aktiv.json"

load_dotenv(ENV_PATH)

def env_first(*keys, default=None):
    for k in keys:
        v = os.getenv(k)
        if v: return v
    return default

def now_iso(): return dt.utcnow().replace(microsecond=0).isoformat() + "Z"

def load_json(p):
    if not pathlib.Path(p).exists(): return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def slug(s: str, n: int = 64) -> str:
    import re
    s = (s or "").strip() or "track"
    s = re.sub(r'[<>:\"/\\|?*\n\r\t]+',' ',s).strip()
    return (s[:n] or "track").replace(' ','_')

RETRYABLE = {429, 430, 455, 500, 502, 503, 504}
ERROR_EXPL = {
    400:"Ogiltig förfrågan.",
    401:"Obehörig – kontrollera SUNO_API_KEY.",
    404:"Fel endpoint/okänt jobb.",
    413:"Payload för stor.",
    429:"Rate-limit/slut på krediter.",
    430:"För hög anropsfrekvens.",
    455:"Underhållsläge.",
    500:"Serverfel.",
    502:"Gateway-fel.",
    503:"Tjänsten tillfälligt nere.",
    504:"Gateway timeout."
}

def backoff(attempt, base=1.5, cap=30.0, jitter=0.5):
    import random
    d = min(cap, base * (2 ** attempt))
    return max(0.0, d + random.uniform(-jitter, jitter))

def detect_ext_from_url(u, fallback=".mp3"):
    path = urlparse(u).path
    ext = pathlib.Path(path).suffix.lower()
    if ext: return ext
    return fallback

def download_file(url, dest_path, headers=None, timeout=120):
    with requests.get(url, headers=headers or {}, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", "0") or 0)
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk: f.write(chunk)
    return dest_path

def main():
    ap = argparse.ArgumentParser(description="Britt-POP × Suno – poll_songs v4")
    ap.add_argument("--jobs", default=str(JOB_ACTIVE), help="jobid_aktiv.json (default: ./jobid_aktiv.json)")
    ap.add_argument("--api-key", default=None, help="Suno API key (överskuggar .env)")
    ap.add_argument("--api-url", default=None, help="Suno API base URL (t.ex. https://api.suno.ai/v1)")
    ap.add_argument("--interval", type=float, default=5.0, help="Pollintervall i sekunder (default 5)")
    ap.add_argument("--max-wait", type=int, default=1800, help="Max total väntetid i sek (default 1800 = 30 min)")
    args = ap.parse_args()

    api_key = args.api_key or env_first("SUNO_API_KEY")
    if not api_key:
        print("✖ SUNO_API_KEY saknas. Lägg i .env eller passera via --api-key.")
        sys.exit(2)

    base_url = args.api_url or env_first("SUNO_API_URL", default="https://api.suno.ai/v1")
    base_url = base_url.rstrip("/")
    status_url = (base_url + "/status") if not base_url.endswith("/status") else base_url

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    job_path = pathlib.Path(args.jobs)
    data = load_json(job_path)
    if not data:
        print(f"✖ Hittar inte {job_path}. Kör create_songs.py först.")
        sys.exit(2)

    meta = data.get("meta", {}) or {}
    items = data.get("items", []) or []
    if not items:
        print("✖ Inga items i jobid_aktiv.json.")
        sys.exit(2)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    print("┌──────────────────────────────────┐")
    print("│ poll_songs.py – Britt-POP × Suno │")
    print("└──────────────────────────────────┘")
    print(f"• Endpoint: {status_url}")
    print(f"• Jobs-fil: {job_path}")
    print(f"• Out-dir : {OUT_DIR}")
    print("")

    # vilka ska vi bevaka?
    watch_idx = [i for i, it in enumerate(items)
                 if it.get("job_id") and not it.get("audio_path")]

    if not watch_idx:
        print("✓ Inget att poll:a – alla spår verkar redan nerladdade.")
        return

    start_t = time.time()
    finished = set()
    attempts = {i:0 for i in watch_idx}

    while True:
        any_progress = False

        for i in list(watch_idx):
            it = items[i]
            if i in finished: continue
            job_id = it.get("job_id")
            if not job_id: 
                finished.add(i); continue

            # Hoppa över om redan laddad
            if it.get("audio_path"):
                finished.add(i); continue

            attempt = attempts[i]
            try:
                r = requests.post(status_url, headers=headers, json={"job_id": job_id}, timeout=60)
                code = r.status_code

                if code == 200:
                    js = r.json() or {}
                    # Vanliga nycklar vi försöker förstå
                    api_status = js.get("status") or js.get("state") or js.get("phase")
                    progress   = js.get("progress")
                    title      = js.get("title") or it.get("title") or f"track_{i+1}"
                    audio_url  = js.get("audio_url") or js.get("mp3_url") or js.get("audio")

                    # Uppdatera item
                    it["api_status"] = api_status
                    it["progress"]   = progress
                    it["last_update"]= now_iso()

                    if audio_url:
                        ext = detect_ext_from_url(audio_url, ".mp3")
                        fname = f"{dt.utcnow().strftime('%Y%m%d-%H%M%S')}_{slug(title)}{ext}"
                        dest = OUT_DIR / fname
                        print(f"  ↓ Laddar ned: {title} → {dest.name}")
                        download_file(audio_url, dest, headers=None)
                        it["audio_url"]  = audio_url
                        it["audio_path"] = str(dest)
                        it["status"]     = "DOWNLOADED"
                        finished.add(i)
                        any_progress = True
                    else:
                        # Ingen fil än – visa status
                        it["status"] = (api_status or "PROCESSING")
                        print(f"  … [{job_id}] {title}: {it['status']} {f'({progress}%)' if progress else ''}")
                    save_json(job_path, {"meta":meta,"items":items})

                elif code in RETRYABLE:
                    attempts[i] = attempt + 1
                    wait = backoff(attempt)
                    print(f"  … HTTP {code} – {ERROR_EXPL.get(code,'tillfälligt fel')} – väntar {wait:.1f}s")
                    time.sleep(wait)
                    any_progress = True

                else:
                    it["status"]="STATUS_FAILED"
                    it["http_status"]=code
                    it["error_expl"]=ERROR_EXPL.get(code, f"Okänt fel ({code})")
                    it["last_update"]=now_iso()
                    print(f"  ✖ [{job_id}] {it['error_expl']}")
                    finished.add(i)
                    save_json(job_path, {"meta":meta,"items":items})

            except requests.RequestException as e:
                attempts[i] = attempt + 1
                wait = backoff(attempt)
                it["status"]="NET_RETRY"
                it["error_expl"]=f"Nätverksfel: {e}"
                it["last_update"]=now_iso()
                print(f"  ✖ Nätverksfel: {e} – retry om {wait:.1f}s")
                save_json(job_path, {"meta":meta,"items":items})
                time.sleep(wait)
                any_progress = True

        # stoppvillkor
        if len(finished) == len(watch_idx):
            print("\n✓ Klart: Alla spår nedladdade eller terminal status.")
            break

        if time.time() - start_t > args.max_wait:
            print("\n! Avbryter: Max väntetid passerad.")
            break

        if not any_progress:
            time.sleep(args.interval)

    # Markera i meta
    meta["overall_status"]="POLL_DONE"
    meta["last_poll"]=now_iso()
    save_json(job_path, {"meta":meta,"items":items})
    print(f"• Uppdaterade: {job_path}")

if __name__ == "__main__":
    main()

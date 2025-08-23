#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
poll_songs_plus.py — Production Pipeline (Suno old-docs)
• Läser jobid_aktiv.json (skapad av create_songs.py)
• Pollar: GET https://api.sunoapi.org/api/v1/generate/record-info?taskId=...
• Vid SUCCESS utförs 5–6 produktionssteg automatiskt:
  1) Ladda ner MP3 ➜ ./out/<taskId>.mp3
  2) Skapa jobbmapp ./jobs/<taskId>__<slug_title>/
  3) Skriv manifest.json med all metadata (prompt, endpoint, status, sunoData)
  4) Kopiera snapshot av jobid_aktiv.json och sunoprompt_aktiv.json till jobbmappen
  5) Kopiera/renama MP3 ➜ ./jobs/.../<slug_title>.mp3
  6) Append till jobid_done.json och markera posten som COMPLETED i jobid_aktiv.json
• (Valfritt) ladda ner bild om imageUrl/coverUrl finns
"""

from __future__ import annotations
import os, sys, json, time, argparse, re
from pathlib import Path
from datetime import datetime as dt

DEFAULT_BASE = "https://api.sunoapi.org/api/v1"
ACTIVE_FILE = Path("jobid_aktiv.json")
DONE_FILE   = Path("jobid_done.json")
PROMPT_FILE = Path("sunoprompt_aktiv.json")
OUT_DIR     = Path("out")
JOBS_DIR    = Path("jobs")

STATUS_DONE = {"SUCCESS"}
STATUS_CONT = {"PENDING","TEXT_SUCCESS","FIRST_SUCCESS","GENERATING"}
STATUS_FAIL = {"FAILED","CREATE_TASK_FAILED","GENERATE_AUDIO_FAILED","SENSITIVE_WORD_ERROR"}


def now():
    return dt.utcnow().replace(microsecond=0).isoformat()+"Z"

def slugify(s: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", s or "").strip().lower().replace(" ", "_")
    return s[:64] or "untitled"

def read_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return default

def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def extract_ids(active_js):
    items = active_js.get("items", [])
    ids = []
    for it in items:
        jid = it.get("job_id") or it.get("taskId")
        if jid:
            ids.append((jid, it))
    return ids


def main():
    ap = argparse.ArgumentParser(description="poll_songs_plus.py – Production Pipeline")
    ap.add_argument("--api-url", default=DEFAULT_BASE, help="Base URL (default: https://api.sunoapi.org/api/v1)")
    ap.add_argument("--token", default=None, help="API-nyckel; annars läses SUNO_API_KEY ur .env/os env")
    ap.add_argument("--interval", type=float, default=3.0, help="Pollintervall sek (default 3.0)")
    ap.add_argument("--timeout", type=int, default=120, help="Max poll-cykler per jobb (default 120 ≈6 min)")
    ap.add_argument("--download-image", action="store_true", help="Försök hämta imageUrl/coverUrl om finns")
    args = ap.parse_args()

    base = args.api_url.rstrip("/")
    poll_url = base + "/generate/record-info"

    # auth
    token = args.token or os.getenv("SUNO_API_KEY")
    if not token:
        token = input("SUNO_API_KEY: ").strip()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # ensure dirs
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    # load active jobs
    active = read_json(ACTIVE_FILE, {"meta":{}, "items":[]})
    id_pairs = extract_ids(active)
    if not id_pairs:
        print("✓ Inget att polla – inga taskId i jobid_aktiv.json.")
        return

    import requests

    completed_count = 0
    for jid, item in id_pairs:
        print(f"→ Pollar {jid} …")
        rec_info = None
        for _ in range(args.timeout):
            r = requests.get(poll_url, headers=headers, params={"taskId": jid}, timeout=60)
            if r.status_code != 200:
                print(f"  ! HTTP {r.status_code} – {r.text[:120]}")
                time.sleep(args.interval); continue
            rec_info = r.json().get("data") or {}
            st = rec_info.get("status") or rec_info.get("generateStatus")
            if st in STATUS_CONT:
                time.sleep(args.interval); continue
            if st in STATUS_FAIL:
                print(f"  ✖ FAILED: {st}")
                item.update({"status":"FAILED","generate_status":st,"finished_at":now()})
                break
            if st in STATUS_DONE:
                # sunoData
                suno = (rec_info.get("response") or {}).get("sunoData") or []
                if not suno:
                    print("  ! SUCCESS utan sunoData")
                    item.update({"status":"NO_DATA","finished_at":now()})
                    break
                entry = suno[0]
                # download MP3 to out
                url = entry.get("audioUrl") or entry.get("streamAudioUrl")
                if not url:
                    print("  ! SUCCESS utan audioUrl")
                    item.update({"status":"NO_AUDIO","finished_at":now()})
                    break
                mp3_out = OUT_DIR / f"{jid}.mp3"
                mp3_out.write_bytes(requests.get(url, timeout=120).content)
                print(f"  ✓ Sparad: {mp3_out}")

                # build job folder
                title = item.get("title") or entry.get("title") or "untitled"
                slug = slugify(title)
                job_dir = JOBS_DIR / f"{jid}__{slug}"
                job_dir.mkdir(parents=True, exist_ok=True)

                # copy artifacts
                mp3_job = job_dir / f"{slug}.mp3"
                try:
                    mp3_job.write_bytes(mp3_out.read_bytes())
                except Exception as e:
                    print("  ! Kunde inte kopiera MP3 till jobbmapp:", e)

                # optional image
                if args.download_image:
                    img_url = entry.get("imageUrl") or entry.get("coverUrl")
                    if img_url:
                        try:
                            img_bytes = requests.get(img_url, timeout=60).content
                            (job_dir / "cover.jpg").write_bytes(img_bytes)
                            print("  ✓ Bild sparad: cover.jpg")
                        except Exception as e:
                            print("  ! Kunde inte hämta bild:", e)

                # write manifest
                manifest = {
                    "job_id": jid,
                    "title": title,
                    "slug": slug,
                    "created_at": active.get("meta",{}).get("created_at"),
                    "finished_at": now(),
                    "endpoint": active.get("meta",{}).get("endpoint"),
                    "prompt_text": item.get("prompt_text"),
                    "status": "SUCCESS",
                    "record_info": rec_info,
                    "sunoData_first": entry,
                    "outputs": {
                        "mp3_out": str(mp3_out.resolve()),
                        "mp3_job": str(mp3_job.resolve())
                    }
                }
                write_json(job_dir / "manifest.json", manifest)

                # snapshots
                try:
                    (job_dir / "jobid_aktiv_snapshot.json").write_text(ACTIVE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
                try:
                    if PROMPT_FILE.exists():
                        (job_dir / "sunoprompt_snapshot.json").write_text(PROMPT_FILE.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass

                # update active + done
                item.update({
                    "status":"COMPLETED",
                    "generate_status":"SUCCESS",
                    "job_dir": str(job_dir.resolve()),
                    "mp3": str(mp3_out.resolve()),
                    "finished_at": manifest["finished_at"]
                })
                active.setdefault("meta",{})._update = now()  # marker
                write_json(ACTIVE_FILE, active)

                done = read_json(DONE_FILE, {"meta": {"created": now()}, "items": []})
                done["items"].append({
                    "job_id": jid,
                    "title": title,
                    "prompt_text": item.get("prompt_text"),
                    "job_dir": str(job_dir.resolve()),
                    "mp3": str(mp3_out.resolve()),
                    "finished_at": manifest["finished_at"]
                })
                write_json(DONE_FILE, done)

                completed_count += 1
                break
        time.sleep(0.5)

    print(f"\nKlart – {completed_count}/{len(id_pairs)} jobb färdigprocessade.")

if __name__ == "__main__":
    main()
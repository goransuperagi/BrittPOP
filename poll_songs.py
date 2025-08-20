import os
import json
import time
import requests

API_KEY = os.getenv("SUNO_API_KEY")
BASE_URL = "https://api.suno.ai/v1/jobs"
DOWNLOAD_DIR = "downloads"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def load_job_ids():
    with open("job_ids.json", "r", encoding="utf-8") as f:
        return json.load(f)

def download_file(url, filename):
    r = requests.get(url)
    if r.status_code == 200:
        with open(filename, "wb") as f:
            f.write(r.content)
        print(f"Downloaded: {filename}")
    else:
        print("Download error:", r.status_code)

def poll_jobs(job_ids):
    headers = {"Authorization": f"Bearer {API_KEY}"}
    for job_id in job_ids:
        print(f"Polling job {job_id}...")
        while True:
            r = requests.get(f"{BASE_URL}/{job_id}", headers=headers)
            if r.status_code == 200:
                data = r.json()
                status = data.get("status")
                if status == "completed":
                    mp3_url = data.get("result", {}).get("audio_url")
                    if mp3_url:
                        filename = os.path.join(DOWNLOAD_DIR, f"{job_id}.mp3")
                        download_file(mp3_url, filename)
                    break
                elif status == "failed":
                    print(f"Job {job_id} failed.")
                    break
                else:
                    print(f"Job {job_id} still {status}, waiting...")
                    time.sleep(10)
            else:
                print("Error:", r.text)
                break

def main():
    job_ids = load_job_ids()
    poll_jobs(job_ids)

if __name__ == "__main__":
    main()

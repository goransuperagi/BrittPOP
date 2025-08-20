import os
import json
import requests
from datetime import datetime

API_KEY = os.getenv("SUNO_API_KEY")
BASE_URL = "https://api.suno.ai/v1/generate"
PROMPT_FILE = "sunoprompt-aktiv.json"

def load_prompts():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_job_ids(job_ids):
    with open("job_ids.json", "w", encoding="utf-8") as f:
        json.dump(job_ids, f, indent=2)

def rename_prompt_file():
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    new_name = f"sunoprompt-{ts}.json"
    os.rename(PROMPT_FILE, new_name)
    print(f"Renamed {PROMPT_FILE} -> {new_name}")

def main():
    prompts = load_prompts()
    job_ids = []

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    for prompt in prompts:
        data = {"prompt": prompt.get("prompt"), "params": prompt.get("params", {})}
        r = requests.post(BASE_URL, headers=headers, json=data)
        if r.status_code == 200:
            job_id = r.json().get("job_id")
            job_ids.append(job_id)
            print(f"Started job {job_id} for prompt: {prompt['prompt']}")
        else:
            print("Error:", r.text)

    save_job_ids(job_ids)
    rename_prompt_file()

if __name__ == "__main__":
    main()

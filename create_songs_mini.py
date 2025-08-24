import os, sys, json, subprocess, shutil, datetime

# Denna testskript skapar en temporär testmapp och kör en minimal pipeline (create + poll) 
# med en enkel prompt för att generera en kort 10-sekunders jingle.

TEST_FOLDER = "minitest"
if os.path.exists(TEST_FOLDER):
    # Radera ev. gammal testmapp för att börja från rent tillstånd
    try:
        if os.path.isdir(TEST_FOLDER):
            shutil.rmtree(TEST_FOLDER)
        else:
            os.remove(TEST_FOLDER)
    except Exception as e:
        print(f"⚠️ Kunde inte rensa gammal testmapp: {e}")
# Skapa ny testmapp
os.makedirs(TEST_FOLDER, exist_ok=True)

# Kopiera .env om den finns (för API-nyckeln) in i testmappen
if os.path.isfile(".env"):
    shutil.copy2(".env", os.path.join(TEST_FOLDER, ".env"))

# Bygg minimal sunoprompt_aktiv.json innehåll
test_prompt = {
    "meta": {
        "created_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "default_count": 1,
        "note": "Mini-test prompt"
    },
    "prompts": [
        {
            "title": "Test Jingle",
            "prompt": "Uppbeat catchy jingle tune with whistling",
            "params": "length=8-12s",
            "count": 1
        }
    ]
}
# Spara promptfil i testmappen
prompt_file_path = os.path.join(TEST_FOLDER, "sunoprompt_aktiv.json")
with open(prompt_file_path, "w", encoding="utf-8") as f:
    json.dump(test_prompt, f, indent=2)

print(f"Testmiljö skapad i mapp: {TEST_FOLDER}")
print("Startar create_songs.py för testprompten...")

# Kör create_songs.py i testmappens kontext
try:
    # Ange testmapp som arbetsmapp så att create_songs.py läser/skrivar där
    completed = subprocess.run([sys.executable, "create_songs.py"], cwd=TEST_FOLDER, check=True)
except subprocess.CalledProcessError as e:
    print(f"❌ create_songs.py misslyckades i testmiljön: {e}")
    sys.exit(1)

print("create_songs.py körd. Startar poll_songs.py...")

try:
    completed = subprocess.run([sys.executable, "poll_songs.py"], cwd=TEST_FOLDER, check=True)
except subprocess.CalledProcessError as e:
    print(f"❌ poll_songs.py misslyckades i testmiljön: {e}")
    sys.exit(1)

print("✅ Testflödet klart. Kontrollera output ovanför för status och genererad MP3-fil i testmappen.")
# Öppna genererad MP3-fil (senaste) på Windows om möjligt
out_dir = os.path.join(TEST_FOLDER, "out")
if os.path.isdir(out_dir):
    mp3_files = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.lower().endswith(".mp3")]
    if mp3_files:
        latest = max(mp3_files, key=os.path.getmtime)
        if os.name == "nt":  # Windows
            os.startfile(latest)
        else:
            print(f"Låt finns här: {latest}")

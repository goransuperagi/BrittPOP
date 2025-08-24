import os, sys, subprocess

# Detta skript antar att create_songs_mini.py just körts.
# Det startar endast poll_songs.py igen separat, ifall man vill testa omstart av poll-fasen.

TEST_FOLDER = "test_jingle"
if not os.path.isdir(TEST_FOLDER):
    print("❌ Ingen testmapp hittad. Kör create_songs_mini.py först.")
    sys.exit(1)

print("Startar en ny pollingomgång på testmiljön...")
try:
    completed = subprocess.run([sys.executable, "poll_songs.py"], cwd=TEST_FOLDER, check=True)
except subprocess.CalledProcessError as e:
    print(f"❌ poll_songs.py misslyckades under test: {e}")
    sys.exit(1)
print("✅ Polling klar. Kontrollera eventuella statusmeddelanden ovan.")

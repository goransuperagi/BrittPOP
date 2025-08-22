# =========================================
# Britt-POP × Suno – Robust installer v2
# - Uppdaterar .env smart
# - Tar --api-key eller SUNO_API_KEY
# - Frågar endast vid behov
# =========================================
import os, sys, pathlib, subprocess, argparse
from urllib.request import urlopen
from getpass import getpass

ROOT = pathlib.Path.cwd().resolve()
RAW  = "https://raw.githubusercontent.com/goransuperagi/BrittPOP/main"
FILES = ["create_songs.py", "poll_songs.py"]

DEFAULT_ENV = {
    "SUNO_API": "https://api.suno.example/v1",
    "SUNO_API_KEY": "",
    "TIMEOUT_CREATE": "30",
    "TIMEOUT_POLL": "30",
    "TIMEOUT_DOWNLOAD": "180",
}

def parse_args():
    p = argparse.ArgumentParser(description="Britt-POP installer v2")
    p.add_argument("--api-key", help="Suno API key (utan citattecken)")
    p.add_argument("--api-url", help="Suno API URL", default=None)
    p.add_argument("--no-prompt", action="store_true",
                   help="Fråga inte efter API-nyckel om saknas")
    p.add_argument("--force", action="store_true",
                   help="Tvinga omskrivning av SUNO_API_KEY i .env")
    return p.parse_args()

def load_env(path: pathlib.Path) -> dict:
    d = DEFAULT_ENV.copy()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d

def save_env(path: pathlib.Path, data: dict):
    lines = [f"{k}={data.get(k,'')}" for k in DEFAULT_ENV.keys()]
    path.write_text("\n".join(lines), encoding="utf-8")

def fetch(name: str):
    url = f"{RAW}/{name}"
    dst = ROOT / name
    with urlopen(url) as r:
        dst.write_bytes(r.read())
    print(f"✓ Hämtad: {name}")

def ensure_packages():
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], shell=False)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "python-dotenv", "tqdm"], shell=False)
        print("✓ Pythonpaket installerade.")
    except Exception as e:
        print(f"! Varning: paketinstallation misslyckades: {e}")

def main():
    args = parse_args()

    print("┌─────────────────────────────┐")
    print("│  HumanoidGPT Britt-POP v2   │")
    print(f"│  Installerar i: {ROOT}")
    print("├─────────────────────────────┤")

    # 1) Mappar
    (ROOT / "out").mkdir(parents=True, exist_ok=True)

    # 2) .env-hantering
    env_path = ROOT / ".env"
    env = load_env(env_path)

    # Källor för API-url & key
    if args.api_url:
        env["SUNO_API"] = args.api_url.strip()

    # Prioritetsordning för API-key:
    # --api-key > miljövariabel SUNO_API_KEY > befintlig .env
    api_key_cli = (args.api_key or "").strip()
    api_key_env = os.environ.get("SUNO_API_KEY", "").strip()

    if api_key_cli:
        env["SUNO_API_KEY"] = api_key_cli
    elif api_key_env and (args.force or not env.get("SUNO_API_KEY")):
        env["SUNO_API_KEY"] = api_key_env

    # Om fortfarande tomt och vi får fråga:
    if not env.get("SUNO_API_KEY") and not args.no_prompt:
        print("\nKlistra in din SUNO API KEY (utan citattecken) och tryck Enter:")
        try:
            entered = getpass(prompt="API KEY: ").strip()
        except Exception:
            entered = input().strip()
        env["SUNO_API_KEY"] = entered

    # Skriv .env
    save_env(env_path, env)
    print(f"✓ .env uppdaterad ({env_path})")

    # 3) Hämta körskript
    for f in FILES:
        try:
            fetch(f)
        except Exception as e:
            print(f"! Misslyckades hämta {f}: {e}")

    # 4) Paket
    ensure_packages()

    # 5) Summering
    print("├─────────────────────────────┤")
    for name in [".env", "create_songs.py", "poll_songs.py", "out\\"]:
        print(f"• {name}")
    masked = ("***" if env.get("SUNO_API_KEY") else "(saknas)")
    print(f"• SUNO_API_KEY: {masked}")
    print("└─────────────────────────────┘\n")

    print("Nästa steg:")
    print(r"  1) Skapa din JSON: sunoprompt-aktiv.json (eller använd Single-exemplet).")
    print(r"  2) python create_songs.py --json .\sunoprompt-aktiv.json")
    print(r"  3) python poll_songs.py")
    print("Installation klar.")

if __name__ == "__main__":
    main()

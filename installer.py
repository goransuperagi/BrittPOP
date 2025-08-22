# installer.py  (v3)
import os, sys, pathlib, subprocess, argparse
from getpass import getpass

ROOT = pathlib.Path.cwd().resolve()
ENV_PATH = ROOT / ".env"

DEFAULTS = {
    "SUNO_API_URL": "https://api.suno.ai/v1",   # bas-URL (skriptet lägger själv på /generate)
    "SUNO_API_KEY": "",
    "TIMEOUT_CREATE": "60",
}

def load_env(p):
    d = DEFAULTS.copy()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k,v=line.split("=",1); d[k.strip()] = v.strip()
    return d

def save_env(p, d):
    lines = [f"{k}={d.get(k,'')}" for k in DEFAULTS.keys()]
    p.write_text("\n".join(lines), encoding="utf-8")

def ensure_packages():
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], shell=False)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "python-dotenv"], shell=False)
        print("✓ Pythonpaket installerade (requests, python-dotenv).")
    except Exception as e:
        print(f"! Varning: paketinstallation misslyckades: {e}")

def parse_args():
    p = argparse.ArgumentParser(description="Britt-POP installer v3")
    p.add_argument("--api-key", help="Suno API key")
    p.add_argument("--api-url", help="Suno API base URL (t.ex. https://api.suno.ai/v1)")
    p.add_argument("--no-prompt", action="store_true", help="Fråga inte om API-nyckel om saknas")
    return p.parse_args()

def main():
    args = parse_args()
    print("┌─────────────────────────────┐")
    print("│  HumanoidGPT Britt-POP v3   │")
    print(f"│  Installerar i: {ROOT}")
    print("└─────────────────────────────┘")

    (ROOT / "out").mkdir(parents=True, exist_ok=True)

    env = load_env(ENV_PATH)

    # Prioritet: CLI > process env > befintlig .env
    if args.api_url: env["SUNO_API_URL"] = args.api_url.strip()
    if args.api_key:
        env["SUNO_API_KEY"] = args.api_key.strip()
    elif os.environ.get("SUNO_API_KEY"):
        env["SUNO_API_KEY"] = os.environ["SUNO_API_KEY"].strip()

    if not env.get("SUNO_API_KEY") and not args.no_prompt:
        print("\nKlistra in din SUNO_API_KEY (Enter för att bekräfta).")
        key = input("API KEY: ").strip() or getpass("API KEY (maskerad): ").st
        env["SUNO_API_KEY"] = key

    save_env(ENV_PATH, env)
    print(f"✓ .env uppdaterad → {ENV_PATH}")
    print(f"• SUNO_API_URL = {env.get('SUNO_API_URL')}")
    print(f"• SUNO_API_KEY = {'***' if env.get('SUNO_API_KEY') else '(saknas)'}")

    ensure_packages()

    print("\nTips:")
    print(r'  • Sätt sessionsvariabel:  $env:SUNO_API_KEY="DIN_KEY"')
    print(r'  • Permanent i Windows:    setx SUNO_API_KEY "DIN_KEY" (starta om PowerShell)')
    print("Klar.")

if __name__ == "__main__":
    main()

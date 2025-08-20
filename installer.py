# =========================================
# Britt-POP × Suno – Ren Python-installer
# Använder alltid aktuell katalog (cwd) som installationsrot.
# =========================================

import os, sys, pathlib, subprocess, json, re
from datetime import datetime

# --- Root = där skriptet körs ifrån ---
ROOT = pathlib.Path.cwd().resolve()

# ──────────────── Startbanner ────────────────
print("┌─────────────────────────────┐")
print("│  HumanoidGPT Britt-POP      │")
print(f"│  Installerar i: {ROOT}")
print("├─────────────────────────────┤")

def nowstamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

# De här skripten hämtas separat via din GPT-prompt före 'python installer.py'
LEGACY_SCRIPTS = ["create_song.py", "poll_songs.py"]
legacy_missing = [f for f in LEGACY_SCRIPTS if not (ROOT / f).exists()]
if legacy_missing:
    print("│ • Info: följande GitHub-filer saknas (hämtas i GPT-blocket):")
    for f in legacy_missing:
        print(f"│   - {f:<22}")
    print("├─────────────────────────────┤")

# 1) Mappar
(ROOT / "out").mkdir(parents=True, exist_ok=True)

# 2) .env & API-key
env_example = (
    "SUNO_API=https://api.suno.example/v1\n"
    "SUNO_API_KEY=\n"
    "TIMEOUT_CREATE=30\n"
    "TIMEOUT_POLL=30\n"
    "TIMEOUT_DOWNLOAD=180\n"
)
(ROOT / ".env.example").write_text(env_example, encoding="utf-8")
env_path = ROOT / ".env"
if not env_path.exists():
    print("\nKlistra in din SUNO API KEY (utan citattecken) och tryck Enter:")
    try:
        api = input().strip()
    except EOFError:
        api = ""
    env = env_example.replace("SUNO_API_KEY=", f"SUNO_API_KEY={api}")
    env_path.write_text(env, encoding="utf-8")
    print(".env skapad.")
else:
    print(".env finns redan – hoppar över.")

# 3) Skriv huvudfiler (inbäddat innehåll)
suno_batch_json_py = r'''import os, sys, json, time, csv, pathlib, concurrent.futures, requests, re
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

ENV_API = os.getenv("SUNO_API", "https://api.suno.example/v1")
ENV_KEY = os.getenv("SUNO_API_KEY")
TIMEOUT_CREATE = int(os.getenv("TIMEOUT_CREATE", "30"))
TIMEOUT_POLL   = int(os.getenv("TIMEOUT_POLL", "30"))
TIMEOUT_DL     = int(os.getenv("TIMEOUT_DOWNLOAD", "180"))

HEADERS = {"Authorization": f"Bearer {ENV_KEY}" if ENV_KEY else "", "Content-Type": "application/json"}

def nowstamp(): return datetime.now().strftime("%Y%m%d-%H%M%S")
def safe(s,n=60):
    s = s or "track"
    s = re.sub(r'[<>:"/\\|?*\n\r\t]+',' ',s).strip()
    return (s[:n] or "track").replace(' ','_')

def join_prompt(p,params):
    return f"{p.strip()} || {params.strip()}" if params and params.strip() else p.strip()

def api_create(api_url,prompt_text):
    r = requests.post(f"{api_url}/generations", headers=HEADERS, json={"prompt":prompt_text}, timeout=TIMEOUT_CREATE)
    r.raise_for_status(); return r.json().get("id")

def api_poll(api_url,job_id):
    while True:
        r = requests.get(f"{api_url}/generations/{job_id}", headers=HEADERS, timeout=TIMEOUT_POLL)
        r.raise_for_status(); s=r.json(); st=s.get("state")
        if st in ("completed","failed","canceled"): return s
        time.sleep(3)

def download(url,dst):
    with requests.get(url, stream=True, timeout=TIMEOUT_DL) as r:
        r.raise_for_status()
        with open(dst,"wb") as f:
            for ch in r.iter_content(8192): f.write(ch)

def run_one(idx,api_url,title,prompt,params,count,outdir):
    res=[]; text=join_prompt(prompt,params); base=safe(title or prompt)
    for i in range(1, count+1):
        rec={"index":idx,"variant":i,"title":title,"prompt":text}
        try:
            job=api_create(api_url,text); s=api_poll(api_url,job)
            rec.update(job_id=job, state=s.get("state"))
            audio=(s.get("audio") or {}).get("url")
            if rec["state"]=="completed" and audio:
                mp3=outdir/f"{idx:03d}_{base}_v{i}_{job}.mp3"; download(audio,mp3); rec["audio_path"]=str(mp3)
            else:
                rec["error"]=f"state={rec['state']}"
        except requests.HTTPError as e:
            rec["error"]=f"http:{getattr(e.response,'status_code','')}"
        except Exception as e:
            rec["error"]=f"{type(e).__name__}:{e}"
        res.append(rec)
    return res

def main(json_file):
    root=pathlib.Path('.').resolve()
    jf=root/json_file
    if not jf.exists(): print(f"ERR: saknar {json_file}"); sys.exit(2)
    data=json.loads(jf.read_text(encoding='utf-8'))
    meta=data.get('meta',{}); arr=data.get('prompts',[])
    if not arr: print('ERR: prompts saknas i JSON'); sys.exit(2)
    api = meta.get('api_url') or ENV_API
    default_count=int(meta.get('default_count',3))
    concurrency=int(meta.get('concurrency',5))
    outdir=root/(meta.get('output_dir') or 'out'); outdir.mkdir(parents=True,exist_ok=True)
    log=outdir/f"log_{nowstamp()}.csv"
    with open(log,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=["index","variant","title","job_id","state","audio_path","prompt","error"])
        w.writeheader()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
            futs=[]
            for idx,item in enumerate(arr,1):
                title=item.get('title') or f'Prompt_{idx}'
                prompt=item.get('prompt') or ''
                params=item.get('params')
                count=int(item.get('count') or default_count)
                futs.append(ex.submit(run_one, idx, api, title, prompt, params, count, outdir))
            for fu in concurrent.futures.as_completed(futs):
                rows=fu.result()
                for rec in rows:
                    w.writerow(rec)
                    print(f"[{rec['index']:03d} v{rec['variant']}] {rec.get('state','-'):10s} {rec.get('audio_path','') or rec.get('error','')}")
    ts=nowstamp(); archived=root/f"sunoprompt-{ts}.json"
    try: jf.replace(archived); print(f"Arkiverad: {archived.name}")
    except Exception as e: print('Varning: kunde inte arkivera JSON:', e)

if __name__=='__main__':
    jf = 'sunoprompt-aktiv.json' if len(sys.argv)<2 else sys.argv[1]
    main(jf)
'''

run_json_ps1 = r'''param(
  [switch]$Setup,
  [switch]$Fire,
  [string]$JsonFile = ".\sunoprompt-aktiv.json"
)
if ($Setup) {
  pip install --upgrade pip
  pip install requests python-dotenv tqdm
  if (-not (Test-Path ".\.env")) { Copy-Item .\.env.example .\.env }
  Write-Host "✓ Setup klart. Fyll .env (SUNO_API_KEY) om saknas. Kör -Fire." -ForegroundColor Green
  exit 0
}
if ($Fire) {
  if (-not (Test-Path $JsonFile)) { Write-Error "Hittar inte $JsonFile"; exit 2 }
  if (Test-Path ".\.env") {
    Get-Content .\.env | ForEach-Object {
      if ($_ -match "^\s*#") { return }
      if ($_ -match "^\s*$") { return }
      $k,$v = $_.Split("=",2); if ($k -and $v) { $env:$k = $v }
    }
  }
  if (-not $env:SUNO_API_KEY) { Write-Error "Saknar SUNO_API_KEY"; exit 2 }
  python .\suno_batch_json.py $JsonFile
  exit 0
}
Write-Host "Använd: .\run_json.ps1 -Setup  (första gången)" -ForegroundColor Cyan
Write-Host "        .\run_json.ps1 -Fire   (kör sunoprompt-aktiv.json)" -ForegroundColor Cyan
'''

analyze_batch_py = r'''import argparse, json, os, pathlib, csv
import numpy as np
import librosa
from tqdm import tqdm

def minmax01(x, lo=None, hi=None, eps=1e-9):
    x = np.asarray(x, float)
    if x.size == 0: return x
    if lo is None: lo = np.nanmin(x)
    if hi is None: hi = np.nanmax(x)
    return np.clip((x - lo) / (hi - lo + eps), 0.0, 1.0)

def band_energy(y, sr, f_lo, f_hi):
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))**2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    idx = np.where((freqs >= f_lo) & (freqs <= f_hi))[0]
    if idx.size == 0: return 0.0
    band = S[idx, :].sum()
    total = S.sum() + 1e-9
    return float(band / total)

def percussive_ratio(y, sr):
    S = librosa.stft(y, n_fft=2048, hop_length=512)
    H, P = librosa.decompose.hpss(S)
    eP = np.sum(np.abs(P)**2)
    eH = np.sum(np.abs(H)**2) + 1e-9
    return float(eP / (eP + eH))

def onset_rate(y, sr):
    o_env = librosa.onset.onset_strength(y=y, sr=sr)
    onsets = librosa.onset.onset_detect(onset_envelope=o_env, sr=sr, units='time')
    dur = len(y)/sr if sr else 0.0
    if dur <= 0: return 0.0
    return float(len(onsets)/dur)

def spectral_flatness_mid(y, sr, lo=300, hi=3000):
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    idx = np.where((freqs >= lo) & (freqs <= hi))[0]
    if idx.size == 0: return 0.0
    Smid = S[idx, :] + 1e-12
    gm = np.exp(np.mean(np.log(Smid), axis=0))
    am = np.mean(Smid, axis=0) + 1e-12
    flat = np.mean(gm / am)
    return float(flat)

def tempo_est(y, sr):
    t = librosa.beat.tempo(y=y, sr=sr, aggregate=None)
    if t is None or len(t)==0: return 0.0
    return float(np.median(t))

def rms_curve(y, sr, hop=512):
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    times = librosa.times_like(rms, sr=sr, hop_length=hop)
    return rms, times

def early_lift_score(y, sr, window_sec=20, lift_min_delta_db=3.0, onset_boost=0.5):
    rms, t = rms_curve(y, sr)
    if t.size == 0: return 0.0
    early_mask = t <= window_sec
    if not np.any(early_mask): return 0.0
    base = np.percentile(rms[~early_mask], 50) if np.any(~early_mask) else np.percentile(rms, 25)
    peak = np.max(rms[early_mask])
    import numpy as np
    delta_db = 20*np.log10((peak+1e-9)/(base+1e-9))
    delta_norm = np.clip((delta_db / lift_min_delta_db), 0.0, 1.0)
    o_env = librosa.onset.onset_strength(y=y, sr=sr)
    on_times = librosa.onset.onset_detect(onset_envelope=o_env, sr=sr, units='time')
    rate = np.mean((on_times >= 0) & (on_times <= window_sec)) / (window_sec+1e-9)
    rate_norm = np.clip(rate*10, 0.0, 1.0)
    return float(np.clip((1-onset_boost)*delta_norm + onset_boost*rate_norm, 0.0, 1.0))

def pianoish_score(y, sr, bands, ppar):
    S = librosa.stft(y, n_fft=2048, hop_length=512)
    H, P = librosa.decompose.hpss(S)
    import numpy as np
    eH = float(np.sum(np.abs(H)**2)); eP = float(np.sum(np.abs(P)**2))+1e-9
    harm_part = eH / (eH + eP)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    Smag = np.abs(S)**2
    mid_idx = np.where((freqs >= bands["mid_low"]) & (freqs <= bands["mid_high"]))[0]
    mid_energy = float(Smag[mid_idx, :].sum() / (Smag.sum()+1e-9)) if mid_idx.size else 0.0
    flat_mid = spectral_flatness_mid(y, sr, bands["mid_low"], bands["mid_high"])
    flat_norm = np.clip(1.0 - minmax01(flat_mid, 0.0, ppar.get("flatness_mid_cap",0.25)), 0.0, 1.0)
    hb = ppar.get("harmonic_bias", 0.7)
    mw = ppar.get("midband_weight", 0.6)
    tonal = np.clip(hb*harm_part + (1-hb)*flat_norm, 0.0, 1.0)
    pianoish = np.clip(mw*mid_energy + (1-mw)*tonal, 0.0, 1.0)
    return float(pianoish)

def analyze_file(path, cfg):
    bands = cfg.get("bands_hz", {"bass_low":20,"bass_high":150,"mid_low":300,"mid_high":3000})
    rpar  = cfg.get("rhythm_params", {"onset_strength_cap":8.0})
    rspar = cfg.get("rap_spice_params", {"flatness_mid_floor":0.05,"flatness_mid_cap":0.5,"percussive_bias":0.5})
    epar  = cfg.get("early_hook_params", {"window_sec":20,"lift_min_delta_db":3.0,"onset_boost":0.5})
    ppar  = cfg.get("pianoish_params", {"harmonic_bias":0.7,"midband_weight":0.6,"flatness_mid_cap":0.25})

    y, sr = librosa.load(path, sr=None, mono=True)
    y = librosa.util.normalize(y)

    tempo = tempo_est(y, sr)
    onr = onset_rate(y, sr)
    perc_ratio = percussive_ratio(y, sr)
    bass_ratio = band_energy(y, sr, bands["bass_low"], bands["bass_high"])
    flat_mid = spectral_flatness_mid(y, sr, bands["mid_low"], bands["mid_high"])

    onr_norm = minmax01(onr, 0.0, rpar.get("onset_strength_cap", 8.0))
    rhythm_score = float(np.clip(perc_ratio * onr_norm, 0.0, 1.0))
    bass_score = float(np.clip(bass_ratio, 0.0, 1.0))

    flat_norm = minmax01(flat_mid, rspar.get("flatness_mid_floor",0.05), rspar.get("flatness_mid_cap",0.5))
    rap_spice = float(np.clip(rspar.get("percussive_bias",0.5)*perc_ratio + (1.0 - rspar.get("percussive_bias",0.5))*flat_norm, 0.0, 1.0))

    early = early_lift_score(y, sr,
        window_sec=epar.get("window_sec",20),
        lift_min_delta_db=epar.get("lift_min_delta_db",3.0),
        onset_boost=epar.get("onset_boost",0.5)
    )

    pianoish = pianoish_score(y, sr,
        bands={"mid_low":bands.get("mid_low",300),"mid_high":bands.get("mid_high",4000)},
        ppar=ppar
    )

    return {
        "tempo": tempo,
        "onset_rate": onr,
        "percussive_ratio": perc_ratio,
        "bass_energy_ratio": bass_ratio,
        "flatness_mid": flat_mid,
        "RhythmScore": rhythm_score,
        "BassScore": bass_score,
        "RapSpiceScore": rap_spice,
        "EarlyLiftScore": float(early),
        "PianoishScore": float(pianoish)
    }

def main(out_dir, config_path):
    out = pathlib.Path(out_dir)
    if not out.exists():
        print(f"Saknar {out.resolve()}")
        return

    cfg = {}
    if pathlib.Path(config_path).exists():
        cfg = json.loads(pathlib.Path(config_path).read_text(encoding="utf-8"))

    files = sorted([p for p in out.glob("*.mp3")])
    if not files:
        print(f"Inga mp3 i {out.resolve()}")
        return

    rows = []
    for p in tqdm(files, desc="Analyserar"):
        feats = analyze_file(str(p), cfg)
        rows.append({"file": p.name, **feats})

    for key in ["RhythmScore","BassScore","RapSpiceScore","EarlyLiftScore","PianoishScore"]:
        vals = np.array([r[key] for r in rows], float)
        vals = (vals - np.min(vals)) / (np.max(vals) - np.min(vals) + 1e-9)
        for i,v in enumerate(vals): rows[i][key] = float(v)

    W = cfg.get("weights", {})
    for r in rows:
        r["TotalScore"] = float(
            W.get("pianoish",0)*r.get("PianoishScore",0) +
            W.get("early_hook",0)*r.get("EarlyLiftScore",0) +
            W.get("rhythm",0)*r.get("RhythmScore",0) +
            W.get("bass",0)*r.get("BassScore",0) +
            W.get("rap_spice",0)*r.get("RapSpiceScore",0)
        )

    csv_path = out / "scores.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = list(rows[0].keys())
        cw = csv.DictWriter(f, fieldnames=fieldnames)
        cw.writeheader()
        cw.writerows(rows)

    top = sorted(rows, key=lambda r: r["TotalScore"], reverse=True)
    rank_path = out / "ranking.json"
    with open(rank_path, "w", encoding="utf-8") as f:
        json.dump({"ranking": top}, f, indent=2)

    print(f"Klart. → {csv_path.name}, {rank_path.name}")
'''

run_analyze_ps1 = r'''param(
  [string]$OutDir = ".\out",
  [string]$Config = ".\ranking_config.json"
)
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Error "Python saknas. Installera från python.org"; exit 2
}
pip show librosa | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installerar beroenden..." -ForegroundColor Yellow
  pip install librosa soundfile numpy scipy tqdm | Out-Null
}
python .\analyze_batch.py -o $OutDir -c $Config
'''

ranking_config_json = json.dumps({
  "weights": {
    "pianoish": 0.35,
    "early_hook": 0.30,
    "rhythm": 0.20,
    "bass": 0.10,
    "rap_spice": 0.05
  },
  "normalization": {"clip_min": 0.0, "clip_max": 1.0, "eps": 1e-9},
  "bands_hz": {"bass_low": 20,"bass_high": 150,"mid_low": 300,"mid_high": 4000},
  "rhythm_params": {"onset_strength_cap": 8.0},
  "rap_spice_params": {"flatness_mid_floor": 0.05,"flatness_mid_cap": 0.5,"percussive_bias": 0.5},
  "pianoish_params": {"harmonic_bias": 0.7,"midband_weight": 0.6,"flatness_mid_cap": 0.25},
  "early_hook_params": {"window_sec": 20,"lift_min_delta_db": 3.0,"onset_boost": 0.5}
}, indent=2)

sunoprompt_example = json.dumps({
  "meta": {"batch_name":"Cafe-60s-Strings","default_count":3,"concurrency":5,"output_dir":"out"},
  "prompts": [
    {
      "title":"Cafe Morning Main",
      "prompt":"Uptempo 60s British pop with lush strings; VCVCB; intro<5s; hook@18s; 118 BPM; key G; tambourine & handclaps, melodic bass, jangly rhythm guitar, piano stabs; warm analog mix; lyrics about a lively café morning; chorus title first line.",
      "params":"form=VCVCB|intro_max=5s|hook=15-25|bpm=116-122|key=E/G/A|length=165|variation=med",
      "count":3
    }
  ]
}, indent=2)

# 4) Skriv filer om de saknas (pipeline-filer)
files = {
  "suno_batch_json.py": suno_batch_json_py,
  "run_json.ps1": run_json_ps1,
  "analyze_batch.py": analyze_batch_py,
  "run_analyze.ps1": run_analyze_ps1,
  "ranking_config.json": ranking_config_json,
  "sunoprompt-aktiv.json": sunoprompt_example,
  "README_SETUP.md": "# Snabbstart: .\\run_json.ps1 -Fire → .\\run_analyze.ps1"
}
for name, content in files.items():
    p = ROOT / name
    if not p.exists():
        p.write_text(content, encoding="utf-8")
        print("Skapade", name)

# 5) Installera paket
try:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], shell=False)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "python-dotenv", "tqdm", "librosa", "soundfile", "numpy", "scipy"], shell=False)
    print("✓ Pythonpaket installerade.")
except Exception as e:
    print("Varning: paketinstallation misslyckades:", e)

# 6) Skriv INSTALL_README.md (för dokumentation)
readme = f"""# HumanoidGPT Britt-POP – Installation

**Installerad i:** `{ROOT}`

## Skapade filer
- README_SETUP.md (snabbstart)
- .env och .env.example (API-nyckel)
- sunoprompt-aktiv.json (exempelbatch)
- suno_batch_json.py (skapa låtar via JSON-pipeline)
- analyze_batch.py (ranking/analys)
- run_json.ps1 / run_analyze.ps1 (PowerShell-wrappar)
- ranking_config.json (standardvikter)
- out\\ (mappar för MP3 + resultat)
- (om tillgängliga) create_song.py, poll_songs.py

## När ska jag köra vad?
- **NU:** Inget mer – installationen är klar.
- **SENARE (när du skapat dina Suno-prompts):**
  1. `python create_song.py`
  2. `python poll_songs.py`

> Tips: Om `create_song.py` och `poll_songs.py` inte finns: hämta dem från GitHub och lägg i denna mapp.

---
_Installation klar_
"""
(ROOT / "INSTALL_README.md").write_text(readme, encoding="utf-8")

# 7) Semigrafisk summering i terminalen
expected = [
    "out\\",
    ".env.example",
    "sunoprompt-aktiv.json",
    "run_json.ps1",
    "run_analyze.ps1",
    "analyze_batch.py",
    "suno_batch_json.py",
    "ranking_config.json",
    "README_SETUP.md",
]
# visa även status för legacy-skript om de finns
expected += LEGACY_SCRIPTS

for name in expected:
    exists = (ROOT / name.rstrip("\\")).exists()
    mark   = "✓" if exists else "•"
    status = "Klar" if exists else "Saknas"
    print(f"│ {mark} {status}: {name:<20}│")

print("└─────────────────────────────┘\n")

# 8) Tydliga nästa steg (körs SENARE av användaren)
print("När du skapat dina Suno-prompts, kör:")
print(r"  1) python create_song.py")
print(r"  2) python poll_songs.py")
print("Installation klar")
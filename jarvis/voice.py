"""
Dictée vocale 100 % locale : whisper.cpp (Metal) + modèle large-v3-turbo, sur le Mac.

L'interface enregistre le micro (MediaRecorder), envoie l'audio comme une pièce jointe, puis Jarvis le transcrit ici.
L'enregistrement est effacé dès la transcription faite : ta voix ne reste pas sur le disque.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import config

MODELS = ("ggml-large-v3-turbo-q5_0.bin", "ggml-large-v3-turbo.bin", "ggml-small-q5_1.bin", "ggml-small.bin")


def whisper_bin() -> str | None:
    return shutil.which("whisper-cli") or next((p for p in ("/opt/homebrew/bin/whisper-cli", "/usr/local/bin/whisper-cli")
                                                if Path(p).exists()), None)


def model_path() -> Path | None:
    d = config.JARVIS_DIR / "models"
    return next((d / m for m in MODELS if (d / m).exists() and (d / m).stat().st_size > 10_000_000), None)


def available() -> bool:
    return bool(whisper_bin() and model_path())


def _to_wav(src: Path, dst: Path) -> str:
    """16 kHz mono 16 bits, le format attendu par whisper. afconvert (inclus dans macOS) lit m4a/aac/caf/wav ;
    ffmpeg, s'il est installé, lit aussi le webm."""
    if src.suffix.lower() in (".m4a", ".mp4", ".aac", ".caf", ".wav", ".aiff", ".aif") and shutil.which("afconvert"):
        r = subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(src), str(dst)],
                           capture_output=True, text=True, timeout=60)
        return "" if r.returncode == 0 else (r.stderr or "conversion impossible")[:200]
    ff = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else None)
    if ff:
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                            str(dst)], capture_output=True, text=True, timeout=60)
        return "" if r.returncode == 0 else (r.stderr or "conversion impossible")[:200]
    return f"format audio non pris en charge ({src.suffix})"


def transcribe(audio: Path, lang: str = "fr") -> dict:
    exe, model = whisper_bin(), model_path()
    if not (exe and model):
        audio.unlink(missing_ok=True)
        return {"text": "", "error": "Dictée locale non installée (whisper.cpp + modèle). Relance l'installateur."}
    try:
        with tempfile.TemporaryDirectory(prefix="jarvis-dictee-") as tmp:
            wav = Path(tmp) / "a.wav"
            err = _to_wav(audio, wav)
            if err:
                return {"text": "", "error": err}
            r = subprocess.run([exe, "-m", str(model), "-f", str(wav), "-l", lang or "fr", "-nt", "-np",
                                "--prompt", "Jarvis, Xcode, GitHub, Firebase, La Boussole."],      # vocabulaire attendu
                               capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                return {"text": "", "error": (r.stderr or "échec de la transcription")[-200:]}
            text = " ".join(ln.strip() for ln in r.stdout.splitlines() if ln.strip())
            text = text.replace("[BLANK_AUDIO]", "").strip()
            return {"text": text, "error": "" if text else "Je n'ai rien entendu."}
    finally:
        audio.unlink(missing_ok=True)       # la voix ne reste pas sur le disque


# ------------------------------------------------------------------ voix de lecture (synthèse vocale macOS, locale)
_VOICES: list = []
PHRASE = "Bonjour, je suis Jarvis. Ta présentation est prête, je l'ai vérifiée."


def parse_voices(text: str) -> list[dict]:
    """Lignes de « say -v ? » → voix françaises, les plus naturelles d'abord (Premium, puis Améliorée)."""
    out = []
    for ln in text.splitlines():
        m = re.match(r"^(.+?)\s{2,}(fr_[A-Z]{2})\s+#", ln)
        if not m:
            continue
        name, loc = m.group(1).strip(), m.group(2)
        q = 2 if re.search(r"premium", name, re.I) else 1 if re.search(r"am[ée]lior|enhanced", name, re.I) else 0
        out.append({"name": name, "locale": loc, "quality": q})
    return sorted(out, key=lambda v: (-v["quality"], v["locale"] != "fr_FR", v["name"]))


def voices(refresh: bool = False) -> list[dict]:
    global _VOICES
    if _VOICES and not refresh:
        return _VOICES
    try:
        txt = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        txt = ""
    _VOICES = parse_voices(txt)
    return _VOICES


def speak(text: str, voice: str = "", rate: int = 190) -> bool:
    try:
        args = ["say", "-r", str(int(rate or 190))] + (["-v", voice] if voice else []) + [text[:1000]]
        r = subprocess.run(args, capture_output=True, timeout=120)
        if r.returncode != 0 and voice:
            r = subprocess.run(["say", "-r", str(int(rate or 190)), text[:1000]], capture_output=True, timeout=120)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

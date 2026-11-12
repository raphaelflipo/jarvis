#!/bin/bash
# Source installer for the macOS edition. --check never changes the machine.
# Optional automation: JARVIS_YES=1 accepts the base install, never extra features.
# JARVIS_MODEL overrides the model. JARVIS_STOP_RUNNING=1 permits an update to stop Jarvis.
set -Eeuo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JH="$HOME/.jarvis"
WS="$HOME/JarvisWorkspace"
BIN="$HOME/.local/bin"
LOG=""
STAGE=""
VERSION="3.3.0-rc.1"
[[ ! -f "$SRC/VERSION" ]] || VERSION="$(cat "$SRC/VERSION")"
step() { printf '\n━━ %s\n' "$*"; }
ok() { printf '✔ %s\n' "$*"; }
warn() { printf '⚠ %s\n' "$*"; }
fail() { printf '✖ %s\n' "$*" >&2; [[ -z "$LOG" ]] || printf 'Journal : %s\n' "$LOG" >&2; exit 1; }
ask() {
  [[ "${JARVIS_YES:-0}" != 1 && -t 0 ]] || return 1
  local answer
  read -r -p "$1 [o/N] " answer || return 1
  [[ "$answer" =~ ^([oOyY]|oui|yes)$ ]]
}
cleanup() { [[ -z "$STAGE" ]] || rm -rf -- "$STAGE"; }
trap cleanup EXIT
trap 'fail "Une étape a échoué (ligne $LINENO). Lisez le journal avant de relancer."' ERR
case "${1:-}" in
  --help|-h)
    printf '%s\n' 'Usage : bash install.sh [--check|--dry-run]' \
      'macOS 14+, puce Apple Silicon, 16 Go de RAM et 30 Go libres.' \
      '--check et --dry-run : vérifications sans écriture ni téléchargement.' \
      'Prérequis : outils Apple et Homebrew (https://brew.sh).' \
      'JARVIS_YES=1 : installation de base sans options supplémentaires.'
    exit 0 ;;
  ''|--check|--dry-run) ;;
  *) fail "Option inconnue : $1 (voir --help)." ;;
esac
[[ $# -le 1 ]] || fail "Une seule option est acceptée (voir --help)."

step "Vérification de Jarvis $VERSION et du Mac"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]] || fail "Version du paquet invalide."
[[ "$(uname -s)" == Darwin ]] || fail "Cet installateur concerne uniquement macOS."
[[ "$(uname -m)" == arm64 ]] || fail "Un Mac Apple Silicon est requis."
[[ $EUID -ne 0 ]] || fail "Lancez ce script avec votre compte habituel, sans sudo."
MACOS="$(sw_vers -productVersion)"; MAJOR="${MACOS%%.*}"
(( MAJOR >= 14 )) || fail "macOS 14 ou plus récent est requis (version détectée : $MACOS)."
RAM=$(( $(sysctl -n hw.memsize) / 1073741824 ))
FREE="$(df -g "$HOME" | awk 'NR==2 {print $4}')"
(( RAM >= 16 )) || fail "Cette édition nécessite au moins 16 Go de mémoire."
[[ "$FREE" =~ ^[0-9]+$ ]] || fail "Impossible de vérifier l'espace de stockage."
(( FREE >= 30 )) || fail "Libérez au moins 30 Go avant l'installation (actuellement : $FREE Go)."
for file in jarvis/jarvis.py jarvis/web/index.html requirements.txt macos/JarvisApp.swift macos/JarvisAgenda.swift assets/AppIcon.icns tests/test_offline.py uninstall.sh; do
  [[ -f "$SRC/$file" && ! -L "$SRC/$file" ]] || fail "Fichier absent ou lien inattendu : $file."
done
if [[ -f "$SRC/MANIFEST.sha256" ]]; then
  (cd "$SRC" && /usr/bin/shasum -a 256 -c MANIFEST.sha256 >/dev/null) || fail "Les fichiers du paquet ont été modifiés ou sont incomplets."
fi
xcode-select -p >/dev/null 2>&1 || fail "Installez les outils Apple avec xcode-select --install, puis relancez ce script."
xcrun --find swiftc >/dev/null 2>&1 || fail "Le compilateur Swift est absent des outils Apple sélectionnés."
[[ -x /opt/homebrew/bin/brew ]] || fail "Homebrew est requis. Installez-le depuis https://brew.sh, puis relancez ce script."
ok "macOS $MACOS · Apple Silicon · $RAM Go de RAM · $FREE Go libres"
if [[ "${1:-}" == --check || "${1:-}" == --dry-run ]]; then
  ok "Vérifications terminées. Aucun fichier modifié, aucun téléchargement."
  exit 0
fi

umask 077
mkdir -p "$JH/logs"
chmod 700 "$JH"
LOG="$JH/logs/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
printf '%s\n' 'Cette préversion télécharge ses dépendances et un modèle local (plusieurs Go).' \
  'Les options supplémentaires sont refusées par défaut. Aucun achat ni compte requis.'
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
# Keep model downloads on this Mac even if the shell has a remote OLLAMA_HOST.
export OLLAMA_HOST="127.0.0.1:11434"

step "Dépendances nécessaires : Python et Ollama"
for package in python@3.12 ollama; do
  if brew list --formula "$package" >/dev/null 2>&1; then ok "$package déjà installé"
  else brew install "$package" || fail "Échec de l'installation de $package."; fi
done
PY=/opt/homebrew/bin/python3.12
[[ -x "$PY" ]] || fail "Python 3.12 est introuvable."
# Validate existing configuration before touching an installed app or its sources.
"$PY" - "$JH/config.json" <<'PYTHON'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
if path.exists():
    if not isinstance(json.loads(path.read_text()), dict):
        raise SystemExit("La configuration existante doit être un objet JSON.")
PYTHON
STAGE="$(mktemp -d "$JH/.install-XXXXXX")"
mkdir -p "$STAGE/source/jarvis" "$STAGE/source/tests"
cp -R "$SRC/jarvis/." "$STAGE/source/jarvis/"
cp "$SRC/tests/test_offline.py" "$STAGE/source/tests/"
[[ ! -f "$SRC/tests/verifier.py" ]] || cp "$SRC/tests/verifier.py" "$STAGE/source/tests/"

step "Préparation de l'application native"
APPDIR=/Applications
[[ -w "$APPDIR" ]] || APPDIR="$HOME/Applications"
APP="$APPDIR/Jarvis.app"
if [[ -e "$APP" ]]; then
  identifier=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$APP/Contents/Info.plist" 2>/dev/null || true)
  [[ "$identifier" == local.jarvis.app ]] || fail "Une autre application porte déjà le nom Jarvis ; elle est conservée."
fi
STAGED_APP="$STAGE/Jarvis.app"
mkdir -p "$STAGED_APP/Contents/MacOS" "$STAGED_APP/Contents/Resources"
cp "$SRC/assets/AppIcon.icns" "$STAGED_APP/Contents/Resources/AppIcon.icns"
"$PY" - "$STAGED_APP/Contents/Info.plist" "$VERSION" <<'PYTHON'
import plistlib, sys
info = {
    "CFBundleName": "Jarvis", "CFBundleDisplayName": "Jarvis",
    "CFBundleIdentifier": "local.jarvis.app", "CFBundleExecutable": "Jarvis",
    "CFBundleIconFile": "AppIcon", "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": sys.argv[2].split("-", 1)[0], "CFBundleVersion": "33",
    "LSMinimumSystemVersion": "14.0", "LSApplicationCategoryType": "public.app-category.productivity",
    "NSHighResolutionCapable": True, "NSSupportsAutomaticGraphicsSwitching": True,
    "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    "NSAppleEventsUsageDescription": "Jarvis pilote vos applications quand vous le demandez.",
    "NSMicrophoneUsageDescription": "Jarvis écoute votre voix lorsque vous appuyez sur le micro.",
    "NSCalendarsFullAccessUsageDescription": "Jarvis consulte et crée vos événements à votre demande.",
    "NSCalendarsUsageDescription": "Jarvis consulte et crée vos événements à votre demande.",
    "NSRemindersFullAccessUsageDescription": "Jarvis consulte et crée vos rappels à votre demande.",
    "NSRemindersUsageDescription": "Jarvis consulte et crée vos rappels à votre demande.",
    "NSHumanReadableCopyright": "Jarvis — logiciel libre sous licence MIT",
}
with open(sys.argv[1], "wb") as stream:
    plistlib.dump(info, stream)
PYTHON
xcrun swiftc -O -target arm64-apple-macos14.0 -o "$STAGED_APP/Contents/MacOS/Jarvis" "$SRC/macos/JarvisApp.swift" \
  -framework Cocoa -framework WebKit -framework Carbon -framework EventKit || fail "Compilation de l'application impossible ; l'application précédente est conservée."
xcrun swiftc -O -target arm64-apple-macos14.0 -o "$STAGED_APP/Contents/MacOS/jarvis-agenda" "$SRC/macos/JarvisAgenda.swift" \
  -framework EventKit || fail "Compilation de l'outil Calendrier/Rappels impossible."
codesign --force --sign - "$STAGED_APP/Contents/MacOS/jarvis-agenda"
codesign --force --sign - "$STAGED_APP"
codesign --verify --deep --strict "$STAGED_APP"
ok "Application compilée et signature locale vérifiée (sans notarisation Apple)"

step "Bibliothèques et tests hors ligne"
if [[ -x "$JH/venv/bin/python3" ]]; then
  "$JH/venv/bin/python3" -c 'import sys; assert sys.version_info >= (3, 11)' || fail "L'environnement Python existant est trop ancien ; conservez vos données et recréez seulement ~/.jarvis/venv."
else
  "$PY" -m venv "$JH/venv"
fi
"$JH/venv/bin/python3" -m pip install --quiet --upgrade pip
"$JH/venv/bin/python3" -m pip install --quiet -r "$SRC/requirements.txt" || fail "Installation des bibliothèques impossible."
if "$JH/venv/bin/python3" "$STAGE/source/tests/test_offline.py" > "$JH/logs/selftest.log" 2>&1; then
  ok "$(tail -1 "$JH/logs/selftest.log")"
else
  fail "Les tests ont échoué. L'application précédente est conservée. Voir ~/.jarvis/logs/selftest.log."
fi

step "Moteur IA local"
if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then
  ok "Ollama déjà actif : réutilisation sans arrêt ni changement de réglages."
else
  OLL_PLIST="$HOME/Library/LaunchAgents/com.jarvis.ollama.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  # Only the Jarvis-owned service is replaced. Existing Ollama services are untouched.
  [[ ! -f "$OLL_PLIST" ]] || launchctl bootout "gui/$(id -u)" "$OLL_PLIST" >/dev/null 2>&1 || true
  "$PY" - "$OLL_PLIST" "$JH/logs/ollama.log" <<'PYTHON'
import plistlib, sys
info = {
    "Label": "com.jarvis.ollama", "ProgramArguments": ["/opt/homebrew/bin/ollama", "serve"],
    "EnvironmentVariables": {"OLLAMA_HOST": "127.0.0.1:11434", "OLLAMA_NUM_PARALLEL": "1",
                             "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_KEEP_ALIVE": "5m"},
    "RunAtLoad": True, "KeepAlive": True, "ProcessType": "Interactive",
    "StandardOutPath": sys.argv[2], "StandardErrorPath": sys.argv[2],
}
with open(sys.argv[1], "wb") as stream:
    plistlib.dump(info, stream)
PYTHON
  launchctl bootstrap "gui/$(id -u)" "$OLL_PLIST" || fail "Impossible de démarrer Ollama. Voir ~/.jarvis/logs/ollama.log."
  for _ in {1..30}; do
    if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then break; fi
    sleep 1
  done
  curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null || fail "Ollama ne répond pas."
  ok "Service local de Jarvis actif (127.0.0.1 uniquement)."
fi
MODEL="${JARVIS_MODEL:-}"
if [[ -z "$MODEL" ]]; then
  MODEL="$("$PY" - "$JH/config.json" <<'PYTHON'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
try:
    model = json.loads(path.read_text()).get("model") if path.exists() else None
except (OSError, ValueError):
    model = None
print(model or "qwen3:8b")
PYTHON
)"
fi
[[ "$MODEL" != -* && "$MODEL" != *[[:space:]]* ]] || fail "Nom du modèle invalide."
step "Modèle local : $MODEL"
ollama pull "$MODEL" || fail "Téléchargement du modèle interrompu. Relancez pour le reprendre."
if ask "Télécharger aussi le modèle de recherche sémantique (nomic-embed-text) ?"; then
  ollama pull nomic-embed-text || warn "Recherche sémantique non préparée."
fi
if ask "Installer Chromium pour permettre à Jarvis de naviguer sur le Web ?"; then
  "$JH/venv/bin/python3" -m playwright install chromium || warn "Navigateur intégré non installé."
fi
if ask "Installer les outils de programmation supplémentaires (GitHub CLI, Node, ripgrep, xcbeautify) ?"; then
  brew install gh node ripgrep xcbeautify || warn "Certains outils supplémentaires ne sont pas installés."
fi

step "Mise en place de Jarvis"
# Locate only this user's exact Jarvis server. Do not terminate other Python apps.
SERVER_PIDS="$("$PY" - "$JH/app/jarvis.py" <<'PYTHON'
import os, subprocess, sys
for line in subprocess.check_output(["/bin/ps", "-axo", "uid=,pid=,command="], text=True).splitlines():
    parts = line.strip().split(None, 2)
    if len(parts) == 3 and parts[0] == str(os.getuid()) and (sys.argv[1] + " serve") in parts[2]:
        print(parts[1])
PYTHON
)"
if [[ -n "$SERVER_PIDS" ]] || pgrep -x Jarvis >/dev/null; then
  if [[ "${JARVIS_STOP_RUNNING:-0}" != 1 ]] && ! ask "Jarvis fonctionne déjà. Arrêter ses tâches pour appliquer la mise à jour ?"; then
    fail "Mise à jour suspendue. Fermez Jarvis et ses tâches, puis relancez l'installateur."
  fi
  osascript -e 'tell application "Jarvis" to quit' >/dev/null 2>&1 || true
  for pid in $SERVER_PIDS; do kill -TERM "$pid" 2>/dev/null || true; done
  sleep 2
  for pid in $SERVER_PIDS; do kill -0 "$pid" 2>/dev/null && fail "Jarvis fonctionne encore. Attendez la fin de ses tâches avant de relancer."; done
fi
# Preflight has completed; retain the previous source and app under unique names.
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$APPDIR" "$WS" "$BIN" "$JH/tests"
[[ ! -e "$JH/app" ]] || mv "$JH/app" "$JH/app.previous-$STAMP"
mv "$STAGE/source/jarvis" "$JH/app"
cp "$STAGE/source/tests/"*.py "$JH/tests/"
cp "$SRC/requirements.txt" "$SRC/uninstall.sh" "$JH/"
chmod 755 "$JH/uninstall.sh"
[[ ! -e "$APP" ]] || mv "$APP" "$APPDIR/.Jarvis.previous-$STAMP.app"
mv "$STAGED_APP" "$APP"
"$PY" - "$JH/config.json" "$MODEL" "$WS" <<'PYTHON'
import json, os, pathlib, sys
path, model, workspace = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
# A malformed existing config is not silently discarded.
config = json.loads(path.read_text()) if path.exists() else {}
config["model"] = model
config.setdefault("workspace", workspace)
config.setdefault("autonomy", "prudent")
config.setdefault("sandbox", True)
config.setdefault("num_ctx", 8192)
config.setdefault("max_parallel_tasks", 1)
config.setdefault("project_dirs", [])
config.setdefault("server", {"host": "127.0.0.1", "port": 8765})
temporary = path.with_suffix(".install.tmp")
temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False))
os.chmod(temporary, 0o600)
temporary.replace(path)
PYTHON
cat > "$BIN/jarvis" <<'LAUNCHER'
#!/bin/zsh
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:$PATH"
if [[ $# -eq 0 ]]; then
  if [[ -d "$HOME/Applications/Jarvis.app" ]]; then exec open "$HOME/Applications/Jarvis.app"; fi
  if [[ -d /Applications/Jarvis.app ]]; then exec open /Applications/Jarvis.app; fi
fi
exec "$HOME/.jarvis/venv/bin/python3" "$HOME/.jarvis/app/jarvis.py" "$@"
LAUNCHER
chmod 755 "$BIN/jarvis"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" >/dev/null 2>&1 || true
ok "Installé dans $APP"
printf '\n%s\n' 'Ouvrez Jarvis depuis Applications ou Spotlight.' \
  "Commande Terminal : $BIN/jarvis" \
  'Accessibilité, capture d’écran, calendrier et micro : autorisez seulement les fonctions souhaitées dans les réglages macOS.' \
  'Désinstallation : bash ~/.jarvis/uninstall.sh (les modèles partagés sont conservés).' \
  'Aucun accès distant ni compte en ligne n’a été activé.' \
  "Journal : $LOG"
if ask "Ouvrir Jarvis maintenant ?"; then open "$APP"; fi

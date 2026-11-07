#!/bin/bash
# =============================================================================
#  JARVIS v3 — Agent IA local, gratuit et sécurisé pour macOS (Apple Silicon)
#  Lancé automatiquement par « Installer Jarvis.app » (ou : bash install.sh)
#  Ré-exécutable à tout moment pour mettre à jour (config, mémoire et historique conservés).
#
#  Options : JARVIS_MODEL=qwen3:14b  JARVIS_VISION=0|1  JARVIS_SKIP_LOGIN=1  JARVIS_YES=1
# =============================================================================
set -uo pipefail
G="\033[38;2;124;252;0m"; B="\033[1m"; Y="\033[33m"; R="\033[31m"; D="\033[2m"; X="\033[0m"
step() { echo -e "\n${G}${B}━━ $* ${X}"; }
ok()   { echo -e "${G}✔${X} $*"; }
warn() { echo -e "${Y}⚠${X} $*"; }
fail() { echo -e "${R}✖ $*${X}"; echo -e "${D}Journal complet : $LOG${X}"; osascript -e "display alert \"Installation de Jarvis interrompue\" message \"$*\"" >/dev/null 2>&1; exit 1; }
ask()  { [[ "${JARVIS_YES:-0}" == "1" ]] && return 0; local r; read -r -p "$(echo -e "${B}$1${X} [o/N] ")" r </dev/tty; [[ "$r" =~ ^([oOyY]|oui|yes)$ ]]; }

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JH="$HOME/.jarvis"
WS="$HOME/JarvisWorkspace"
BIN="$HOME/.local/bin"
UIDN=$(id -u)
mkdir -p "$JH/logs"; chmod 700 "$JH"
LOG="$JH/logs/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

clear
echo -e "${G}${B}"
cat <<'EOF'
        ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
        ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
        ██║███████║██████╔╝██║   ██║██║███████╗
   ██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
   ╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
    ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝   v3.1 · local · gratuit · sécurisé
EOF
echo -e "${X}"
echo "Durée : 20 à 45 minutes (surtout le téléchargement des modèles IA, 6 à 25 Go)."
echo "Ton mot de passe de session sera demandé une fois (Homebrew). Rien n'est payant."

# --------------------------------------------------------------------------- 1
step "1/12 Vérification du Mac"
[[ "$(uname -s)" == "Darwin" ]] || fail "Ce programme est prévu pour macOS."
[[ "$(uname -m)" == "arm64" ]]  || fail "Une puce Apple Silicon (M1…M5) est nécessaire."
[[ $EUID -ne 0 ]] || fail "Ne lance pas l'installation avec sudo."
MACOS=$(sw_vers -productVersion); MAJ=${MACOS%%.*}
(( MAJ >= 13 )) || fail "macOS 13 ou plus récent requis (tu as $MACOS)."
RAM=$(( $(sysctl -n hw.memsize) / 1073741824 ))
FREE=$(df -g "$HOME" | awk 'NR==2 {print $4}')
ok "macOS $MACOS · $(sysctl -n machdep.cpu.brand_string) · ${RAM} Go de RAM · ${FREE} Go libres"
(( FREE < 30 )) && warn "Moins de 30 Go libres : les modèles risquent de ne pas tenir. Garde au moins 15 Go libres APRÈS installation (mémoire virtuelle de macOS)."
curl -fsS --max-time 10 https://ollama.com >/dev/null || fail "Pas d'accès à Internet (nécessaire uniquement pour l'installation)."

# --------------------------------------------------------------------------- 2
step "2/12 Outils de développement Apple (gratuits)"
if ! xcode-select -p >/dev/null 2>&1; then
  xcode-select --install 2>/dev/null || true
  echo "Une fenêtre s'est ouverte : clique sur « Installer », puis patiente…"
  until xcode-select -p >/dev/null 2>&1; do sleep 10; done
fi
ok "Outils de ligne de commande présents"

# --------------------------------------------------------------------------- 3
step "3/12 Homebrew"
if [[ ! -x /opt/homebrew/bin/brew ]]; then
  echo "Installation de Homebrew (mot de passe de session demandé)…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty || fail "Échec de Homebrew"
fi
eval "$(/opt/homebrew/bin/brew shellenv)"
grep -q 'brew shellenv' "$HOME/.zprofile" 2>/dev/null || echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
ok "Homebrew $(brew --version | head -1 | awk '{print $2}')"

# --------------------------------------------------------------------------- 4
step "4/12 Logiciels : Python, Git, GitHub CLI, Node, Ollama, ripgrep, xcbeautify"
for pkg in python@3.12 git gh node ollama ripgrep xcbeautify; do
  if brew list --formula "$pkg" >/dev/null 2>&1; then ok "$pkg"; else brew install "$pkg" || { [[ "$pkg" == xcbeautify ]] && warn "xcbeautify ignoré" || fail "Échec de l'installation de $pkg"; }; fi
done
brew upgrade ollama >/dev/null 2>&1 || true
[[ -d "/Applications/Visual Studio Code.app" ]] || brew install --cask visual-studio-code || warn "VS Code non installé"
[[ -d "/Applications/Visual Studio Code.app" ]] && ! command -v code >/dev/null && ln -sf "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" /opt/homebrew/bin/code
command -v firebase >/dev/null || npm install -g firebase-tools --no-fund --no-audit || warn "firebase-tools non installé"
[[ -d /Applications/Xcode.app ]] || warn "Xcode absent : installe-le gratuitement depuis l'App Store pour compiler des apps iOS/macOS."
ok "Logiciels prêts"

# --------------------------------------------------------------------------- 5
step "5/12 Choix des modèles IA pour ${RAM} Go de RAM"
if (( RAM >= 32 )); then MODELS="qwen3-coder:30b qwen3:30b qwen3:14b"; PAR=4; CTX=32768; VIS=1
elif (( RAM >= 24 )); then MODELS="gpt-oss:20b qwen3:14b qwen3:8b"; PAR=3; CTX=16384; VIS=1   # gpt-oss : 2,4× plus rapide (mesuré sur M5)
else MODELS="qwen3:8b qwen2.5-coder:7b"; PAR=2; CTX=16384; VIS=0; fi
[[ -n "${JARVIS_MODEL:-}" ]] && MODELS="$JARVIS_MODEL"
[[ -n "${JARVIS_VISION:-}" ]] && VIS="$JARVIS_VISION"
echo "Tâches simultanées : $PAR · mémoire de travail : $CTX jetons"
# Flux de génération réellement simultanés dans Ollama. Chaque flux réserve sa propre mémoire de contexte :
# au-delà de 2 sous 48 Go, le Mac part en swap (mesuré : 14 Go de swap avec 4 flux sur 24 Go) et tout ralentit.
# Les tâches en plus restent parallèles côté Jarvis : leurs requêtes s'intercalent.
if (( RAM >= 48 )); then OLL_PAR=$((PAR + 1)); else OLL_PAR=2; fi

# --------------------------------------------------------------------------- 6
step "6/12 Moteur IA local (Ollama optimisé pour le parallélisme, accessible uniquement depuis ce Mac)"
brew services stop ollama >/dev/null 2>&1 || true
if [[ -d /Applications/Ollama.app ]]; then
  osascript -e 'quit app "Ollama"' >/dev/null 2>&1 || true
  warn "L'app Ollama a été fermée : Jarvis utilise son propre service. Désactive l'ouverture auto d'Ollama.app (Réglages › Général › Ouverture)."
fi
pkill -f "ollama serve" >/dev/null 2>&1 || true
sleep 1
OLL_PLIST="$HOME/Library/LaunchAgents/com.jarvis.ollama.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$OLL_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.jarvis.ollama</string>
  <key>ProgramArguments</key><array><string>/opt/homebrew/bin/ollama</string><string>serve</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>OLLAMA_HOST</key><string>127.0.0.1:11434</string>
    <key>OLLAMA_NUM_PARALLEL</key><string>$OLL_PAR</string>
    <key>OLLAMA_MAX_LOADED_MODELS</key><string>2</string>
    <key>OLLAMA_FLASH_ATTENTION</key><string>1</string>
    <key>OLLAMA_KV_CACHE_TYPE</key><string>q8_0</string>
    <key>OLLAMA_KEEP_ALIVE</key><string>30m</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$JH/logs/ollama.log</string>
  <key>StandardErrorPath</key><string>$JH/logs/ollama.log</string>
</dict></plist>
EOF
launchctl bootout "gui/$UIDN" "$OLL_PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UIDN" "$OLL_PLIST" || warn "launchctl bootstrap : vérifie ~/.jarvis/logs/ollama.log"
for i in {1..40}; do curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done
curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null || fail "Ollama ne répond pas (voir ~/.jarvis/logs/ollama.log)"
ok "Ollama $(ollama --version 2>/dev/null | awk '{print $NF}') actif (démarre tout seul à chaque session)"

# --------------------------------------------------------------------------- 7
step "7/12 Téléchargement des modèles (le plus long — tu peux faire autre chose)"
MODEL=""
for m in $MODELS; do
  echo -e "${D}→ $m${X}"
  if ollama pull "$m"; then MODEL="$m"; break; else warn "$m indisponible, modèle suivant…"; fi
done
[[ -n "$MODEL" ]] || fail "Impossible de télécharger un modèle IA."
ok "Cerveau : $MODEL"
ollama pull nomic-embed-text && ok "Recherche par le sens : nomic-embed-text" || warn "Modèle d'embeddings non installé"
VMODEL=""
if [[ "$VIS" == "1" ]]; then
  for v in gemma4:e4b qwen2.5vl:7b; do ollama pull "$v" && { VMODEL="$v"; break; }; done
  [[ -n "$VMODEL" ]] && ok "Vision (écran, captures) : $VMODEL" || warn "Pas de modèle vision"
else
  warn "Vision ignorée (16 Go de RAM). Plus tard : JARVIS_VISION=1 et relance l'installateur."
fi

# Dictée vocale locale (whisper.cpp + modèle large-v3-turbo compressé, ~550 Mo) : gratuite, rien ne part sur Internet
WHISPER_MODEL="$HOME/.jarvis/models/ggml-large-v3-turbo-q5_0.bin"
if ! command -v whisper-cli >/dev/null; then brew install whisper-cpp >>"$LOG" 2>&1 || warn "whisper.cpp non installé (dictée locale indisponible)"; fi
if command -v whisper-cli >/dev/null && [[ ! -s "$WHISPER_MODEL" ]]; then
  mkdir -p "$HOME/.jarvis/models"
  curl -L --fail --progress-bar -o "$WHISPER_MODEL.part" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin" && mv "$WHISPER_MODEL.part" "$WHISPER_MODEL" \
    || { rm -f "$WHISPER_MODEL.part"; warn "Modèle de dictée non téléchargé"; }
fi
[[ -s "$WHISPER_MODEL" ]] && ok "Dictée vocale locale : whisper large-v3-turbo"

# Moteur MLX d'Apple (facultatif) : ~30 % plus rapide que llama.cpp pour gpt-oss sur puce M (mesuré sur M5 : 40 contre 30 jetons/s)
if [[ "$MODEL" == gpt-oss:20b* ]] && ask "Installer aussi le moteur MLX d'Apple (12 Go de plus, environ 30 % plus rapide) ?"; then
  if [[ ! -x "$JH/mlx-venv/bin/mlx_lm.server" ]]; then
    "$(brew --prefix)/bin/python3.12" -m venv "$JH/mlx-venv" >>"$LOG" 2>&1 && "$JH/mlx-venv/bin/pip" install -q mlx-lm >>"$LOG" 2>&1
  fi
  "$JH/mlx-venv/bin/python" -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/gpt-oss-20b-MXFP4-Q8')" \
    && ok "Moteur MLX installé : active-le dans Réglages › Général › Moteur" || warn "Moteur MLX non installé"
fi

# Images sur le Mac (facultatif) : Z-Image-Turbo (Apache 2.0) via mflux, ~6 Go, ~5 Go de mémoire pendant la création
if [[ "$(uname -m)" == "arm64" ]] && ask "Installer la création d'images sur le Mac (environ 6 Go, gratuit) ?"; then
  if [[ ! -x "$JH/image-venv/bin/mflux-generate-z-image-turbo" ]]; then
    "$(brew --prefix)/bin/python3.12" -m venv "$JH/image-venv" >>"$LOG" 2>&1 && "$JH/image-venv/bin/pip" install -q mflux >>"$LOG" 2>&1
  fi
  "$JH/image-venv/bin/python" -c "from huggingface_hub import snapshot_download; snapshot_download('filipstrand/Z-Image-Turbo-mflux-4bit')" \
    >>"$LOG" 2>&1 && ok "Création d'images installée" || warn "Création d'images non installée"
fi

# --------------------------------------------------------------------------- 8
step "8/12 Installation de Jarvis"
osascript -e 'quit app "Jarvis"' >/dev/null 2>&1 || true
pkill -f ".jarvis/app/jarvis.py serve" >/dev/null 2>&1 || true     # arrête l'ancien serveur (mise à jour)
sleep 1
mkdir -p "$JH/app" "$JH/tests" "$WS" "$BIN"
rm -rf "$JH/app"/*
cp -R "$SRC/jarvis/." "$JH/app/"
cp -R "$SRC/tests/." "$JH/tests/"
cp "$SRC/requirements.txt" "$SRC/uninstall.sh" "$JH/" && chmod +x "$JH/uninstall.sh"
xattr -dr com.apple.quarantine "$JH" 2>/dev/null || true
PY=/opt/homebrew/bin/python3.12
if [[ -x "$JH/venv/bin/python3" ]] && ! "$JH/venv/bin/python3" -c "import sys; assert sys.version_info >= (3,11)" 2>/dev/null; then rm -rf "$JH/venv"; fi
[[ -x "$JH/venv/bin/python3" ]] || "$PY" -m venv "$JH/venv" || fail "Création de l'environnement Python impossible"
"$JH/venv/bin/pip" install --quiet --upgrade pip
echo "Bibliothèques Python (quelques minutes)…"
"$JH/venv/bin/pip" install --quiet --upgrade -r "$JH/requirements.txt" || fail "Échec de l'installation des bibliothèques Python"
ok "Bibliothèques installées"
"$JH/venv/bin/python3" -m playwright install chromium >/dev/null 2>&1 && ok "Navigateur intégré (Chromium)" || warn "Chromium non installé : navigation web désactivée"
# Python de développement de l'agent (séparé de celui de Jarvis) : python, pip, pytest
[[ -x "$WS/.venv/bin/python" ]] || "$PY" -m venv "$WS/.venv"
"$WS/.venv/bin/pip" install --quiet --upgrade pip pytest >/dev/null 2>&1 && ok "Python de développement de l'agent (pytest)" || warn "Python de développement non préparé"

# migration depuis Atlas (version précédente)
if [[ -f "$HOME/.atlas/memory.md" && ! -s "$JH/memory.md" ]]; then
  cp "$HOME/.atlas/memory.md" "$JH/memory.md" && ok "Mémoire de l'ancienne version (Atlas) importée"
fi
touch "$JH/memory.md"

# dossiers projets
DIRS=()
if ! grep -q '"project_dirs"' "$JH/config.json" 2>/dev/null; then     # seulement à la première installation
  for d in "$HOME/Developer" "$HOME/Projets" "$HOME/Projects" "$HOME/Code" "$HOME/Documents/GitHub"; do
    [[ -d "$d" ]] && ask "Autoriser Jarvis à travailler (écrire) dans $d ?" && DIRS+=("$d")
  done
fi
DIRS_JSON=$(printf '%s\n' "${DIRS[@]:-}" | "$JH/venv/bin/python3" -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')

"$JH/venv/bin/python3" - "$MODEL" "$VMODEL" "$CTX" "$PAR" "$WS" "$DIRS_JSON" <<'EOF'
import json, os, sys, pathlib
model, vision, ctx, par, ws, dirs = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], json.loads(sys.argv[6])
p = pathlib.Path.home() / ".jarvis" / "config.json"
c = json.loads(p.read_text()) if p.exists() else {}
if c.get("config_version", 0) < 31:      # migration : réglages mémoire recalibrés en 3.1
    c["num_ctx"], c["max_parallel_tasks"] = ctx, par
c.update(model=model, num_ctx=c.get("num_ctx", ctx), max_parallel_tasks=c.get("max_parallel_tasks", par), config_version=31)
c.setdefault("autonomy", "autonome"); c.setdefault("workspace", ws); c.setdefault("sandbox", True)
if vision: c["vision_model"] = vision
c["project_dirs"] = sorted(set(c.get("project_dirs", []) + dirs))
p.write_text(json.dumps(c, indent=2, ensure_ascii=False)); os.chmod(p, 0o600)
EOF
ok "Configuration : ~/.jarvis/config.json"

cat > "$BIN/jarvis" <<'EOF'
#!/bin/zsh
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:$PATH"
if [[ $# -eq 0 ]] && [[ -d /Applications/Jarvis.app || -d "$HOME/Applications/Jarvis.app" ]]; then
  open -a Jarvis; exit 0
fi
exec "$HOME/.jarvis/venv/bin/python3" "$HOME/.jarvis/app/jarvis.py" "$@"
EOF
chmod 755 "$BIN/jarvis"
grep -q '.local/bin' "$HOME/.zshrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
ok "Commande « jarvis » disponible dans le Terminal"

# --------------------------------------------------------------------------- 9
step "9/12 Application Jarvis (fenêtre native, icône dans le Dock)"
APPDIR=/Applications; [[ -w /Applications ]] || { APPDIR="$HOME/Applications"; mkdir -p "$APPDIR"; }
APP="$APPDIR/Jarvis.app"
osascript -e 'quit app "Jarvis"' >/dev/null 2>&1 || true
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$SRC/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Jarvis</string>
  <key>CFBundleDisplayName</key><string>Jarvis</string>
  <key>CFBundleIdentifier</key><string>local.jarvis.app</string>
  <key>CFBundleExecutable</key><string>Jarvis</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>3.1.0</string>
  <key>CFBundleVersion</key><string>31</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSAppleEventsUsageDescription</key><string>Jarvis pilote tes applications (Mail, Rappels, Finder…) quand tu le lui demandes.</string>
  <key>NSMicrophoneUsageDescription</key><string>Jarvis écoute ta voix quand tu appuies sur le micro. La transcription se fait sur ton Mac.</string>
  <key>NSCalendarsFullAccessUsageDescription</key><string>Jarvis lit et ajoute des événements quand tu le lui demandes. Rien ne quitte ton Mac.</string>
  <key>NSCalendarsUsageDescription</key><string>Jarvis lit et ajoute des événements quand tu le lui demandes. Rien ne quitte ton Mac.</string>
  <key>NSRemindersFullAccessUsageDescription</key><string>Jarvis lit et ajoute des rappels quand tu le lui demandes. Rien ne quitte ton Mac.</string>
  <key>NSRemindersUsageDescription</key><string>Jarvis lit et ajoute des rappels quand tu le lui demandes. Rien ne quitte ton Mac.</string>
  <key>NSHumanReadableCopyright</key><string>Jarvis — 100 % local et open-source</string>
</dict></plist>
EOF
NATIVE=0
if xcrun swiftc -O -target arm64-apple-macos13.0 -o "$APP/Contents/MacOS/Jarvis" "$SRC/macos/JarvisApp.swift" \
     -framework Cocoa -framework WebKit -framework Carbon -framework EventKit >>"$LOG" 2>&1; then
  NATIVE=1; ok "Application native compilée (AppKit + WebKit)"
else
  warn "Compilation native impossible : application de secours (fenêtre WebKit Python)"
  printf '#!/bin/zsh\nexport PATH="/opt/homebrew/bin:$PATH"\nexec "$HOME/.jarvis/venv/bin/python3" "$HOME/.jarvis/app/jarvis.py" app\n' > "$APP/Contents/MacOS/Jarvis"
  chmod +x "$APP/Contents/MacOS/Jarvis"
fi
# Calendrier et Rappels (EventKit) : petit outil rangé dans l'app, l'accès est demandé au nom de « Jarvis »
xcrun swiftc -O -target arm64-apple-macos13.0 -o "$APP/Contents/MacOS/jarvis-agenda" "$SRC/macos/JarvisAgenda.swift" \
  -framework EventKit >>"$LOG" 2>&1 && ok "Calendrier et Rappels : outil compilé" || warn "Outil Calendrier/Rappels non compilé"
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" >/dev/null 2>&1 || true
ok "Jarvis installé dans $APPDIR"

if ! defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "Jarvis.app" && ask "Ajouter Jarvis au Dock ?"; then
  defaults write com.apple.dock persistent-apps -array-add "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>file://$APP/</string><key>_CFURLStringType</key><integer>15</integer></dict></dict></dict>"
  killall Dock >/dev/null 2>&1 || true
  ok "Jarvis est dans le Dock"
fi
LOGIN_PLIST="$HOME/Library/LaunchAgents/com.jarvis.login.plist"
if [[ ! -f "$LOGIN_PLIST" ]] && ask "Démarrer Jarvis en arrière-plan à l'ouverture de session (tâches planifiées et accès iPhone toujours disponibles) ?"; then
  cat > "$LOGIN_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.jarvis.login</string>
  <key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-g</string><string>-j</string><string>-a</string><string>$APP</string></array>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF
  ok "Démarrage automatique activé"
fi

# --------------------------------------------------------------------------- 10
step "10/12 Comptes gratuits et accès à distance"
if [[ "${JARVIS_SKIP_LOGIN:-0}" != "1" ]]; then
  if ! gh auth status >/dev/null 2>&1 && ask "Connecter ton compte GitHub (gratuit) ?"; then
    gh auth login --git-protocol https --web </dev/tty && gh auth setup-git >/dev/null 2>&1 || warn "GitHub ignoré"
  fi
  if command -v firebase >/dev/null && ! firebase login:list 2>/dev/null | grep -q "@" && ask "Connecter Firebase (plan Spark gratuit) ?"; then
    firebase login </dev/tty || warn "Firebase ignoré"
  fi
fi
if [[ -z "$(git config --global user.name)" ]]; then
  read -r -p "Ton nom pour les commits Git : " GN </dev/tty; [[ -n "$GN" ]] && git config --global user.name "$GN"
  read -r -p "Ton e-mail pour les commits Git : " GE </dev/tty; [[ -n "$GE" ]] && git config --global user.email "$GE"
fi
if [[ ! -d /Applications/Tailscale.app ]] && ask "Installer Tailscale (gratuit) pour utiliser Jarvis depuis ton iPhone, en sécurité, partout ?"; then
  brew install --cask tailscale && open -a Tailscale && warn "Connecte-toi dans Tailscale (barre des menus), puis dans Jarvis : Réglages › Accès à distance."
fi

# --------------------------------------------------------------------------- 11
step "11/12 Autotest de Jarvis (bac à sable, sécurité, parallélisme, bureautique…)"
if "$JH/venv/bin/python3" "$JH/tests/test_offline.py" > "$JH/logs/selftest.log" 2>&1; then
  ok "$(tail -1 "$JH/logs/selftest.log")"
else
  warn "Certains autotests échouent : $(tail -1 "$JH/logs/selftest.log") — détails : ~/.jarvis/logs/selftest.log"
  grep "✖" "$JH/logs/selftest.log" | head -8
fi

# --------------------------------------------------------------------------- 12
step "12/12 Autorisations macOS"
echo "Pour piloter la souris et lire l'écran, macOS te demandera d'autoriser « Jarvis » :"
echo "   Réglages Système › Confidentialité et sécurité › Accessibilité  ET  Enregistrement de l'écran"
echo -e "${D}(Tu peux le faire plus tard : Jarvis fonctionne sans, sauf pour la souris et les captures d'écran.)${X}"
if ask "Ouvrir ces réglages maintenant ?"; then
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"; sleep 2
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
fi

echo -e "\n${G}${B}✔ Jarvis est installé.${X}\n"
echo "  • Ouvrir Jarvis         : icône Jarvis (Dock / Applications / Spotlight)"
echo "  • Dans le Terminal       : jarvis \"ta demande\"  ·  jarvis chat  ·  jarvis doctor"
echo "  • Depuis l'iPhone        : Jarvis › Réglages › Accès à distance"
echo "  • Désinstaller           : ~/.jarvis/uninstall.sh"
echo -e "  ${D}Journal : $LOG${X}"
osascript -e 'display notification "Jarvis est prêt. Bonne découverte !" with title "Installation terminée" sound name "Glass"' >/dev/null 2>&1
open -a "$APP"
exit 0

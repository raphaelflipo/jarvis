#!/bin/bash
# Remove only Jarvis-owned files. Shared runtimes, models and workspaces stay.
set -euo pipefail
case "${1:-}" in
  --help|-h)
    printf '%s\n' 'Usage : bash uninstall.sh' 'Confirmation interactive requise. Les modèles Ollama et JarvisWorkspace sont conservés.'
    exit 0 ;;
  '') ;;
  *) printf 'Option inconnue : %s\n' "$1" >&2; exit 1 ;;
esac
[[ "$(uname -s)" == Darwin && $EUID -ne 0 ]] || { printf 'Utilisez votre compte macOS habituel, sans sudo.\n' >&2; exit 1; }
[[ -t 0 ]] || { printf 'Lancez la désinstallation dans un Terminal interactif.\n' >&2; exit 1; }
read -r -p "Arrêter les tâches et désinstaller Jarvis ? [o/N] " answer
[[ "$answer" =~ ^([oOyY]|oui|yes)$ ]] || exit 0
osascript -e 'tell application "Jarvis" to quit' >/dev/null 2>&1 || true
# Match the exact installed script and this account, never every Python/Ollama process.
if [[ -x "$HOME/.jarvis/venv/bin/python3" ]]; then
  "$HOME/.jarvis/venv/bin/python3" - "$HOME/.jarvis/app/jarvis.py" <<'PYTHON'
import os, signal, subprocess, sys, time
pids = []
for line in subprocess.check_output(["/bin/ps", "-axo", "uid=,pid=,command="], text=True).splitlines():
    parts = line.strip().split(None, 2)
    if len(parts) == 3 and parts[0] == str(os.getuid()) and (sys.argv[1] + " serve") in parts[2]:
        pids.append(int(parts[1]))
for pid in pids:
    try: os.kill(pid, signal.SIGTERM)
    except ProcessLookupError: pass
time.sleep(1)
for pid in pids:
    try: os.kill(pid, 0)
    except ProcessLookupError: continue
    raise SystemExit("Jarvis fonctionne encore. Attendez la fin de ses tâches avant de relancer.")
PYTHON
fi
shopt -s nullglob
for plist in "$HOME/Library/LaunchAgents/com.jarvis.login.plist"              "$HOME/Library/LaunchAgents/com.jarvis.ollama.plist"              "$HOME/Library/LaunchAgents/com.jarvis.nightly.plist"              "$HOME/Library/LaunchAgents/com.jarvis.mlx.plist"              "$HOME"/Library/LaunchAgents/com.jarvis.task.*.plist; do
  if [[ -f "$plist" ]]; then
    launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
    rm -f -- "$plist"
  fi
done
for app in /Applications/Jarvis.app "$HOME/Applications/Jarvis.app"; do
  if [[ -d "$app" ]]; then
    identifier=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$app/Contents/Info.plist" 2>/dev/null || true)
    if [[ "$identifier" == local.jarvis.app ]]; then rm -rf -- "$app"; fi
  fi
done
if [[ -f "$HOME/.local/bin/jarvis" ]] && grep -Fq '.jarvis/app/jarvis.py' "$HOME/.local/bin/jarvis"; then
  rm -f -- "$HOME/.local/bin/jarvis"
fi
read -r -p "Supprimer aussi les données de Jarvis (mémoire, historique, configuration et bibliothèques dans ~/.jarvis) ? [o/N] " answer
if [[ "$answer" =~ ^([oOyY]|oui|yes)$ ]]; then rm -rf -- "$HOME/.jarvis"; fi
printf '%s\n' 'Jarvis est désinstallé. JarvisWorkspace, les modèles et Ollama sont conservés.' \
  'Les anciennes copies .Jarvis.previous-*.app éventuelles restent dans Applications.' \
  'Les réglages des services partagés (Tailscale, Git, Homebrew…) n’ont pas été modifiés.'

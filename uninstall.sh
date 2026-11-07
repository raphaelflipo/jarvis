#!/bin/bash
# Désinstallation de Jarvis (ton dossier ~/JarvisWorkspace et tes projets sont conservés).
set -u
read -r -p "Désinstaller Jarvis ? [o/N] " r; [[ "$r" =~ ^[oOyY] ]] || exit 0
UIDN=$(id -u)
osascript -e 'quit app "Jarvis"' >/dev/null 2>&1
pkill -f ".jarvis/app/jarvis.py" >/dev/null 2>&1
for p in "$HOME"/Library/LaunchAgents/com.jarvis.*.plist; do
  [[ -f "$p" ]] && launchctl bootout "gui/$UIDN" "$p" >/dev/null 2>&1; rm -f "$p"
done
command -v tailscale >/dev/null && tailscale serve reset >/dev/null 2>&1
rm -rf /Applications/Jarvis.app "$HOME/Applications/Jarvis.app" "$HOME/.local/bin/jarvis"
read -r -p "Supprimer aussi la mémoire, l'historique et la configuration (~/.jarvis) ? [o/N] " r
[[ "$r" =~ ^[oOyY] ]] && rm -rf "$HOME/.jarvis"
read -r -p "Supprimer aussi les modèles IA (~/.ollama, plusieurs Go) et Ollama ? [o/N] " r
if [[ "$r" =~ ^[oOyY] ]]; then
  /opt/homebrew/bin/brew uninstall ollama >/dev/null 2>&1; rm -rf "$HOME/.ollama"
fi
echo "Jarvis est désinstallé. Ton dossier ~/JarvisWorkspace est conservé."

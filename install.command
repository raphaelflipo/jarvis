#!/bin/bash
cd "$(dirname "$0")" || exit 1
printf '\033]0;Installation de Jarvis\007'
bash ./install.sh
result=$?
printf '\n'
if [[ -t 0 ]]; then read -r -p "Appuyez sur Entrée pour fermer cette fenêtre…" _; fi
exit "$result"

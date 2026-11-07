#!/bin/bash
cd "$(dirname "$0")" || exit 1
printf '\033]0;Installation de Jarvis\007'
bash ./install.sh
echo
read -r -p "Appuie sur Entrée pour fermer cette fenêtre…" _

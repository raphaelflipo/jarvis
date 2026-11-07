#!/bin/bash
# Fabrique dist/Jarvis-v3.1.zip (app « Installer Jarvis » + code) à partir du dépôt.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="dist/Jarvis-v3.1"
APP="$OUT/Installer Jarvis.app"
rm -rf dist && mkdir -p "$OUT"
cp -R "packaging/Installer Jarvis.app" "$OUT/"
mkdir -p "$APP/Contents/Resources/payload"
rsync -a --exclude '.git' --exclude 'dist' --exclude 'packaging' --exclude 'docs' --exclude '__pycache__' \
  ./ "$APP/Contents/Resources/payload/"
chmod +x "$APP/Contents/MacOS/Installer" "$APP/Contents/Resources/payload/"{install.sh,install.command,uninstall.sh}
(cd dist && zip -qr -X Jarvis-v3.1.zip Jarvis-v3.1)
echo "dist/Jarvis-v3.1.zip prêt"

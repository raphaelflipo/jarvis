#!/bin/bash
# Deterministic source installer for Mac Apple Silicon. Does not install Jarvis.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 packaging/build_macos.py --version "${1:-3.3.0-rc.1}" --output "${2:-dist}"

#!/usr/bin/env bash
# Monthly refresh: collect -> rebuild the static dashboard. Push is done by the caller.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-python3}"
"$PY" collect.py
"$PY" build_site.py

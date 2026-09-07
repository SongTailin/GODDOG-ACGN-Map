#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAW_DIR="$ROOT/data/raw-city-boundaries"

mkdir -p "$RAW_DIR"

codes=(
  110000 120000 130000 140000 150000
  210000 220000 230000 310000 320000
  330000 340000 350000 360000 370000
  410000 420000 430000 440000 450000
  460000 500000 510000 520000 530000
  540000 610000 620000 630000 640000
  650000 710000 810000 820000
)

for code in "${codes[@]}"; do
  echo "Fetching $code"
  if ! wget -q -O "$RAW_DIR/$code.json" "https://geojson.cn/api/china/$code.json"; then
    echo "Skip $code because the source is unavailable" >&2
  fi
done

python "$ROOT/scripts/build_map_assets.py"

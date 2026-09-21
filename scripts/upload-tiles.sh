#!/bin/zsh
# build-tiles.py 가 만든 public/tiles/changes.pmtiles 를 Vercel Blob 에 올리고 URL 을 출력한다.
# 올린 뒤 NEXT_PUBLIC_TILES_URL(Vercel env + .env.local)을 새 URL 로 바꾸고 재배포해야 한다.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env.local; set +a
vercel blob put public/tiles/changes.pmtiles \
  --pathname tiles/changes.pmtiles --access public \
  --content-type application/octet-stream --cache-control-max-age 31536000 \
  --rw-token "$BLOB_READ_WRITE_TOKEN"

#!/bin/zsh
# build-tiles.py 가 만든 public/tiles/changes.pmtiles 를 Vercel Blob 에 올리고 URL 을 출력한다.
# 올린 뒤 NEXT_PUBLIC_TILES_URL(Vercel env + .env.local)을 새 URL 로 바꾸고 재배포해야 한다.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env.local; set +a
# 1) tippecanoe 결과가 MBTiles(SQLite) 로 나오는 경우가 있다 — 헤더가 "PMTiles" 가 아니면 tile-join 으로 변환
if [ "$(head -c 7 public/tiles/changes.pmtiles)" != "PMTiles" ]; then
  mv public/tiles/changes.pmtiles public/tiles/changes.mbtiles
  tile-join --force -pk -o public/tiles/changes.pmtiles public/tiles/changes.mbtiles
fi
# 2) 고정 경로에 덮어쓰면 CDN 캐시(1년) 때문에 옛 파일이 보인다 — 경로에 버전을 붙인다
TAG=${1:?usage: upload-tiles.sh <tag e.g. 2026q2-quarters>}
vercel blob put public/tiles/changes.pmtiles \
  --pathname "tiles/changes-${TAG}.pmtiles" --access public \
  --content-type application/octet-stream --cache-control-max-age 31536000 \
  --rw-token "$BLOB_READ_WRITE_TOKEN"

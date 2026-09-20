#!/usr/bin/env python3
"""전국 지도용 동네 단위 집계(data/dots.json) 생성.

넓게 볼 때 36만 개 점을 다 그릴 수 없어서, 행정동 하나를 원 하나로 뭉친다.
- 신규/소멸 개수는 `data/dong/{시군구코드}.json`(정확한 집계)에서 가져온다.
- 좌표는 `public/data/changes/{시군구코드}.json` 의 표본 점들을 행정동별로 평균 낸 값이다
  (행정동 경계 데이터가 없으므로 점들의 무게중심을 대표 좌표로 쓴다).

build-data.py 를 다시 돌린 뒤에 이어서 실행하면 된다.
"""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DONG_DIR = ROOT / "data" / "dong"
CHANGES_DIR = ROOT / "public" / "data" / "changes"
OUT = ROOT / "data" / "dots.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    sigungu = {s["code"]: s for s in load(ROOT / "data" / "sigungu.json")}
    dots = []
    missing_coords = 0

    for code, region in sorted(sigungu.items()):
        dong_file = DONG_DIR / f"{code}.json"
        change_file = CHANGES_DIR / f"{code}.json"
        if not dong_file.exists() or not change_file.exists():
            continue

        points = defaultdict(list)
        changes = load(change_file)
        for kind in ("opened", "closed"):
            for item in changes[kind]:
                points[item["dong"]].append((item["lon"], item["lat"]))

        for dong in load(dong_file):
            pts = points.get(dong["name"])
            if not pts:
                missing_coords += 1
                continue
            lon = round(sum(p[0] for p in pts) / len(pts), 6)
            lat = round(sum(p[1] for p in pts) / len(pts), 6)
            dots.append(
                {
                    "code": dong["code"],
                    "name": dong["name"],
                    "sigunguCode": code,
                    "sigungu": region["name"],
                    "sido": region["sido"],
                    "lon": lon,
                    "lat": lat,
                    "opened": dong["opened"],
                    "closed": dong["closed"],
                    "stores": dong["stores"],
                }
            )

    OUT.write_text(json.dumps(dots, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    total_opened = sum(d["opened"] for d in dots)
    total_closed = sum(d["closed"] for d in dots)
    print(f"행정동 {len(dots)}개 저장 ({OUT.stat().st_size / 1024:.0f}KB)")
    print(f"좌표를 못 구한 행정동 {missing_coords}개 (표본에 점이 없음)")
    print(f"합계 신규 {total_opened:,} / 소멸 {total_closed:,}")


if __name__ == "__main__":
    main()

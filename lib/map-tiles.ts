/** 신규·소멸 점포 전량 벡터 타일(PMTiles) 공통 설정. 클라이언트 전용. */

import maplibregl from 'maplibre-gl';
import { Protocol } from 'pmtiles';

export const OPENED_COLOR = '#3182F6';
export const CLOSED_COLOR = '#E5484D';
/** 같은 자리·같은 세부업종으로 바뀐 곳 — 개명일 수도, 새 주인(교체)일 수도 있다 */
export const RENAMED_COLOR = '#8B95A1';
/** 소진공엔 올해 처음 등록됐지만 인허가일이 1년 전보다 오래된 곳 — 새로 생긴 게 아니라 등록만 늦음 */
export const STALE_COLOR = '#B7C4D6';
/** 소진공에선 사라졌지만 인허가상 아직 영업 중인 곳 — 소멸로 볼 근거가 없음 */
export const UNVERIFIED_COLOR = '#E3C7A6';

/**
 * 분기(q=1..4)별 색 농도. 옅을수록 오래전, 진할수록 최근.
 * opened q: 1=2025년 7~9월에 생김 … 4=2026년 4~6월에 생김
 * closed q: 1=2025년 여름 직후 사라짐 … 4=2026년 봄 이후 사라짐
 */
export const OPENED_RAMP = ['#A8CCFF', '#6FA8FF', '#3182F6', '#1B4FBF'] as const;
export const CLOSED_RAMP = ['#F9B8BC', '#F28389', '#E5484D', '#A8262B'] as const;
/** 스냅샷 기준일: 2025-06-30, 2025-10-30(9월분이 한 달 늦게 등록됨), 2025-12-31, 2026-03-31, 2026-06-30 */
export const QUARTER_LABELS = {
  opened: ['2025년 7~10월', '2025년 11~12월', '2026년 1~3월', '2026년 4~6월'],
  closed: ['2025년 7~10월', '2025년 11~12월', '2026년 1~3월', '2026년 4~6월'],
} as const;

/** q 가 없는(구버전) 타일이면 기본색 */
function rampExpression(ramp: readonly string[], fallback: string): maplibregl.ExpressionSpecification {
  return ['match', ['coalesce', ['get', 'q'], 0], 1, ramp[0], 2, ramp[1], 3, ramp[2], 4, ramp[3], fallback];
}
export const BASE_STYLE = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

/** 타일은 Vercel Blob 에 있다(80MB 라 저장소에 안 둔다). 없으면 로컬 public/tiles 로 폴백 */
export const TILES_URL = `pmtiles://${process.env.NEXT_PUBLIC_TILES_URL ?? '/tiles/changes.pmtiles'}`;
export const TILES_SOURCE = 'changes';
export const TILES_LAYER = 'changes';
/** 타일에 점이 들어 있는 최소 줌 (scripts/build-tiles.py 의 -Z 와 맞춘다) */
export const TILES_MIN_ZOOM = 6;

export type Kind = 'opened' | 'closed' | 'renamed' | 'stale' | 'unverified';
/** 그리는 순서(뒤가 위에 그려짐). 토글 표시는 TOGGLE_ORDER */
export const KINDS: readonly Kind[] = ['unverified', 'stale', 'closed', 'renamed', 'opened'];
export const TOGGLE_ORDER: readonly Kind[] = ['opened', 'closed', 'renamed', 'stale', 'unverified'];
/** 타일 속성 k: 0 소멸, 1 신규, 2 같은 업종 교체, 3 예전부터 영업(등록 지연), 4 소멸 미확인(인허가상 영업 중) */
const KIND_CODE: Record<Kind, number> = { closed: 0, opened: 1, renamed: 2, stale: 3, unverified: 4 };
export const KIND_COLOR: Record<Kind, string> = {
  opened: OPENED_COLOR,
  closed: CLOSED_COLOR,
  renamed: RENAMED_COLOR,
  stale: STALE_COLOR,
  unverified: UNVERIFIED_COLOR,
};
export const KIND_LABEL: Record<Kind, string> = {
  opened: '새로 생긴 곳',
  closed: '사라진 곳',
  renamed: '같은 업종 교체',
  stale: '예전부터 영업',
  unverified: '소멸 미확인',
};

/** 타일 피처 속성: k=1 신규/0 소멸, n 상호, u 업종, d 행정동, r 주소, s 시군구코드 */
export interface TileProps {
  k: number;
  n: string;
  u: string;
  d: string;
  r: string;
  s: string;
  /** 분기 1~4 (없으면 구버전 타일) */
  q?: number;
  /** k=2(간판 바뀜 추정)일 때 이전 상호 */
  p?: string;
  /** 인허가일 YYYYMMDD (식품접객업만, 인허가 데이터와 이어진 경우) */
  a?: string;
  /** 폐업일 YYYYMMDD (인허가 데이터상 폐업한 경우) */
  c?: string;
}

let registered = false;

/** pmtiles:// 프로토콜을 한 번만 등록한다 */
export function ensurePmtilesProtocol(): void {
  if (registered) return;
  maplibregl.addProtocol('pmtiles', new Protocol().tile);
  registered = true;
}

/** 신규/소멸 점 레이어 두 개를 추가한다. `extraFilter` 로 시군구 등을 좁힐 수 있다. */
export function addChangeLayers(
  map: maplibregl.Map,
  opts: { minzoom?: number; extraFilter?: maplibregl.ExpressionSpecification } = {},
): void {
  if (!map.getSource(TILES_SOURCE)) {
    map.addSource(TILES_SOURCE, { type: 'vector', url: TILES_URL });
  }
  for (const kind of KINDS) {
    const kindFilter: maplibregl.ExpressionSpecification = ['==', ['get', 'k'], KIND_CODE[kind]];
    const filter: maplibregl.ExpressionSpecification = opts.extraFilter ? ['all', kindFilter, opts.extraFilter] : kindFilter;
    map.addLayer({
      id: kind,
      type: 'circle',
      source: TILES_SOURCE,
      'source-layer': TILES_LAYER,
      minzoom: opts.minzoom ?? TILES_MIN_ZOOM,
      filter,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 1.5, 11, 2.5, 14, 5, 17, 8],
        'circle-color':
          kind === 'opened'
            ? rampExpression(OPENED_RAMP, OPENED_COLOR)
            : kind === 'closed'
              ? rampExpression(CLOSED_RAMP, CLOSED_COLOR)
              : kind === 'renamed'
                ? RENAMED_COLOR
                : kind === 'stale'
                  ? STALE_COLOR
                  : UNVERIFIED_COLOR,
        'circle-opacity': ['interpolate', ['linear'], ['zoom'], 8, 0.55, 12, 0.85],
        'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 10, 0, 13, 1],
        'circle-stroke-color': '#ffffff',
      },
    });
    map.on('click', kind, (e) => {
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties as TileProps;
      const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates;
      new maplibregl.Popup({ offset: 10 }).setLngLat([lon, lat]).setHTML(popupHtml(p)).addTo(map);
    });
    map.on('mouseenter', kind, () => (map.getCanvas().style.cursor = 'pointer'));
    map.on('mouseleave', kind, () => (map.getCanvas().style.cursor = ''));
  }
}

export function setKindVisible(map: maplibregl.Map, show: Record<Kind, boolean>): void {
  for (const kind of KINDS) {
    if (map.getLayer(kind)) map.setLayoutProperty(kind, 'visibility', show[kind] ? 'visible' : 'none');
  }
}

function ymd(v?: string): string {
  return v && v.length === 8 ? `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6, 8)}` : '';
}

function popupHtml(p: TileProps): string {
  const license = p.a ? `<div style="color:#8B95A1">인허가 ${ymd(p.a)}${p.c ? ` · 폐업 ${ymd(p.c)}` : ''}</div>` : '';
  if (p.k === 3) {
    return (
      `<div style="font:13px/1.5 Pretendard,system-ui;color:#191F28"><b>${escapeHtml(p.n)}</b>` +
      `<div style="color:#5B6B85">예전부터 영업 · 상가정보에는 올해 처음 등록됨 · ${escapeHtml(p.u)}</div>` +
      license + `<div style="color:#8B95A1">${escapeHtml(p.d)} · ${escapeHtml(p.r)}</div></div>`
    );
  }
  if (p.k === 4) {
    return (
      `<div style="font:13px/1.5 Pretendard,system-ui;color:#191F28"><b>${escapeHtml(p.n)}</b>` +
      `<div style="color:#9A6B2F">소멸 미확인 · 상가정보에선 빠졌지만 인허가상 영업 중 · ${escapeHtml(p.u)}</div>` +
      license + `<div style="color:#8B95A1">${escapeHtml(p.d)} · ${escapeHtml(p.r)}</div></div>`
    );
  }
  if (p.k === 2) {
    return (
      `<div style="font:13px/1.5 Pretendard,system-ui;color:#191F28"><b>${escapeHtml(p.n)}</b>` +
      `<div style="color:${RENAMED_COLOR}">같은 업종 교체 · 전에는 "${escapeHtml(p.p ?? '')}" · ${escapeHtml(p.u)}</div>` +
      `<div style="color:#8B95A1">${escapeHtml(p.d)} · ${escapeHtml(p.r)}</div></div>`
    );
  }
  const opened = p.k === 1;
  const q = Number(p.q);
  const when = q >= 1 && q <= 4 ? (opened ? `${QUARTER_LABELS.opened[q - 1]}에 생김` : `${QUARTER_LABELS.closed[q - 1]} 사이 사라짐`) : opened ? '새로 생긴 곳' : '사라진 곳';
  return (
    `<div style="font:13px/1.5 Pretendard,system-ui;color:#191F28"><b>${escapeHtml(p.n)}</b>` +
    `<div style="color:${opened ? OPENED_COLOR : CLOSED_COLOR}">${when} · ${escapeHtml(p.u)}</div>` + license +
    `<div style="color:#8B95A1">${escapeHtml(p.d)} · ${escapeHtml(p.r)}</div></div>`
  );
}

export function escapeHtml(s: string): string {
  return String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

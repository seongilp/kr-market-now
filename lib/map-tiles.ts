/** 신규·소멸 점포 전량 벡터 타일(PMTiles) 공통 설정. 클라이언트 전용. */

import maplibregl from 'maplibre-gl';
import { Protocol } from 'pmtiles';

export const OPENED_COLOR = '#3182F6';
export const CLOSED_COLOR = '#E5484D';
export const BASE_STYLE = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

export const TILES_URL = 'pmtiles:///tiles/changes.pmtiles';
export const TILES_SOURCE = 'changes';
export const TILES_LAYER = 'changes';
/** 타일에 점이 들어 있는 최소 줌 (scripts/build-tiles.py 의 -Z 와 맞춘다) */
export const TILES_MIN_ZOOM = 6;

export type Kind = 'opened' | 'closed';

/** 타일 피처 속성: k=1 신규/0 소멸, n 상호, u 업종, d 행정동, r 주소, s 시군구코드 */
export interface TileProps {
  k: number;
  n: string;
  u: string;
  d: string;
  r: string;
  s: string;
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
  for (const kind of ['closed', 'opened'] as Kind[]) {
    const kindFilter: maplibregl.ExpressionSpecification = ['==', ['get', 'k'], kind === 'opened' ? 1 : 0];
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
        'circle-color': kind === 'opened' ? OPENED_COLOR : CLOSED_COLOR,
        'circle-opacity': ['interpolate', ['linear'], ['zoom'], 8, 0.5, 12, 0.8],
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
  for (const kind of ['opened', 'closed'] as Kind[]) {
    if (map.getLayer(kind)) map.setLayoutProperty(kind, 'visibility', show[kind] ? 'visible' : 'none');
  }
}

function popupHtml(p: TileProps): string {
  const opened = p.k === 1;
  return (
    `<div style="font:13px/1.5 Pretendard,system-ui;color:#191F28"><b>${escapeHtml(p.n)}</b>` +
    `<div style="color:${opened ? OPENED_COLOR : CLOSED_COLOR}">${opened ? '새로 생긴 곳' : '사라진 곳'} · ${escapeHtml(p.u)}</div>` +
    `<div style="color:#8B95A1">${escapeHtml(p.d)} · ${escapeHtml(p.r)}</div></div>`
  );
}

export function escapeHtml(s: string): string {
  return String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

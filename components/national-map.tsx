'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource, type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import type { ChangeItem, Dot, SigunguChanges } from '@/lib/data-types';

const OPENED_COLOR = '#3182F6';
const CLOSED_COLOR = '#E5484D';
const BASE_STYLE = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';
/** 이 줌부터 개별 점을 불러온다. 그 아래에서는 행정동 단위로 뭉쳐 보여준다 */
const DETAIL_ZOOM = 11.5;
/** 한 화면에서 한꺼번에 받아올 시군구 수 상한 — 넘으면 더 확대하라고 안내한다 */
const MAX_REGIONS_IN_VIEW = 12;

type Kind = 'opened' | 'closed';

const EMPTY: GeoJSON.FeatureCollection<GeoJSON.Point> = { type: 'FeatureCollection', features: [] };

function pointFeatures(items: ChangeItem[], kind: Kind): GeoJSON.Feature<GeoJSON.Point>[] {
  return items.map((it) => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [it.lon, it.lat] },
    properties: { kind, name: it.name + (it.branch ? ` ${it.branch}` : ''), upjong: it.upjong, road: it.road },
  }));
}

function dotFeatures(dots: Dot[]): GeoJSON.FeatureCollection<GeoJSON.Point> {
  return {
    type: 'FeatureCollection',
    features: dots.map((d) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [d.lon, d.lat] },
      properties: {
        name: d.name,
        sigungu: `${d.sido} ${d.sigungu}`,
        sigunguCode: d.sigunguCode,
        opened: d.opened,
        closed: d.closed,
        total: d.opened + d.closed,
        net: d.opened - d.closed,
      },
    })),
  };
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export function NationalMap({ dots }: { dots: Dot[] }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const cache = useRef(new Map<string, SigunguChanges>());
  const [show, setShow] = useState<Record<Kind, boolean>>({ opened: true, closed: true });
  const [hint, setHint] = useState('지도를 확대하면 가게 하나하나가 점으로 나옵니다.');

  /** 화면에 보이는 시군구의 변화 목록을 받아 개별 점 레이어를 채운다 */
  const loadVisible = useCallback(async (map: MapLibreMap) => {
    if (map.getZoom() < DETAIL_ZOOM) {
      (map.getSource('opened') as GeoJSONSource | undefined)?.setData(EMPTY);
      (map.getSource('closed') as GeoJSONSource | undefined)?.setData(EMPTY);
      setHint('지도를 확대하면 가게 하나하나가 점으로 나옵니다.');
      return;
    }
    // 확대하면 동네 원 레이어는 숨겨지므로 렌더된 피처가 아니라 지도 범위로 시군구를 고른다
    const b = map.getBounds();
    const pad = 0.03; // 약 3km — 동네 원 중심이 화면 밖이어도 그 시군구는 포함
    b.extend([b.getWest() - pad, b.getSouth() - pad]);
    b.extend([b.getEast() + pad, b.getNorth() + pad]);
    const codes = [...new Set(dots.filter((d) => b.contains([d.lon, d.lat])).map((d) => d.sigunguCode))];
    if (codes.length === 0) {
      setHint('이 범위에는 집계된 동네가 없습니다. 조금 축소해 보세요.');
      return;
    }
    if (codes.length > MAX_REGIONS_IN_VIEW) {
      setHint('보이는 지역이 너무 넓습니다. 조금 더 확대해 주세요.');
      return;
    }

    setHint('불러오는 중…');
    await Promise.all(
      codes
        .filter((c) => !cache.current.has(c))
        .map((c) =>
          fetch(`/data/changes/${c}.json`)
            .then((r) => (r.ok ? r.json() : null))
            .then((j: SigunguChanges | null) => j && cache.current.set(c, j))
            .catch(() => null),
        ),
    );

    for (const kind of ['opened', 'closed'] as Kind[]) {
      const features = codes.flatMap((c) => {
        const data = cache.current.get(c);
        return data ? pointFeatures(data[kind], kind) : [];
      });
      (map.getSource(kind) as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features });
    }
    setHint('표본으로 뽑은 점만 표시합니다. 실제 변화는 이보다 많습니다.');
  }, [dots]);

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    // /map?lat=37.47&lng=126.86&z=13 처럼 위치를 바로 열 수 있다(시군구 페이지에서 링크)
    const q = new URLSearchParams(window.location.search);
    const lat = Number(q.get('lat'));
    const lng = Number(q.get('lng'));
    const z = Number(q.get('z'));
    const hasTarget = Number.isFinite(lat) && Number.isFinite(lng) && lat !== 0 && lng !== 0;
    const map = new maplibregl.Map({
      container: container.current,
      style: BASE_STYLE,
      center: hasTarget ? [lng, lat] : [127.6, 36.3],
      zoom: hasTarget ? (z > 0 ? z : 13) : 6.3,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }), 'top-right');

    map.on('load', () => {
      map.addSource('dots', { type: 'geojson', data: dotFeatures(dots) });
      map.addLayer({
        id: 'dots',
        type: 'circle',
        source: 'dots',
        maxzoom: DETAIL_ZOOM,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'total']], 0, 2, 10, 6, 30, 14, 60, 22],
          'circle-color': ['case', ['>=', ['get', 'net'], 0], OPENED_COLOR, CLOSED_COLOR],
          'circle-opacity': 0.55,
          'circle-stroke-width': 1,
          'circle-stroke-color': '#ffffff',
        },
      });

      for (const kind of ['closed', 'opened'] as Kind[]) {
        map.addSource(kind, { type: 'geojson', data: EMPTY });
        map.addLayer({
          id: kind,
          type: 'circle',
          source: kind,
          minzoom: DETAIL_ZOOM,
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 3, 15, 5.5, 17, 8],
            'circle-color': kind === 'opened' ? OPENED_COLOR : CLOSED_COLOR,
            'circle-opacity': 0.8,
            'circle-stroke-width': 1,
            'circle-stroke-color': '#ffffff',
          },
        });
        map.on('click', kind, (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const p = f.properties as { kind: Kind; name: string; upjong: string; road: string };
          const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates;
          new maplibregl.Popup({ offset: 10 })
            .setLngLat([lon, lat])
            .setHTML(
              `<div style="font:13px/1.5 Pretendard,system-ui;color:#191F28"><b>${escapeHtml(p.name)}</b>` +
                `<div style="color:${p.kind === 'opened' ? OPENED_COLOR : CLOSED_COLOR}">${p.kind === 'opened' ? '새로 생긴 곳' : '사라진 곳'} · ${escapeHtml(p.upjong)}</div>` +
                `<div style="color:#8B95A1">${escapeHtml(p.road)}</div></div>`,
            )
            .addTo(map);
        });
      }

      map.on('click', 'dots', (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties as { name: string; sigungu: string; opened: number; closed: number; sigunguCode: string };
        const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates;
        new maplibregl.Popup({ offset: 10 })
          .setLngLat([lon, lat])
          .setHTML(
            `<div style="font:13px/1.5 Pretendard,system-ui;color:#191F28"><b>${escapeHtml(p.name)}</b>` +
              `<div style="color:#8B95A1">${escapeHtml(p.sigungu)}</div>` +
              `<div style="color:${OPENED_COLOR}">신규 ${p.opened.toLocaleString()}곳</div>` +
              `<div style="color:${CLOSED_COLOR}">소멸 ${p.closed.toLocaleString()}곳</div>` +
              `<a href="/r/${p.sigunguCode}" style="color:${OPENED_COLOR}">이 지역 자세히 보기</a></div>`,
          )
          .addTo(map);
      });

      for (const layer of ['dots', 'opened', 'closed']) {
        map.on('mouseenter', layer, () => (map.getCanvas().style.cursor = 'pointer'));
        map.on('mouseleave', layer, () => (map.getCanvas().style.cursor = ''));
      }

      void loadVisible(map);
    });

    map.on('moveend', () => void loadVisible(map));

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [dots, loadVisible]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    for (const kind of ['opened', 'closed'] as Kind[]) {
      if (map.getLayer(kind)) map.setLayoutProperty(kind, 'visibility', show[kind] ? 'visible' : 'none');
    }
    if (map.getLayer('dots')) {
      const filter: maplibregl.FilterSpecification | null =
        show.opened && show.closed
          ? null
          : show.opened
            ? ['>=', ['get', 'net'], 0]
            : show.closed
              ? ['<', ['get', 'net'], 0]
              : ['==', ['get', 'total'], -1];
      map.setFilter('dots', filter);
    }
  }, [show]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Toggle
          on={show.opened}
          color={OPENED_COLOR}
          label="새로 생긴 곳"
          onClick={() => setShow((s) => ({ ...s, opened: !s.opened }))}
        />
        <Toggle
          on={show.closed}
          color={CLOSED_COLOR}
          label="사라진 곳"
          onClick={() => setShow((s) => ({ ...s, closed: !s.closed }))}
        />
        <span className="text-xs text-muted-foreground">{hint}</span>
      </div>
      <div
        ref={container}
        className="h-[70vh] min-h-[420px] w-full overflow-hidden rounded-2xl border border-[#E5E8EB] bg-[#F9FAFB]"
        aria-label="전국 신규·소멸 점포 지도"
      />
    </div>
  );
}

function Toggle({ on, color, label, onClick }: { on: boolean; color: string; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors ${
        on ? 'border-[#E5E8EB] bg-white' : 'border-transparent bg-[#F2F4F6] text-muted-foreground'
      }`}
    >
      <span className="size-2.5 rounded-full" style={{ backgroundColor: on ? color : '#C3C9D0' }} />
      {label}
    </button>
  );
}

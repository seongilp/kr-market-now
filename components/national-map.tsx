'use client';

import { useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import { QuarterLegend } from '@/components/quarter-legend';

import type { Dot } from '@/lib/data-types';
import {
  BASE_STYLE,
  CLOSED_COLOR,
  OPENED_COLOR,
  RENAMED_COLOR,
  addChangeLayers,
  ensurePmtilesProtocol,
  escapeHtml,
  setKindVisible,
  type Kind,
} from '@/lib/map-tiles';

/** 이 줌부터 개별 점(전량 타일)을 보여준다. 그 아래에서는 행정동 단위로 뭉친다 */
const DETAIL_ZOOM = 10.5;

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

export function NationalMap({ dots }: { dots: Dot[] }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [show, setShow] = useState<Record<Kind, boolean>>({ opened: true, closed: true, renamed: true });
  const [detail, setDetail] = useState(false);

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    ensurePmtilesProtocol();

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
      addChangeLayers(map, { minzoom: DETAIL_ZOOM });

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
      map.on('mouseenter', 'dots', () => (map.getCanvas().style.cursor = 'pointer'));
      map.on('mouseleave', 'dots', () => (map.getCanvas().style.cursor = ''));
      setDetail(map.getZoom() >= DETAIL_ZOOM);
    });
    map.on('zoomend', () => setDetail(map.getZoom() >= DETAIL_ZOOM));

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [dots]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    setKindVisible(map, show);
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
        <Toggle on={show.opened} color={OPENED_COLOR} label="새로 생긴 곳" onClick={() => setShow((s) => ({ ...s, opened: !s.opened }))} />
        <Toggle on={show.closed} color={CLOSED_COLOR} label="사라진 곳" onClick={() => setShow((s) => ({ ...s, closed: !s.closed }))} />
        <Toggle on={show.renamed} color={RENAMED_COLOR} label="같은 업종 교체" onClick={() => setShow((s) => ({ ...s, renamed: !s.renamed }))} />
        <span className="text-xs text-muted-foreground">
          {detail ? '가게 하나하나가 점입니다. 점을 누르면 상호가 나옵니다.' : '지도를 확대하면 가게 하나하나가 점으로 나옵니다.'}
        </span>
      </div>
      <div
        ref={container}
        className="h-[70vh] min-h-[420px] w-full overflow-hidden rounded-2xl border border-[#E5E8EB] bg-[#F9FAFB]"
        aria-label="전국 신규·소멸 점포 지도"
      />
      <QuarterLegend />
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

'use client';

import { useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import type { ChangeItem, SigunguChanges } from '@/lib/data-types';

const OPENED_COLOR = '#3182F6';
const CLOSED_COLOR = '#E5484D';
const BASE_STYLE = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

type Kind = 'opened' | 'closed';

function toGeoJson(items: ChangeItem[], kind: Kind): GeoJSON.FeatureCollection<GeoJSON.Point> {
  return {
    type: 'FeatureCollection',
    features: items.map((it) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [it.lon, it.lat] },
      properties: { kind, name: it.name + (it.branch ? ` ${it.branch}` : ''), upjong: it.upjong, road: it.road },
    })),
  };
}

function bounds(items: ChangeItem[]): maplibregl.LngLatBounds | undefined {
  if (items.length === 0) return undefined;
  const b = new maplibregl.LngLatBounds();
  for (const it of items) b.extend([it.lon, it.lat]);
  return b;
}

export function ChangeMap({ code, regionName }: { code: string; regionName: string }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [show, setShow] = useState<Record<Kind, boolean>>({ opened: true, closed: true });
  const [data, setData] = useState<SigunguChanges | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch(`/data/changes/${code}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j: SigunguChanges) => alive && setData(j))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [code]);

  useEffect(() => {
    if (!container.current || !data || mapRef.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: BASE_STYLE,
      bounds: bounds([...data.opened, ...data.closed]),
      fitBoundsOptions: { padding: 40 },
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

    map.on('load', () => {
      for (const kind of ['closed', 'opened'] as Kind[]) {
        map.addSource(kind, { type: 'geojson', data: toGeoJson(data[kind], kind) });
        map.addLayer({
          id: kind,
          type: 'circle',
          source: kind,
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 2.5, 14, 5, 17, 8],
            'circle-color': kind === 'opened' ? OPENED_COLOR : CLOSED_COLOR,
            'circle-opacity': 0.75,
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
              `<div style="font:13px/1.5 Pretendard,system-ui;color:#191F28">
                 <b>${escapeHtml(p.name)}</b>
                 <div style="color:${p.kind === 'opened' ? OPENED_COLOR : CLOSED_COLOR}">${p.kind === 'opened' ? '새로 생긴 곳' : '사라진 곳'} · ${escapeHtml(p.upjong)}</div>
                 <div style="color:#8B95A1">${escapeHtml(p.road)}</div>
               </div>`,
            )
            .addTo(map);
        });
        map.on('mouseenter', kind, () => (map.getCanvas().style.cursor = 'pointer'));
        map.on('mouseleave', kind, () => (map.getCanvas().style.cursor = ''));
      }
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    for (const kind of ['opened', 'closed'] as Kind[]) {
      if (map.getLayer(kind)) map.setLayoutProperty(kind, 'visibility', show[kind] ? 'visible' : 'none');
    }
  }, [show]);

  if (failed) {
    return (
      <p className="rounded-2xl border border-[#E5E8EB] bg-white p-4 text-sm text-muted-foreground">
        지도를 불러오지 못했습니다.
      </p>
    );
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Toggle
          on={show.opened}
          color={OPENED_COLOR}
          label={`새로 생긴 곳 ${data ? data.opened.length.toLocaleString() : '…'}`}
          onClick={() => setShow((s) => ({ ...s, opened: !s.opened }))}
        />
        <Toggle
          on={show.closed}
          color={CLOSED_COLOR}
          label={`사라진 곳 ${data ? data.closed.length.toLocaleString() : '…'}`}
          onClick={() => setShow((s) => ({ ...s, closed: !s.closed }))}
        />
      </div>
      <div
        ref={container}
        className="h-[420px] w-full overflow-hidden rounded-2xl border border-[#E5E8EB] bg-[#F9FAFB] sm:h-[560px]"
        aria-label={`${regionName} 신규·소멸 점포 지도`}
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

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

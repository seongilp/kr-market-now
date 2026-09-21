'use client';

import { useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import { QuarterLegend } from '@/components/quarter-legend';

import { BASE_STYLE, CLOSED_COLOR, OPENED_COLOR, addChangeLayers, ensurePmtilesProtocol, setKindVisible, type Kind } from '@/lib/map-tiles';

export interface MapBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

/** 시군구 하나의 신규·소멸 점포 전량(벡터 타일에서 시군구코드로 걸러서) */
export function ChangeMap({
  code,
  regionName,
  bounds,
  opened,
  closed,
}: {
  code: string;
  regionName: string;
  bounds: MapBounds;
  opened: number;
  closed: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [show, setShow] = useState<Record<Kind, boolean>>({ opened: true, closed: true });

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    ensurePmtilesProtocol();
    const map = new maplibregl.Map({
      container: container.current,
      style: BASE_STYLE,
      bounds: [bounds.west, bounds.south, bounds.east, bounds.north],
      fitBoundsOptions: { padding: 30 },
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('load', () => addChangeLayers(map, { extraFilter: ['==', ['get', 's'], code] }));
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [code, bounds]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.isStyleLoaded()) setKindVisible(map, show);
  }, [show]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Toggle on={show.opened} color={OPENED_COLOR} label={`새로 생긴 곳 ${opened.toLocaleString()}`} onClick={() => setShow((s) => ({ ...s, opened: !s.opened }))} />
        <Toggle on={show.closed} color={CLOSED_COLOR} label={`사라진 곳 ${closed.toLocaleString()}`} onClick={() => setShow((s) => ({ ...s, closed: !s.closed }))} />
      </div>
      <div
        ref={container}
        className="h-[420px] w-full overflow-hidden rounded-2xl border border-[#E5E8EB] bg-[#F9FAFB] sm:h-[560px]"
        aria-label={`${regionName} 신규·소멸 점포 지도`}
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

import { CLOSED_RAMP, OPENED_RAMP, QUARTER_LABELS, RENAMED_COLOR } from '@/lib/map-tiles';

/** 점 색 농도가 뜻하는 시기를 보여주는 범례. 옅을수록 오래전, 진할수록 최근. */
export function QuarterLegend() {
  return (
    <div className="mt-2 grid gap-1.5 text-xs text-muted-foreground sm:grid-cols-2">
      <Row label="생긴 때" ramp={OPENED_RAMP} labels={QUARTER_LABELS.opened} />
      <Row label="사라진 때" ramp={CLOSED_RAMP} labels={QUARTER_LABELS.closed} />
      <div className="flex items-center gap-2">
        <span className="w-14 shrink-0">같은 업종 교체</span>
        <span className="size-3 shrink-0 rounded-full" style={{ backgroundColor: RENAMED_COLOR }} aria-hidden />
        <span>같은 자리에 같은 세부업종으로 다른 상호가 들어옴. 개명일 수도, 새 주인일 수도 있어 신규·소멸에 넣지 않았습니다</span>
      </div>
      <p className="sm:col-span-2">
        옅을수록 오래전, 진할수록 최근. 2026년 4~6월분은 원본이 크게 갱신된 회차라 실제보다 "최근에 생김"이 많이 잡힙니다.
      </p>
    </div>
  );
}

function Row({ label, ramp, labels }: { label: string; ramp: readonly string[]; labels: readonly string[] }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-14 shrink-0">{label}</span>
      <span className="flex overflow-hidden rounded-full" aria-hidden>
        {ramp.map((c) => (
          <span key={c} className="h-3 w-6" style={{ backgroundColor: c }} />
        ))}
      </span>
      <span className="truncate">
        {labels[0]} → {labels[labels.length - 1]}
      </span>
    </div>
  );
}

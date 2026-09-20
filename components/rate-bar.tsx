/** 비율 하나를 전국 기준선과 함께 막대로. 기준선보다 높으면 빨강, 낮으면 파랑. */
export function RateBar({ value, baseline, max = 0.5 }: { value: number; baseline: number; max?: number }) {
  const w = Math.min(100, (value / max) * 100);
  const b = Math.min(100, (baseline / max) * 100);
  const color = value > baseline ? '#E5484D' : '#3182F6';
  return (
    <div className="relative h-2 w-full rounded-full bg-[#F2F4F6]" aria-hidden>
      <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${w}%`, backgroundColor: color }} />
      <div className="absolute -top-0.5 h-3 w-0.5 bg-[#8B95A1]" style={{ left: `${b}%` }} title="전국" />
    </div>
  );
}

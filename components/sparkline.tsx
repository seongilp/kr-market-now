/** 연도별 추이를 작은 선 그래프로. 값이 하나뿐이면 점 하나만 찍는다. */
export function Sparkline({
  values,
  width = 120,
  height = 32,
  color = '#3182F6',
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  if (values.length === 0) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 3;
  const x = (i: number) => (values.length === 1 ? width / 2 : pad + (i * (width - pad * 2)) / (values.length - 1));
  const y = (v: number) => height - pad - ((v - min) / span) * (height - pad * 2);
  const d = values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const last = values[values.length - 1];

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="shrink-0">
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(values.length - 1)} cy={y(last)} r={2.5} fill={color} />
    </svg>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone = 'default',
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'default' | 'up' | 'down';
}) {
  const toneClass = tone === 'up' ? 'text-primary' : tone === 'down' ? 'text-[#E5484D]' : '';
  return (
    <div className="rounded-2xl border border-[#E5E8EB] bg-white p-4">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${toneClass}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

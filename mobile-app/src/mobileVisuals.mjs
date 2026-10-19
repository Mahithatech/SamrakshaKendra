/** Safe, display-ready chart data for the React Native dashboard. */
export function prepareWeeklyChartPoints(points, maxPoints = 8) {
  if (!Array.isArray(points)) return [];
  const limit = Number.isInteger(maxPoints) && maxPoints > 0 ? maxPoints : 8;
  return points
    .filter((point) => point && typeof point === 'object')
    .map((point) => {
      const raw = point.cases ?? point.total_cases ?? point.value ?? 0;
      const cases = Number(raw);
      return {
        period: String(point.period ?? point.label ?? point.week ?? 'Period'),
        cases: Number.isFinite(cases) && cases >= 0 ? cases : 0,
      };
    })
    .slice(-limit);
}

export function compactPeriodLabel(period) {
  const value = String(period ?? '').trim();
  const match = value.match(/^(\d{4})[-\s]?W(\d{1,2})$/i);
  if (match) return `${match[1].slice(2)}-W${String(Number(match[2])).padStart(2, '0')}`;
  return value.length > 9 ? `${value.slice(0, 8)}…` : value || '—';
}

export function prepareRankingBars(items, maxItems = 6) {
  if (!Array.isArray(items)) return [];
  const limit = Number.isInteger(maxItems) && maxItems > 0 ? maxItems : 6;
  const normalized = items
    .filter((item) => item && typeof item === 'object')
    .map((item) => {
      const name = String(item.name ?? item.state ?? item.disease ?? item.label ?? '').trim();
      const raw = item.cases ?? item.total_cases ?? item.value ?? item.count ?? 0;
      const value = Number(raw);
      return name ? { name, value: Number.isFinite(value) && value >= 0 ? value : 0 } : null;
    })
    .filter(Boolean)
    .sort((a, b) => b.value - a.value)
    .slice(0, limit);
  const max = Math.max(1, ...normalized.map((item) => item.value));
  return normalized.map((item) => ({
    ...item,
    percent: item.value > 0 ? Math.min(100, Math.max(2, (item.value / max) * 100)) : 0,
  }));
}

export function safePageLabel(page, pages) {
  const p = Number(page);
  const n = Number(pages);
  const safePages = Number.isFinite(n) && n >= 1 ? Math.floor(n) : 1;
  const safePage = Number.isFinite(p) && p >= 1 ? Math.min(Math.floor(p), safePages) : 1;
  return `${safePage}/${safePages}`;
}

export function displayStatValue(value, formatNumber = (n) => Number(n).toLocaleString('en-IN')) {
  if (typeof value === 'number') return formatNumber(value);
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
}


export function prepareIcaSignalData(signals, maxPeriods = 6) {
  if (!Array.isArray(signals)) return { components: [], periods: [], maxAbs: 1 };
  const limit = Number.isInteger(maxPeriods) && maxPeriods > 0 ? maxPeriods : 6;
  const valid = signals.filter((row) => row && typeof row === 'object');
  const components = [...new Set(valid.flatMap((row) => Object.keys(row).filter((key) => /^IC\d+$/i.test(key))))].sort((a, b) => Number(a.slice(2)) - Number(b.slice(2)));
  const periods = valid.slice(-limit).map((row, index) => ({
    period: String(row.period ?? row.label ?? `Period ${index + 1}`),
    values: components.map((component) => {
      const value = Number(row[component] ?? 0);
      return { component, value: Number.isFinite(value) ? value : 0 };
    }),
  }));
  const maxAbs = Math.max(1, ...periods.flatMap((period) => period.values.map((item) => Math.abs(item.value))));
  return { components, periods, maxAbs };
}

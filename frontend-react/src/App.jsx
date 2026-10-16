import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ComposableMap, Geographies, Geography, Marker } from 'react-simple-maps';

const API_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000').replace(/\/$/, '');
const navItems = [
  { id: 'overview', label: 'Overview', glyph: '◫' },
  { id: 'history', label: 'Historical data', glyph: '▤' },
  { id: 'signals', label: 'Global signals', glyph: '↗' },
  { id: 'india-reports', label: 'India reports', glyph: '⌂' },
  { id: 'report-review', label: 'Report review queue', glyph: '✓' },
  { id: 'staged-data', label: 'Staged NCDC data', glyph: '▦' },
  { id: 'anomalies', label: 'Anomaly detection', glyph: '⌁' },
  { id: 'ica', label: 'ICA lab', glyph: '◉' },
  { id: 'map', label: 'Map & hotspots', glyph: '◎' },
  { id: 'report-queue', label: 'Report review queue', glyph: '⇣' },
];

async function api(path, options = {}) {
  const { headers: customHeaders = {}, ...fetchOptions } = options;
  const token = sessionStorage.getItem('sk_access_token');
  const headers = {
    'Content-Type': 'application/json',
    ...(token && path !== '/auth/login' ? { Authorization: `Bearer ${token}` } : {}),
    ...customHeaders,
  };
  const response = await fetch(`${API_BASE}${path}`, { ...fetchOptions, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') {
      sessionStorage.removeItem('sk_access_token');
      window.dispatchEvent(new Event('sk-auth-expired'));
    }
    const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return body;
}

function formatNumber(value) {
  return new Intl.NumberFormat('en-IN').format(Number(value || 0));
}

function formatDateTime(value) {
  if (!value) return 'Unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Date unavailable';
  return date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

function Badge({ children, tone = 'neutral' }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

function MetricCard({ label, value, footnote, accent, glyph }) {
  return (
    <article className={`metric-card accent-${accent}`}>
      <div className="metric-top"><span>{label}</span><span className="metric-glyph">{glyph}</span></div>
      <div className="metric-value">{value === null || value === undefined ? '—' : formatNumber(value)}</div>
      <div className="metric-footnote">{footnote}</div>
    </article>
  );
}

function EmptyState({ title, body }) {
  return <div className="empty-state"><div className="empty-symbol">◇</div><strong>{title}</strong><p>{body}</p></div>;
}

function TrendChart({ points = [] }) {
  if (!points.length) return <EmptyState title="No trend data yet" body="The selected database does not contain enough reporting periods to plot a trend." />;
  const width = 720; const height = 220; const pad = { left: 38, right: 18, top: 16, bottom: 38 };
  const values = points.map((p) => Number(p.cases || 0));
  const max = Math.max(...values, 1);
  const usableW = width - pad.left - pad.right; const usableH = height - pad.top - pad.bottom;
  const coords = values.map((v, i) => ({
    x: pad.left + (points.length === 1 ? usableW / 2 : (i / (points.length - 1)) * usableW),
    y: pad.top + usableH - (v / max) * usableH,
  }));
  const line = coords.map((p) => `${p.x},${p.y}`).join(' ');
  const area = `${pad.left},${pad.top + usableH} ${line} ${pad.left + usableW},${pad.top + usableH}`;
  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Weekly reported cases trend" className="trend-svg">
        {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
          const y = pad.top + usableH - fraction * usableH;
          return <g key={fraction}><line x1={pad.left} x2={width - pad.right} y1={y} y2={y} className="grid-line"/><text x={pad.left - 8} y={y + 4} textAnchor="end" className="axis-label">{Math.round(max * fraction)}</text></g>;
        })}
        <polygon points={area} className="trend-area" />
        <polyline points={line} className="trend-line" />
        {coords.map((p, i) => <circle key={points[i].period} cx={p.x} cy={p.y} r="3.8" className="trend-dot"><title>{points[i].period}: {formatNumber(values[i])} cases</title></circle>)}
        {points.map((p, i) => (i === 0 || i === points.length - 1 || i === Math.floor(points.length / 2)) ? <text key={p.period} x={coords[i].x} y={height - 12} textAnchor="middle" className="axis-label">{p.period}</text> : null)}
      </svg>
      <div className="chart-foot"><span><i className="legend-dot" /> Reported cases</span><span>Latest {points.length} year-week buckets</span></div>
    </div>
  );
}

function HorizontalBars({ items = [], valueKey = 'cases' }) {
  if (!items.length) return <EmptyState title="No comparison data" body="No state or disease aggregates are available for these filters." />;
  const max = Math.max(...items.map((item) => Number(item[valueKey] || 0)), 1);
  return <div className="bars">{items.slice(0, 7).map((item) => <div className="bar-row" key={item.name}>
    <div className="bar-label" title={item.name}>{item.name}</div>
    <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.max(1, Number(item[valueKey] || 0) / max * 100)}%` }} /></div>
    <div className="bar-value">{formatNumber(item[valueKey])}</div>
  </div>)}</div>;
}

function IcaPlot({ signals = [] }) {
  if (!signals.length) return null;
  const components = Object.keys(signals[0]).filter((key) => key.startsWith('IC'));
  const width = 720; const height = 250; const left = 34; const right = 16; const top = 18; const bottom = 42;
  const raw = signals.flatMap((s) => components.map((c) => Number(s[c] || 0)));
  const maxAbs = Math.max(...raw.map(Math.abs), 1);
  const innerW = width - left - right; const innerH = height - top - bottom;
  return <div className="chart-wrap"><svg viewBox={`0 0 ${width} ${height}`} className="trend-svg" role="img" aria-label="ICA component signals over weekly periods">
    <line x1={left} x2={width-right} y1={top + innerH/2} y2={top + innerH/2} className="grid-line" />
    {components.map((component, ci) => {
      const pts = signals.map((s, i) => {
        const x = left + (signals.length === 1 ? innerW / 2 : i / (signals.length - 1) * innerW);
        const y = top + innerH / 2 - (Number(s[component] || 0) / maxAbs) * (innerH / 2 - 4);
        return `${x},${y}`;
      }).join(' ');
      return <g key={component}><polyline points={pts} className={`ica-line ica-line-${ci % 4}`} /><text x={width-right-4} y={top+16+ci*18} textAnchor="end" className={`ica-label ica-label-${ci % 4}`}>{component}</text></g>;
    })}
    {signals.filter((_, i) => i === 0 || i === signals.length-1 || i === Math.floor(signals.length/2)).map((s) => <text key={s.period} x={left + signals.indexOf(s)/(Math.max(1, signals.length-1))*innerW} y={height-13} textAnchor="middle" className="axis-label">{s.period}</text>)}
  </svg><div className="chart-foot"><span>Standardized ICA signals</span><span>Exploratory; not an outbreak prediction</span></div></div>;
}


function mapNameKey(value) {
  return String(value || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/&/g, 'and').replace(/[^a-z0-9]/g, '');
}

const MAP_STATE_ALIASES = {
  orissa: 'odisha',
  uttaranchal: 'uttarakhand',
  pondicherry: 'puducherry',
  nctofdelhi: 'delhi',
  delhinationalcapitalterritory: 'delhi',
  andamannicobarislands: 'andamanandnicobarislands',
  andamanandnicobar: 'andamanandnicobarislands',
  dadraandnagarhavelianddamandiu: 'dadraandnagarhavelianddamandiu',
  jammuandkashmir: 'jammuandkashmir',
};

function canonicalMapName(value) {
  const key = mapNameKey(value);
  return MAP_STATE_ALIASES[key] || key;
}

function featureStateName(feature) {
  const properties = feature?.properties || {};
  const preferred = Object.keys(properties).find((key) =>
    /^(st_nm|stname|state|state_name|name|name_1|adm1_en)$/i.test(key)
  );
  if (preferred && properties[preferred] != null) return String(properties[preferred]);
  const fallback = Object.entries(properties).find(([, value]) => typeof value === 'string' && value.trim());
  return fallback ? fallback[1] : String(feature?.id || 'Unknown state');
}


// Approximate state/UT centroids, used only to place state-level markers on the map.
// These are not district or individual case coordinates.
const MAP_STATE_COORDINATES = {
  andhrapradesh: [80.1, 15.9], arunachalpradesh: [94.5, 28.2], assam: [92.8, 26.2],
  bihar: [85.6, 25.9], chhattisgarh: [81.8, 21.3], goa: [74.0, 15.4], gujarat: [71.5, 22.5],
  haryana: [76.1, 29.0], himachalpradesh: [77.2, 31.9], jharkhand: [85.3, 23.6],
  karnataka: [76.3, 15.3], kerala: [76.3, 10.5], madhyapradesh: [78.5, 23.5],
  maharashtra: [75.7, 19.5], manipur: [93.9, 24.7], meghalaya: [91.3, 25.5],
  mizoram: [92.8, 23.2], nagaland: [94.1, 26.1], odisha: [85.6, 20.9], punjab: [75.4, 31.0],
  rajasthan: [73.8, 26.5], sikkim: [88.5, 27.5], tamilnadu: [78.6, 11.0], telangana: [79.0, 18.1],
  tripura: [91.7, 23.8], uttarpradesh: [80.9, 26.8], uttarakhand: [79.0, 30.0], westbengal: [87.8, 22.8],
  delhi: [77.2, 28.6], jammuandkashmir: [75.3, 33.7], ladakh: [77.8, 34.2],
  andamanandnicobarislands: [92.7, 11.7], chandigarh: [76.8, 30.7],
  dadraandnagarhavelianddamandiu: [72.9, 20.3], lakshadweep: [72.6, 10.5], puducherry: [79.8, 11.9],
};

function IndiaMapHotspots() {
  const [mapData, setMapData] = useState(null);
  const [anomalies, setAnomalies] = useState([]);
  const [selectedState, setSelectedState] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError('');
    try {
      const first = await api('/public/surveillance?page=1&page_size=100');
      const pageCount = Math.max(1, Number(first.pages || 1));
      const rest = await Promise.all(Array.from({ length: pageCount - 1 }, (_, index) =>
        api(`/public/surveillance?page=${index + 2}&page_size=100`)
      ));
      const allRecords = [ ...(first.items || []), ...rest.flatMap((result) => result.items || []) ];
      const periods = allRecords.map((row) => ({
        year: Number(row.year), week: Number(row.week), end: String(row.reporting_end_date || ''),
      })).filter((row) => Number.isFinite(row.year) && Number.isFinite(row.week));
      if (!allRecords.length || !periods.length) {
        setMapData({ period: 'No reporting period available', rows: [], sourceRows: 0 });
      } else {
        periods.sort((a, b) => (b.year - a.year) || (b.week - a.week) || b.end.localeCompare(a.end));
        const latest = periods[0];
        const latestKey = `${latest.year}-${latest.week}`;
        const latestRows = allRecords.filter((row) => `${Number(row.year)}-${Number(row.week)}` === latestKey);
        const grouped = new Map();
        for (const row of latestRows) {
          const name = String(row.state || 'Unknown state').trim();
          const key = canonicalMapName(name);
          if (!grouped.has(key)) grouped.set(key, {
            state: name, casesSum: 0, casesKnown: 0, deathsSum: 0, deathsKnown: 0,
            records: 0, districts: new Set(), diseases: new Set(), periodEnd: '', sources: new Set(),
          });
          const item = grouped.get(key);
          item.records += 1;
          if (row.district) item.districts.add(String(row.district));
          if (row.disease) item.diseases.add(String(row.disease));
          if (row.reporting_end_date && String(row.reporting_end_date) > item.periodEnd) item.periodEnd = String(row.reporting_end_date);
          if (row.source_url) item.sources.add(String(row.source_url));
          if (row.cases !== null && row.cases !== undefined && row.cases !== '' && Number.isFinite(Number(row.cases))) {
            item.casesSum += Number(row.cases); item.casesKnown += 1;
          }
          if (row.deaths !== null && row.deaths !== undefined && row.deaths !== '' && Number.isFinite(Number(row.deaths))) {
            item.deathsSum += Number(row.deaths); item.deathsKnown += 1;
          }
        }
        const rows = Array.from(grouped.values()).map((item) => ({
          state: item.state,
          cases: item.casesKnown ? item.casesSum : null,
          cases_known_records: item.casesKnown,
          deaths: item.deathsKnown ? item.deathsSum : null,
          deaths_known_records: item.deathsKnown,
          records: item.records,
          districts: item.districts.size,
          diseases: item.diseases.size,
          period_end: item.periodEnd || latest.end || null,
          sources: Array.from(item.sources),
        })).sort((a, b) => (b.cases ?? -1) - (a.cases ?? -1));
        setMapData({
          period: `Year ${latest.year}, week ${String(latest.week).padStart(2, '0')}`,
          periodKey: latestKey,
          periodEnd: latest.end || rows.map((row) => row.period_end).filter(Boolean).sort().at(-1) || null,
          rows,
          sourceRows: latestRows.length,
          totalStates: rows.length,
          note: first.data_note || 'Aggregate records only; source coverage may vary.',
        });
      }
      try {
        const result = await api('/analytics/anomalies');
        setAnomalies((result.items || []).filter((item) => !item.is_synthetic && item.type !== 'demo_anomaly'));
      } catch {
        setAnomalies([]);
      }
    } catch (err) {
      setError(err.message || 'Could not load surveillance data for the map.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const stateByKey = useMemo(() => {
    const lookup = new Map();
    for (const row of mapData?.rows || []) lookup.set(canonicalMapName(row.state), row);
    return lookup;
  }, [mapData]);

  const hotspotKeys = useMemo(() => new Set(anomalies.map((item) => canonicalMapName(item.state)).filter(Boolean)), [anomalies]);
  const maxCases = useMemo(() => Math.max(1, ...(mapData?.rows || []).map((row) => Number(row.cases ?? 0))), [mapData]);
  const mapMarkers = useMemo(() => {
    const candidateNames = new Map();
    for (const row of mapData?.rows || []) {
      const key = canonicalMapName(row.state);
      if (key && (Number(row.cases) > 0 || hotspotKeys.has(key))) candidateNames.set(key, row.state);
    }
    for (const item of anomalies) {
      const key = canonicalMapName(item.state);
      if (key && item.state) candidateNames.set(key, item.state);
    }
    return Array.from(candidateNames.entries()).flatMap(([key, state]) => {
      const coordinates = MAP_STATE_COORDINATES[key];
      if (!coordinates) return [];
      const row = stateByKey.get(key);
      const flagged = hotspotKeys.has(key);
      const cases = row && row.cases !== null && row.cases !== undefined && Number.isFinite(Number(row.cases))
        ? Number(row.cases) : null;
      const ratio = cases === null ? 0 : Math.max(0, cases / maxCases);
      return [{
        key, state, coordinates, flagged, cases,
        radius: Math.max(3, Math.min(7.5, 3 + Math.sqrt(ratio) * 4.5 + (flagged ? 1 : 0))),
      }];
    });
  }, [mapData, anomalies, hotspotKeys, stateByKey, maxCases]);

  const selected = selectedState ? stateByKey.get(canonicalMapName(selectedState)) : null;

  const fillForState = (row) => row ? '#f4f6f8' : '#d7dde4';

  const topHotspots = useMemo(() => {
    const seen = new Set();
    return anomalies.filter((item) => {
      const key = `${canonicalMapName(item.state)}|${String(item.disease || '').toLowerCase()}|${item.year}|${item.week}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, 10);
  }, [anomalies]);

  return (
    <div className="map-hotspots-page">
      <section className="hero-compact map-hero">
        <div><Badge tone="blue">GEOGRAPHIC SURVEILLANCE</Badge><h2>India map & potential hotspots</h2>
          <p>State-level view of the latest reporting week found in this installation. Outlined states have historical statistical anomaly candidates; they are not confirmed outbreaks.</p>
        </div><div className="map-hero-mark">⌖</div>
      </section>
      {error && <div className="alert-banner error-banner"><strong>Map data issue</strong><span>{error}</span></div>}
      <section className="panel">
        <div className="panel-heading map-panel-heading"><div><span className="eyebrow">LATEST AVAILABLE PERIOD</span><h3>{mapData?.period || (loading ? 'Loading reporting period…' : 'No period available')}</h3>
          <p className="muted small">{mapData?.sourceRows ?? 0} source rows · {mapData?.totalStates ?? 0} states/UT labels with records{mapData?.periodEnd ? ` · latest end date ${mapData.periodEnd}` : ''}</p>
        </div><button className="button button-outline" disabled={refreshing} onClick={refresh}>{refreshing ? 'Refreshing…' : 'Refresh map data'}</button></div>
        <p className="map-disclaimer">Glowing markers are approximate state-centroid locations, not exact case locations. Marker size reflects known case totals for the latest available reporting week; bright red markers also indicate historical statistical anomaly candidates. These are screening aids, not confirmed outbreaks. Missing values remain unknown.</p>
        {loading && !mapData ? <div className="loading-line"><span className="spinner" /> Loading geographic data…</div> : (
          <div className="map-layout">
            <div className="india-map-wrap">
              <ComposableMap projection="geoMercator" projectionConfig={{ scale: 850, center: [82, 22] }} width={620} height={620} role="img" aria-label="India state surveillance map">
                <Geographies geography="/india-states-simplified.geojson">
                  {({ geographies }) => geographies.map((geo) => {
                    const name = featureStateName(geo);
                    const row = stateByKey.get(canonicalMapName(name));
                    const flagged = hotspotKeys.has(canonicalMapName(name));
                    return <Geography key={geo.rsmKey || geo.id || name} geography={geo} onClick={() => setSelectedState(name)}
                      style={{ default: { fill: fillForState(row), stroke: flagged ? '#c24155' : '#9aabba', strokeWidth: flagged ? 1.5 : 0.55, outline: 'none', cursor: 'pointer' }, hover: { fill: '#f0b44d', stroke: '#243746', strokeWidth: 1.1, outline: 'none', cursor: 'pointer' }, pressed: { fill: '#e3a13c', outline: 'none' } }} />;
                  })}
                </Geographies>
                {mapMarkers.map((marker) => (
                  <Marker key={marker.key} coordinates={marker.coordinates}>
                    <g
                      className={`outbreak-marker ${marker.flagged ? 'is-flagged' : 'is-reported'}`}
                      onClick={() => setSelectedState(marker.state)}
                      role="button"
                      aria-label={`Select ${marker.state}; ${marker.flagged ? 'historical anomaly candidate' : 'reported aggregate activity'}`}
                    >
                      <circle className="hotspot-glow" r={marker.radius * 3.1} />
                      <circle className="hotspot-pulse" r={marker.radius * 2.0} />
                      <g className="hotspot-rays">
                        {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => (
                          <line key={angle} transform={`rotate(${angle})`} x1="0" y1={-(marker.radius + 1)} x2="0" y2={-(marker.radius + 4)} />
                        ))}
                      </g>
                      <circle className="hotspot-core" r={marker.radius} />
                      <circle className="hotspot-center" r={Math.max(1.2, marker.radius * 0.32)} />
                      <title>{`${marker.state}: ${marker.flagged ? 'historical anomaly candidate' : 'reported aggregate activity'}${marker.cases === null ? '' : ` · ${formatNumber(marker.cases)} known reported cases in selected week`}`}</title>
                    </g>
                  </Marker>
                ))}
              </ComposableMap>
              <div className="map-legend"><span><i className="map-dot reported" />Reported aggregate activity</span><span><i className="map-dot flagged" />Historical anomaly candidate</span></div>
              <p className="map-attribution">State boundary data: AbhinavSwami28/india-official-geojson, MIT license. Verify boundary depiction with Survey of India for formal publication.</p>
            </div>
            <aside className="map-side-panel">
              <div className="map-selected-card"><span className="eyebrow">SELECTED STATE / UT</span><h3>{selectedState || 'Choose a state on the map'}</h3>
                {selected ? <>
                  <div className="map-state-metrics"><div><small>Known cases sum</small><strong>{selected.cases == null ? 'Unavailable' : formatNumber(selected.cases)}</strong></div><div><small>Known deaths sum</small><strong>{selected.deaths == null ? 'Unavailable' : formatNumber(selected.deaths)}</strong></div></div>
                  <div className="map-detail-line"><span>Rows in period</span><strong>{formatNumber(selected.records)}</strong></div>
                  <div className="map-detail-line"><span>District labels</span><strong>{formatNumber(selected.districts)}</strong></div>
                  <div className="map-detail-line"><span>Disease labels</span><strong>{formatNumber(selected.diseases)}</strong></div>
                  <div className="map-detail-line"><span>Period end date</span><strong>{selected.period_end || 'Unavailable'}</strong></div>
                  <small className="muted">Cases known for {selected.cases_known_records} of {selected.records} rows; deaths known for {selected.deaths_known_records} of {selected.records} rows.</small>
                </> : <p className="muted small">Select a shaded state to inspect aggregate records for the latest available reporting week.</p>}
              </div>
              <div className="map-hotspot-list"><div className="map-list-title"><div><span className="eyebrow">STATISTICAL SCREENING</span><h3>Potential hotspots</h3></div><Badge tone={topHotspots.length ? 'warning' : 'neutral'}>{topHotspots.length}</Badge></div>
                <p className="muted small">Candidates from historical time-series anomaly screening. These may be from an earlier week than the map and require human review.</p>
                {topHotspots.length ? topHotspots.map((item, index) => <button className="map-hotspot-row" key={`${item.state}-${item.disease}-${item.year}-${item.week}-${index}`} onClick={() => setSelectedState(item.state || '')}>
                  <span className="map-hotspot-number">{index + 1}</span><span className="map-hotspot-text"><strong>{item.state || 'Unknown state'}</strong><small>{item.district ? `${item.district} · ` : ''}{item.disease || 'Disease not labelled'} · {item.year || 'Year ?'} W{item.week ?? '?'}</small></span><span className="map-hotspot-cases">{item.cases == null ? '—' : formatNumber(item.cases)}</span>
                </button>) : <EmptyState title="No candidates returned" body="No eligible historical anomaly candidate is available from the current API result. This does not prove there is no outbreak." />}
              </div>
            </aside>
          </div>
        )}
      </section>
    </div>
  );
}


function NCDCReportReviewQueue() {
  const [queue, setQueue] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('pending_review');
  const [savingId, setSavingId] = useState('');
  const [notesById, setNotesById] = useState({});

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setRefreshing(true);
    setError('');
    try {
      const params = new URLSearchParams({ limit: '300' });
      if (filter !== 'all') params.set('status', filter);
      const result = await api(`/admin/ncdc-report-queue?${params.toString()}`);
      setQueue(result);
    } catch (err) {
      setError(err.message || 'Could not load the NCDC report review queue.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filter]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(() => refresh(true), 60000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const updateReview = async (item, status) => {
    setSavingId(item.report_id);
    setError('');
    try {
      await api(`/admin/ncdc-report-queue/items/${encodeURIComponent(item.report_id)}/review`, {
        method: 'POST',
        body: JSON.stringify({ status, notes: notesById[item.report_id] || item.review_notes || '' }),
      });
      await refresh(true);
    } catch (err) {
      setError(err.message || 'Could not update this report review.');
    } finally {
      setSavingId('');
    }
  };

  const counts = queue?.counts || {};
  return (
    <div className="report-queue-page">
      <section className="hero-compact report-queue-hero">
        <div><Badge tone="blue">OFFICIAL SOURCE WORKFLOW</Badge><h2>NCDC report review queue</h2>
          <p>New weekly report links are discovered by the background source refresh and saved here for review.</p>
        </div><div className="report-queue-symbol">⇣</div>
      </section>
      <section className="panel report-queue-panel">
        <div className="panel-heading">
          <div><span className="eyebrow">SOURCE DISCOVERY</span><h3>Reports awaiting review</h3>
            <p className="muted small">Last queue sync: {formatDateTime(queue?.last_sync_at)} · Source status: {queue?.source_status || 'not checked'}</p>
          </div>
          <button className="button button-outline" disabled={refreshing} onClick={() => refresh()}>{refreshing ? 'Refreshing…' : 'Refresh queue'}</button>
        </div>
        <div className="report-queue-summary">
          <button className={filter === 'pending_review' ? 'queue-filter active' : 'queue-filter'} onClick={() => setFilter('pending_review')}><strong>{formatNumber(counts.pending_review)}</strong><span>Pending review</span></button>
          <button className={filter === 'reviewed' ? 'queue-filter active' : 'queue-filter'} onClick={() => setFilter('reviewed')}><strong>{formatNumber(counts.reviewed)}</strong><span>Marked reviewed</span></button>
          <button className={filter === 'ignored' ? 'queue-filter active' : 'queue-filter'} onClick={() => setFilter('ignored')}><strong>{formatNumber(counts.ignored)}</strong><span>Ignored</span></button>
          <button className={filter === 'all' ? 'queue-filter active' : 'queue-filter'} onClick={() => setFilter('all')}><strong>{formatNumber(queue?.counts ? Object.values(queue.counts).reduce((a, b) => a + Number(b || 0), 0) : 0)}</strong><span>All queued</span></button>
        </div>
        <div className="report-queue-warning"><strong>Important:</strong> This queue tracks official PDF discovery and human review only. Marking a report reviewed does not extract or import case/death counts. Only validated records imported through the staging workflow appear in surveillance totals and map values.</div>
        {error && <div className="alert-banner error-banner"><strong>Queue issue</strong><span>{error}</span></div>}
        {loading ? <div className="loading-line"><span className="spinner" /> Loading source review queue…</div> : (
          <div className="report-queue-list">
            {(queue?.items || []).map((item) => (
              <article className="report-queue-card" key={item.report_id}>
                <div className="report-queue-card-main">
                  <div className="report-queue-card-title"><Badge tone={item.status === 'pending_review' ? 'warning' : item.status === 'reviewed' ? 'success' : 'neutral'}>{item.status.replace('_', ' ')}</Badge>
                    <strong>{item.title || 'NCDC weekly outbreak report'}</strong></div>
                  <p className="muted small">{item.year ? `Year ${item.year}` : 'Year not identified'}{item.week ? ` · Week ${item.week}` : ''} · First seen {formatDateTime(item.first_seen_at)}</p>
                  <a className="source-link" href={item.url} target="_blank" rel="noreferrer">Open official NCDC PDF ↗</a>
                  <label className="report-queue-notes">Review notes<textarea rows={2} maxLength={2000} value={notesById[item.report_id] ?? item.review_notes ?? ''} onChange={(event) => setNotesById((prev) => ({ ...prev, [item.report_id]: event.target.value }))} placeholder="e.g. reporting period checked; table needs manual extraction" /></label>
                </div>
                <div className="report-queue-actions">
                  {item.status !== 'reviewed' && <button className="button button-primary" disabled={savingId === item.report_id} onClick={() => updateReview(item, 'reviewed')}>{savingId === item.report_id ? 'Saving…' : 'Mark reviewed'}</button>}
                  {item.status !== 'ignored' && <button className="button button-quiet" disabled={savingId === item.report_id} onClick={() => updateReview(item, 'ignored')}>Ignore</button>}
                  {item.status !== 'pending_review' && <button className="button button-quiet" disabled={savingId === item.report_id} onClick={() => updateReview(item, 'pending_review')}>Reopen</button>}
                </div>
              </article>
            ))}
            {!queue?.items?.length && <EmptyState title="No reports in this view" body={filter === 'pending_review' ? 'No new reports are waiting right now. The queue will update when the background source refresh discovers new official PDFs.' : 'No reports match this status filter yet.'} />}
          </div>
        )}
        {queue?.interpretation && <p className="muted small report-queue-footnote">{queue.interpretation}</p>}
        <p className="report-queue-attribution">Source archive: <a className="source-link" href="https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php" target="_blank" rel="noreferrer">NCDC / IDSP Weekly Outbreak Reports ↗</a></p>
      </section>
    </div>
  );
}



function ReportReviewQueuePanel() {
  const [queue, setQueue] = useState(null);
  const [statusFilter, setStatusFilter] = useState('pending_review');
  const [notesById, setNotesById] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [savingId, setSavingId] = useState('');
  const [notice, setNotice] = useState('');

  const refreshQueue = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const query = statusFilter === 'all'
        ? '?limit=200'
        : `?status=${encodeURIComponent(statusFilter)}&limit=200`;
      const result = await api(`/admin/ncdc-report-queue${query}`);
      setQueue(result);
      setNotesById((previous) => {
        const next = { ...previous };
        for (const item of (result.items || [])) {
          if (next[item.report_id] === undefined) next[item.report_id] = item.review_notes || '';
        }
        return next;
      });
    } catch (err) {
      setError(err.message || 'Could not load the report review queue.');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { refreshQueue(); }, [refreshQueue]);

  const saveReview = async (item, nextStatus) => {
    setSavingId(item.report_id);
    setError('');
    setNotice('');
    try {
      await api(`/admin/ncdc-report-queue/items/${encodeURIComponent(item.report_id)}/review`, {
        method: 'POST',
        body: JSON.stringify({ status: nextStatus, notes: notesById[item.report_id] || '' }),
      });
      setNotice(nextStatus === 'reviewed'
        ? 'Review marked complete. This does not import case counts into live surveillance.'
        : nextStatus === 'ignored'
          ? 'Report marked ignored; it remains in the review history.'
          : 'Report returned to pending review.');
      await refreshQueue();
    } catch (err) {
      setError(err.message || 'Could not save the review decision.');
    } finally {
      setSavingId('');
    }
  };

  const counts = queue?.counts || {};
  return (
    <div className="rq-page">
      <section className="hero-compact rq-hero">
        <div>
          <Badge tone="blue">OFFICIAL SOURCE REVIEW</Badge>
          <h2>NCDC report review queue</h2>
          <p>Newly discovered official PDF links are tracked here. Review the source report and record notes before any separate, approved data import.</p>
        </div>
        <div className="rq-hero-symbol" aria-hidden="true">PDF</div>
      </section>

      {error && <div className="alert-banner error-banner"><strong>Queue issue</strong><span>{error}</span></div>}
      {notice && <div className="alert-banner info-banner"><strong>Saved</strong><span>{notice}</span><button className="close-notice" aria-label="Dismiss notice" onClick={() => setNotice('')}>×</button></div>}

      <section className="metric-grid three-metrics rq-metrics">
        <MetricCard label="Pending review" value={counts.pending_review ?? 0} footnote="Awaiting human review" accent="rose" glyph="◷" />
        <MetricCard label="Reviewed" value={counts.reviewed ?? 0} footnote="Review status only; not imported" accent="teal" glyph="✓" />
        <MetricCard label="Ignored" value={counts.ignored ?? 0} footnote="Retained in queue history" accent="violet" glyph="—" />
      </section>

      <section className="panel rq-panel">
        <div className="panel-heading rq-toolbar">
          <div><span className="eyebrow">REPORT CATALOGUE</span><h3>Discovered official reports</h3>
            <p className="muted small">{queue?.total ?? 0} report(s) in the selected view · last queue sync: {formatDateTime(queue?.last_sync_at)}</p>
          </div>
          <div className="rq-toolbar-actions">
            <label className="rq-filter-label">Status
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="pending_review">Pending review</option>
                <option value="reviewed">Reviewed</option>
                <option value="ignored">Ignored</option>
                <option value="all">All reports</option>
              </select>
            </label>
            <button className="button button-outline" onClick={refreshQueue} disabled={loading || Boolean(savingId)}>{loading ? 'Loading…' : 'Refresh queue'}</button>
          </div>
        </div>
        {loading && <div className="loading-line"><span className="spinner" /> Loading report queue…</div>}
        {!loading && !error && (queue?.items || []).length === 0 && <EmptyState title="No reports in this view" body="Try another status or refresh the queue. Source discovery may return the same reports until NCDC publishes updates." />}
        <div className="rq-list">
          {(queue?.items || []).map((item) => (
            <article className="rq-item" key={item.report_id}>
              <div className="rq-item-main">
                <div className="rq-item-title-row">
                  <strong>{item.title || 'NCDC weekly outbreak report'}</strong>
                  <Badge tone={item.status === 'reviewed' ? 'success' : item.status === 'ignored' ? 'neutral' : 'warning'}>{(item.status || 'pending_review').replaceAll('_', ' ')}</Badge>
                </div>
                <div className="rq-meta"><span>First seen: {formatDateTime(item.first_seen_at)}</span><span>Last seen: {formatDateTime(item.last_seen_at)}</span></div>
                <div className="rq-links"><a className="source-link" href={item.url} target="_blank" rel="noreferrer">Open official PDF ↗</a><a className="source-link" href={item.archive_url || 'https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php'} target="_blank" rel="noreferrer">NCDC archive ↗</a></div>
                <label className="rq-notes-label">Review notes
                  <textarea rows={2} maxLength={2000} value={notesById[item.report_id] ?? item.review_notes ?? ''} onChange={(event) => setNotesById((previous) => ({ ...previous, [item.report_id]: event.target.value }))} placeholder="Record source page/table, corrections needed, or supervisor notes…" />
                </label>
                <div className="rq-item-actions">
                  <button className="button button-primary" disabled={Boolean(savingId)} onClick={() => saveReview(item, 'reviewed')}>{savingId === item.report_id ? 'Saving…' : 'Mark reviewed'}</button>
                  <button className="button button-outline" disabled={Boolean(savingId)} onClick={() => saveReview(item, 'ignored')}>Ignore</button>
                  {item.status !== 'pending_review' && <button className="button button-quiet" disabled={Boolean(savingId)} onClick={() => saveReview(item, 'pending_review')}>Reopen</button>}
                </div>
              </div>
            </article>
          ))}
        </div>
        <p className="rq-caution">Important: “Reviewed” records a human review decision only. It does not authorize import into PostgreSQL or mark case counts as confirmed. Use the separate validated staging and explicit-approval workflow.</p>
      </section>
    </div>
  );
}

/* SAMRAKSHA_STAGING_PREVIEW_UI */
function StagedNcdcPreviewPanel() {
  const [data, setData] = useState(null);
  const [statusFilter, setStatusFilter] = useState('pending_supervisor_review');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (statusFilter !== 'all') params.set('review_status', statusFilter);
      setData(await api(`/admin/ncdc-staging/summary?${params.toString()}`));
    } catch (err) {
      setError(err.message || 'Could not load NCDC staging data.');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { loadData(); }, [loadData]);
  const totals = data?.totals || {};
  const states = data?.by_state || [];
  const rows = data?.items || [];
  return (
    <div className="sk-staging-page">
      <section className="hero-compact sk-staging-hero">
        <div><Badge tone="blue">SEPARATE REVIEW DATASET</Badge><h2>NCDC staging data preview</h2>
          <p>Inspect extracted weekly report rows before approval. This page is read-only and never promotes data into live surveillance.</p></div>
        <div className="sk-staging-mark" aria-hidden="true">QA</div>
      </section>
      {error && <div className="alert-banner error-banner"><strong>Staging preview issue</strong><span>{error}</span></div>}
      <section className="metric-grid three-metrics">
        <MetricCard label="Staged records" value={data?.total_records ?? 0} footnote="Separate from live surveillance" accent="blue" glyph="▤" />
        <MetricCard label="Known cases sum" value={totals.known_cases_sum} footnote="Staging sum only; not a national total" accent="teal" glyph="⌁" />
        <MetricCard label="Unknown case rows" value={totals.unknown_case_rows ?? 0} footnote="Not treated as zero" accent="rose" glyph="?" />
      </section>
      <section className="panel">
        <div className="panel-heading sk-staging-toolbar">
          <div><span className="eyebrow">REVIEW STATE</span><h3>Rows awaiting or completing review</h3>
            <p className="muted small">Pending: {formatNumber(data?.status_counts?.pending_supervisor_review ?? 0)} · Promoted: {formatNumber(data?.status_counts?.promoted_to_live_surveillance ?? 0)} · Unknown deaths: {formatNumber(totals.unknown_death_rows ?? 0)}</p>
          </div>
          <div className="sk-staging-actions">
            <label>Status<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="pending_supervisor_review">Pending supervisor review</option>
              <option value="promoted_to_live_surveillance">Promoted to live</option>
              <option value="all">All staging rows</option>
            </select></label>
            <button className="button button-outline" onClick={loadData} disabled={loading}>{loading ? 'Loading…' : 'Refresh staging'}</button>
          </div>
        </div>
        {loading && <div className="loading-line"><span className="spinner" /> Loading staged records…</div>}
        {!loading && !error && rows.length === 0 && <EmptyState title="No staging rows in this view" body="The staging table may be empty or all rows may have a different review status." />}
        {!loading && rows.length > 0 && <div className="sk-staging-table-wrap"><table className="sk-staging-table"><thead><tr><th>Record ID</th><th>State / District</th><th>Disease</th><th>Cases</th><th>Deaths</th><th>Review status</th><th>Source</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.record_id}><td><code>{row.record_id}</code><small>{row.report_year}-W{String(row.report_week).padStart(2, '0')}</small></td><td>{row.state}<small>{row.district}</small></td><td>{row.disease}</td><td>{row.cases == null ? 'Unknown' : formatNumber(row.cases)}</td><td>{row.deaths == null ? 'Unknown' : formatNumber(row.deaths)}</td><td><Badge tone={row.review_status === 'promoted_to_live_surveillance' ? 'success' : 'warning'}>{String(row.review_status || 'unknown').replaceAll('_', ' ')}</Badge></td><td>{row.source_url ? <a className="source-link" href={row.source_url} target="_blank" rel="noreferrer">Open PDF ↗</a> : 'Unavailable'}</td></tr>)}</tbody></table></div>}
      </section>
      <section className="panel">
        <div className="panel-heading"><div><span className="eyebrow">STATE BREAKDOWN</span><h3>Staging cases by state</h3><p className="muted small">Only known case values are summed; this is not a unique-person count.</p></div></div>
        {states.length ? <div className="sk-staging-state-grid">{states.slice(0, 12).map((row) => <div className="sk-staging-state" key={row.state}><strong>{row.state || 'Unknown state'}</strong><span>{row.known_cases_sum == null ? 'Cases unknown' : `${formatNumber(row.known_cases_sum)} known cases`}</span><small>{formatNumber(row.records)} rows · {formatNumber(row.unknown_case_rows)} missing case counts</small></div>)}</div> : <EmptyState title="No state aggregates" body="State breakdowns appear when staging rows are available." />}
      </section>
      <p className="sk-staging-warning">{data?.data_note || 'Staging data is separate from live surveillance and requires human review.'}</p>
    </div>
  );
}

function Dashboard({ onLogout }) {
  const [page, setPage] = useState('overview');
  const [summary, setSummary] = useState(null);
  const [records, setRecords] = useState([]);
  const [totalRecords, setTotalRecords] = useState(0);
  const [pageIndex, setPageIndex] = useState(1);
  const [filters, setFilters] = useState({ state: '', district: '', disease: '', year: '' });
  const [appliedFilters, setAppliedFilters] = useState({ state: '', district: '', disease: '', year: '' });
  const [anomalies, setAnomalies] = useState([]);
  const [icaResult, setIcaResult] = useState(null);
  const [icaComponents, setIcaComponents] = useState(2);
  const [loading, setLoading] = useState(true);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [wsStatus, setWsStatus] = useState('connecting');
  const [liveEvents, setLiveEvents] = useState([]);
  const [notice, setNotice] = useState('');
  const [globalFeed, setGlobalFeed] = useState(null);
  const [globalFeedLoading, setGlobalFeedLoading] = useState(false);
  const [globalFeedError, setGlobalFeedError] = useState('');
  const [indiaReports, setIndiaReports] = useState(null);
  const [indiaReportsLoading, setIndiaReportsLoading] = useState(false);
  const [indiaReportsError, setIndiaReportsError] = useState('');

  const filterParams = useMemo(() => {
    const p = new URLSearchParams();
    Object.entries(appliedFilters).forEach(([key, value]) => { if (String(value || '').trim()) p.set(key, String(value).trim()); });
    return p;
  }, [appliedFilters]);

  const refreshSummary = useCallback(async () => {
    const result = await api(`/public/surveillance/summary${filterParams.toString() ? `?${filterParams}` : ''}`);
    setSummary(result);
  }, [filterParams]);

  const refreshRecords = useCallback(async () => {
    setRecordsLoading(true);
    try {
      const params = new URLSearchParams(filterParams);
      params.set('page', String(pageIndex));
      params.set('page_size', '30');
      const result = await api(`/public/surveillance?${params.toString()}`);
      setRecords(result.items || []);
      setTotalRecords(Number(result.total || 0));
    } finally {
      setRecordsLoading(false);
    }
  }, [filterParams, pageIndex]);

  const refreshAnomalies = useCallback(async () => {
    const result = await api('/analytics/anomalies');
    setAnomalies(result.items || []);
  }, []);

  const refreshGlobalSignals = useCallback(async (forceRefresh = false) => {
    setGlobalFeedLoading(true);
    setGlobalFeedError('');
    try {
      const result = await api(`/public/global-outbreaks?limit=25${forceRefresh ? '&force_refresh=true' : ''}`);
      setGlobalFeed(result);
    } catch (err) {
      setGlobalFeedError(err.message || 'Could not load the WHO public feed.');
    } finally {
      setGlobalFeedLoading(false);
    }
  }, []);

  const refreshIndiaReports = useCallback(async (forceRefresh = false) => {
    setIndiaReportsLoading(true);
    setIndiaReportsError('');
    try {
      const result = await api(`/public/india-outbreak-reports?limit=50${forceRefresh ? '&force_refresh=true' : ''}`);
      setIndiaReports(result);
    } catch (err) {
      setIndiaReportsError(err.message || 'Could not load the official NCDC weekly-outbreak archive.');
    } finally {
      setIndiaReportsLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    Promise.all([refreshSummary(), refreshRecords(), refreshAnomalies()])
      .catch((err) => { if (alive) setError(err.message || 'Could not connect to the API.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [refreshSummary, refreshRecords, refreshAnomalies]);

  useEffect(() => {
    if (page !== 'signals' && page !== 'overview') return undefined;
    refreshGlobalSignals();
    const refreshTimer = window.setInterval(() => refreshGlobalSignals(), 15 * 60 * 1000);
    return () => window.clearInterval(refreshTimer);
  }, [page, refreshGlobalSignals]);

  useEffect(() => {
    if (page !== 'india-reports' && page !== 'overview') return undefined;
    refreshIndiaReports();
    const refreshTimer = window.setInterval(() => refreshIndiaReports(), 15 * 60 * 1000);
    return () => window.clearInterval(refreshTimer);
  }, [page, refreshIndiaReports]);

  useEffect(() => {
    let stopped = false;
    let socket;
    let reconnectTimer;
    const connect = () => {
      if (stopped) return;
      const wsUrl = `${API_BASE.replace(/^http/, 'ws')}/ws/alerts`;
      try { socket = new WebSocket(wsUrl); } catch { setWsStatus('offline'); return; }
      socket.onopen = () => { setWsStatus('connecting'); try { socket.send(JSON.stringify({ type: 'authenticate', token: sessionStorage.getItem('sk_access_token') })); } catch { setWsStatus('offline'); } };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'connection_ready') { setWsStatus('live'); try { socket.send('ping'); } catch { /* ignore a closing socket */ } return; }
          if (payload.type === 'pong') return;
          setLiveEvents((previous) => [payload, ...previous].slice(0, 6));
          setNotice(payload.is_synthetic ? 'Demo notification received (synthetic only).' : 'New screening notification received.');
        } catch { /* ignore non-JSON messages */ }
      };
      socket.onerror = () => setWsStatus('offline');
      socket.onclose = () => { setWsStatus('reconnecting'); if (!stopped) reconnectTimer = window.setTimeout(connect, 2500); };
    };
    connect();
    return () => { stopped = true; window.clearTimeout(reconnectTimer); if (socket) socket.close(); };
  }, []);

  const applyFilters = (event) => {
    event.preventDefault(); setPageIndex(1); setAppliedFilters({ ...filters });
  };
  const clearFilters = () => { const empty = { state: '', district: '', disease: '', year: '' }; setFilters(empty); setAppliedFilters(empty); setPageIndex(1); };

  const triggerDemo = async () => {
    setWorking(true); setError('');
    try { const result = await api('/analytics/demo-anomaly', { method: 'POST' }); setNotice(`${result.message} ${result.delivered_clients} live client(s) received it.`); }
    catch (err) { setError(err.message); }
    finally { setWorking(false); }
  };

  const runDetection = async () => {
    setWorking(true); setError('');
    try {
      const result = await api('/analytics/anomalies/run', { method: 'POST' });
      setAnomalies(result.items || []);
      setNotice(`Screening finished: ${result.count} potential anomaly/anomalies; ${result.delivered_messages} live message delivery/deliveries.`);
    } catch (err) { setError(err.message); }
    finally { setWorking(false); }
  };

  const loadIca = async () => {
    setWorking(true); setError(''); setIcaResult(null);
    try { setIcaResult(await api(`/analytics/ica?components=${icaComponents}`)); }
    catch (err) { setError(err.message); }
    finally { setWorking(false); }
  };

  const csvUrl = `${API_BASE}/public/surveillance/export.csv${filterParams.toString() ? `?${filterParams}` : ''}`;
  const downloadCsv = useCallback(async () => {
    try {
      const token = sessionStorage.getItem('sk_access_token');
      const response = await fetch(csvUrl, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (response.status === 401) { sessionStorage.removeItem('sk_access_token'); window.dispatchEvent(new Event('sk-auth-expired')); }
      if (!response.ok) throw new Error(`CSV download failed (${response.status})`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'samraksha-surveillance.csv'; anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) { setError(err.message || 'Could not export CSV.'); }
  }, [csvUrl]);
  const pageCount = Math.max(1, Math.ceil(totalRecords / 30));
  const pageMeta = navItems.find((item) => item.id === page) || navItems[0];

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">SK</div><div><strong>Samraksha Kendra</strong><small>PUBLIC HEALTH INTELLIGENCE</small></div></div>
      <div className="nav-label">WORKSPACE</div>
      <nav>{navItems.map((item) => <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}><span className="nav-glyph">{item.glyph}</span>{item.label}{page === item.id && <span className="nav-indicator" />}</button>)}</nav>
      <div className="sidebar-bottom"><div className={`connection-pill ${wsStatus}`}><span className="status-dot" />{wsStatus === 'live' ? 'Live alerts connected' : wsStatus === 'connecting' || wsStatus === 'reconnecting' ? 'Connecting live alerts…' : 'Live alerts offline'}</div><div className="sidebar-note">Aggregate historical data for awareness and research. Not a diagnostic service.</div><div className="footer-brand">SAMRAKSHA KENDRA <span>•</span> REVIEW BUILD</div></div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div><div className="eyebrow">SURVEILLANCE WORKSPACE / {pageMeta.label.toUpperCase()}</div><h1>{page === 'overview' ? 'Public health overview' : pageMeta.label}</h1><p>{page === 'overview' ? 'Understand available surveillance data and recent signals.' : page === 'history' ? 'Explore public, aggregate historical surveillance records.' : page === 'signals' ? 'View newly published official global outbreak notices.' : page === 'india-reports' ? 'Browse official Indian weekly outbreak reports.' : page === 'staged-data' ? 'Inspect numerical NCDC candidates awaiting supervisor review.' : page === 'anomalies' ? 'Inspect statistical flags and safely test live event delivery.' : page === 'map' ? 'Explore the latest available reporting period by state and review historical anomaly candidates.' : 'Explore statistical independent components from disease-count signals.'}</p></div><div className="topbar-actions"><Badge tone={wsStatus === 'live' ? 'success' : 'neutral'}>{wsStatus === 'live' ? 'LIVE STREAM ON' : 'STREAM '+wsStatus.toUpperCase()}</Badge><button className="button button-quiet" onClick={() => { setAppliedFilters({ state: '', district: '', disease: '', year: '' }); setFilters({ state: '', district: '', disease: '', year: '' }); setPageIndex(1); }} title="Clear all data filters">Reset filters</button><button className="button button-quiet" onClick={onLogout}>Sign out</button></div></header>

      {error && <div className="alert-banner error-banner"><strong>API issue</strong><span>{error}</span><span className="hint">Confirm FastAPI is running and the enhancement router has been included.</span></div>}
      {notice && <div className="alert-banner info-banner"><strong>Update</strong><span>{notice}</span><button className="close-notice" aria-label="Dismiss notice" onClick={() => setNotice('')}>×</button></div>}
      {loading && <div className="loading-line"><span className="spinner" /> Loading surveillance data…</div>}

      {page === 'overview' && <>
        <section className="hero-panel"><div className="hero-copy"><Badge tone="blue">IDSP DATA EXPLORER</Badge><h2>Evidence-led monitoring.<br /><em>Earlier signals.</em></h2><p>A shared workspace to inspect historical reports, investigate possible anomalies and demonstrate real-time alert delivery.</p><div className="hero-actions"><button className="button button-primary" onClick={() => setPage('history')}>Explore historical data <span>→</span></button><button className="button button-outline" onClick={() => setPage('anomalies')}>Open anomaly lab</button></div></div><div className="hero-visual"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="hero-core"><span>SK</span><small>MONITORING</small></div><div className="orbit-tag tag-one"><span className="status-dot" /> DATA</div><div className="orbit-tag tag-two">↗ SIGNALS</div><div className="orbit-tag tag-three">◉ INSIGHTS</div></div></section>
        <div className="section-heading"><div><span className="eyebrow">CURRENT DATASET</span><h2>At a glance</h2></div><span className="muted small">Values reflect records loaded into this installation</span></div>
        <section className="metric-grid"><MetricCard label="Surveillance records" value={summary?.total_records} footnote="Available aggregate records" accent="blue" glyph="▤"/><MetricCard label="Reported cases" value={summary?.total_cases} footnote="Sum of available case counts" accent="teal" glyph="⌁"/><MetricCard label="Reported deaths" value={summary?.total_deaths} footnote="Sum of available death counts" accent="rose" glyph="＋"/><MetricCard label="States / UTs" value={summary?.states_count} footnote={`${formatNumber(summary?.diseases_count)} distinct disease labels`} accent="violet" glyph="◎"/></section>
        <section className="panel official-live-panel">
          <div className="panel-heading official-live-heading">
            <div><span className="eyebrow">LIVE OFFICIAL SOURCE UPDATES</span><h3>Latest published outbreak intelligence</h3><p className="muted small">Fetched from WHO and the official NCDC/IDSP weekly report catalogue. These publication feeds are separate from the 246 historical structured surveillance rows.</p></div>
            <button className="button button-outline" disabled={globalFeedLoading || indiaReportsLoading} onClick={async () => { await Promise.allSettled([refreshGlobalSignals(true), refreshIndiaReports(true)]); }}>{globalFeedLoading || indiaReportsLoading ? 'Refreshing sources…' : 'Refresh official sources'}</button>
          </div>
          <div className="official-live-grid">
            <section className="official-live-source">
              <div className="official-live-source-top"><div><strong>WHO Disease Outbreak News</strong><small>Latest public global notices</small></div><Badge tone={globalFeed?.status === 'available' ? 'success' : globalFeed?.status === 'stale' ? 'warning' : 'neutral'}>{globalFeed?.status || (globalFeedLoading ? 'loading' : 'not checked')}</Badge></div>
              <div className="feed-metadata"><span>Last checked: {formatDateTime(globalFeed?.last_checked_at)}</span><span>Last success: {formatDateTime(globalFeed?.last_successful_fetch_at)}</span></div>
              {globalFeedError && <p className="feed-warning-text">{globalFeedError}</p>}
              {globalFeed?.items?.length ? <div className="official-live-items">{globalFeed.items.slice(0, 3).map((item) => <article className="official-live-item" key={item.id}><div className="official-live-date">Published {formatDateTime(item.publication_date)}</div><strong>{item.title}</strong><p>{item.summary}</p><a className="source-link" href={item.url} target="_blank" rel="noreferrer">Read WHO notice ↗</a></article>)}</div> : <p className="muted small">{globalFeedLoading ? 'Fetching latest WHO notices…' : 'No WHO notices loaded yet. Use Refresh official sources.'}</p>}
            </section>
            <section className="official-live-source">
              <div className="official-live-source-top"><div><strong>NCDC / IDSP India reports</strong><small>Official weekly report catalogue</small></div><Badge tone={indiaReports?.status === 'available' ? 'success' : indiaReports?.status === 'stale' ? 'warning' : 'neutral'}>{indiaReports?.status || (indiaReportsLoading ? 'loading' : 'not checked')}</Badge></div>
              <div className="feed-metadata"><span>Last checked: {formatDateTime(indiaReports?.last_checked_at)}</span><span>Last success: {formatDateTime(indiaReports?.last_successful_fetch_at)}</span></div>
              {indiaReportsError && <p className="feed-warning-text">{indiaReportsError}</p>}
              {indiaReports?.items?.length ? <div className="official-live-items">{indiaReports.items.slice(0, 5).map((item) => <article className="official-live-item official-live-report" key={item.url}><div className="official-live-date">{item.year ? `Year ${item.year}` : 'Official report'}{item.week ? ` · Week ${item.week}` : ''}</div><strong>{item.title}</strong><a className="source-link" href={item.url} target="_blank" rel="noreferrer">Open official NCDC report ↗</a></article>)}</div> : <p className="muted small">{indiaReportsLoading ? 'Checking the NCDC archive…' : 'No NCDC reports loaded yet. Use Refresh official sources.'}</p>}
            </section>
          </div>
          <p className="official-live-note">Refresh interval: every 15 minutes while this overview is open. “Last checked” is the retrieval time; the report’s publication date is shown separately. This is current public-source intelligence, not a continuous patient-level case-count feed. New numerical records are only added after report extraction, validation and import.</p>
        </section>
        <section className="content-grid main-chart-grid"><article className="panel large-panel"><div className="panel-heading"><div><span className="eyebrow">TIME SERIES</span><h3>Reported cases by reporting week</h3></div><Badge>Historical</Badge></div><TrendChart points={summary?.weekly_trend || []}/></article><article className="panel"><div className="panel-heading"><div><span className="eyebrow">GEOGRAPHY</span><h3>Top reported states</h3></div><span className="panel-icon">⌖</span></div><HorizontalBars items={summary?.top_states || []}/></article></section>
        <section className="content-grid"><article className="panel"><div className="panel-heading"><div><span className="eyebrow">DISEASE BREAKDOWN</span><h3>Most reported diseases</h3></div><button className="text-button" onClick={() => setPage('history')}>View data →</button></div><HorizontalBars items={summary?.top_diseases || []}/></article><article className="panel live-panel"><div className="panel-heading"><div><span className="eyebrow">EVENT STREAM</span><h3>Live alert activity</h3></div><Badge tone={wsStatus === 'live' ? 'success' : 'neutral'}>{wsStatus}</Badge></div>{liveEvents.length ? <div className="event-list">{liveEvents.slice(0, 4).map((event) => <EventRow key={event.event_id || `${event.created_at}-${event.type}`} event={event}/>)}</div> : <EmptyState title="No new live events" body="Keep this page open, then trigger a synthetic demo event from the Anomaly detection page."/>}<button className="button button-outline full-width" onClick={() => setPage('anomalies')}>Test live notification</button></article></section>
        <p className="data-disclaimer">Data note: summaries reflect only the surveillance records currently loaded in this installation. Counts can vary with source coverage, duplicates, reporting periods and updates. Anomaly flags are for review, not official outbreak declarations.</p>
      </>}

      {page === 'history' && <>
        <section className="panel filter-panel"><div className="panel-heading"><div><span className="eyebrow">PUBLIC DATA EXPLORER</span><h3>Find historical reports</h3><p className="muted small">Search available aggregate records. Personal/community reporter information is not exposed here.</p></div><Badge tone="blue">READ ONLY</Badge></div><form className="filter-form" onSubmit={applyFilters}>
          <label>State<input value={filters.state} onChange={(e) => setFilters({ ...filters, state: e.target.value })} placeholder="e.g. Karnataka" /></label>
          <label>District<input value={filters.district} onChange={(e) => setFilters({ ...filters, district: e.target.value })} placeholder="e.g. Bengaluru" /></label>
          <label>Disease<input value={filters.disease} onChange={(e) => setFilters({ ...filters, disease: e.target.value })} placeholder="e.g. Dengue" /></label>
          <label>Year<input type="number" min="2000" max="2100" value={filters.year} onChange={(e) => setFilters({ ...filters, year: e.target.value })} placeholder="All years" /></label>
          <div className="filter-actions"><button className="button button-primary" type="submit">Apply filters</button><button className="button button-quiet" type="button" onClick={clearFilters}>Clear</button></div>
        </form></section>
        <section className="panel table-panel"><div className="panel-heading"><div><span className="eyebrow">RESULTS</span><h3>Surveillance records <span className="inline-count">{formatNumber(totalRecords)}</span></h3></div><button className="button button-outline" onClick={downloadCsv}>↓ Export CSV</button></div>{recordsLoading ? <div className="loading-line"><span className="spinner"/> Loading records…</div> : records.length ? <div className="table-scroll"><table><thead><tr><th>Period</th><th>State / district</th><th>Disease</th><th>Cases</th><th>Deaths</th><th>Status</th><th>Source</th></tr></thead><tbody>{records.map((row) => <tr key={row.record_id || `${row.year}-${row.week}-${row.state}-${row.disease}`}><td><strong>{row.year}-W{String(row.week).padStart(2, '0')}</strong><small>{row.reporting_start_date || 'Date unavailable'}</small></td><td>{row.state || '—'}<small>{row.district || 'District not specified'}</small></td><td>{row.disease || '—'}</td><td className="number-cell">{formatNumber(row.cases)}</td><td className="number-cell">{formatNumber(row.deaths)}</td><td><Badge tone={/outbreak|alert/i.test(row.outbreak_status || '') ? 'warning' : 'neutral'}>{row.outbreak_status || 'Reported'}</Badge></td><td>{row.source_url ? <a className="source-link" href={row.source_url} target="_blank" rel="noreferrer">Source ↗</a> : <span className="muted">{row.source || '—'}</span>}</td></tr>)}</tbody></table></div> : <EmptyState title="No records matched" body="Try a broader state, district, disease or year filter."/>}<div className="pagination"><span className="muted small">Showing {records.length ? ((pageIndex-1)*30+1) : 0}–{Math.min(pageIndex*30,totalRecords)} of {formatNumber(totalRecords)}</span><div><button className="button button-quiet" disabled={pageIndex <= 1} onClick={() => setPageIndex((p) => Math.max(1, p-1))}>← Previous</button><span className="page-count">Page {pageIndex} / {pageCount}</span><button className="button button-quiet" disabled={pageIndex >= pageCount} onClick={() => setPageIndex((p) => Math.min(pageCount, p+1))}>Next →</button></div></div></section>
        <p className="data-disclaimer">CSV export is capped at 10,000 rows per request. This portal is intended for aggregate public-health awareness and research, not diagnosis or clinical decision-making.</p>
      </>}

      {page === 'signals' && <>
        <section className="hero-compact signals-hero"><div><Badge tone="blue">OFFICIAL PUBLIC SOURCE</Badge><h2>Global outbreak intelligence</h2><p>Latest notices published by the World Health Organization (WHO). This feed refreshes periodically and shows publication updates; it is not a continuous or district-level case-count stream.</p></div><div className="signals-glyph">↗</div></section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">EXTERNAL SOURCE FEED</span><h3>WHO Disease Outbreak News</h3><p className="muted small">Source: <a className="source-link" href="https://www.who.int/emergencies/disease-outbreak-news" target="_blank" rel="noreferrer">who.int ↗</a></p></div><div className="feed-actions"><Badge tone={globalFeed?.status === 'available' ? 'success' : globalFeed?.status === 'stale' ? 'warning' : 'neutral'}>{globalFeed?.status || (globalFeedLoading ? 'loading' : 'not loaded')}</Badge><button className="button button-outline" disabled={globalFeedLoading} onClick={() => refreshGlobalSignals(true)}>{globalFeedLoading ? 'Refreshing…' : 'Refresh feed'}</button></div></div>
          {globalFeedError && <div className="feed-warning"><strong>Feed unavailable</strong><span>{globalFeedError} Your local IDSP historical dataset is still available.</span></div>}
          {globalFeedLoading && !globalFeed && <div className="loading-line"><span className="spinner"/> Fetching official public notices…</div>}
          {globalFeed?.warning && <p className="feed-warning-text">{globalFeed.warning}</p>}
          <div className="feed-metadata"><span>Last checked: {formatDateTime(globalFeed?.last_checked_at)}</span><span>Last successful fetch: {formatDateTime(globalFeed?.last_successful_fetch_at)}</span><span>Auto-check: every 15 minutes while this page is open</span></div>
          {globalFeed?.items?.length ? <div className="source-notice-list">{globalFeed.items.map((item) => <article className="source-notice" key={item.id}><div className="source-notice-meta"><Badge tone="blue">WHO NOTICE</Badge><span>{formatDateTime(item.publication_date)}</span></div><h3>{item.title}</h3><p>{item.summary}</p><a className="source-link" href={item.url} target="_blank" rel="noreferrer">Read official WHO report ↗</a></article>)}</div> : !globalFeedLoading ? <EmptyState title="No public notices available" body={globalFeed?.source_error || 'The WHO feed may be temporarily unavailable. Try Refresh feed later; historical IDSP data remains separate.'}/> : null}
        </section>
        <section className="notice-panel signals-notice"><strong>How to interpret this feed</strong><p>WHO publishes reports when qualifying public-health events are selected for public communication. Publication time does not mean the underlying event happened at that moment, and WHO says its Disease Outbreak News is not an exhaustive list of every event it responds to. Do not add these notices to Indian case totals or treat them as an automatic outbreak declaration.</p></section>
      </>}


      {page === 'india-reports' && <>
        <section className="hero-compact india-reports-hero"><div><Badge tone="blue">OFFICIAL INDIAN SOURCE</Badge><h2>Indian outbreak report archive</h2><p>Browse official NCDC weekly outbreak PDFs compiled through India's Integrated Disease Surveillance Programme (IDSP). This catalogue refreshes periodically and links to official source reports.</p></div><div className="signals-glyph">⌂</div></section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">PUBLIC SOURCE FEED</span><h3>NCDC Weekly Outbreak Reports</h3><p className="muted small">Source: <a className="source-link" href="https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php" target="_blank" rel="noreferrer">ncdc.mohfw.gov.in ↗</a></p></div><div className="feed-actions"><Badge tone={indiaReports?.status === 'available' ? 'success' : indiaReports?.status === 'stale' ? 'warning' : 'neutral'}>{indiaReports?.status || (indiaReportsLoading ? 'loading' : 'not loaded')}</Badge><button className="button button-outline" disabled={indiaReportsLoading} onClick={() => refreshIndiaReports(true)}>{indiaReportsLoading ? 'Refreshing…' : 'Refresh archive'}</button></div></div>
          {indiaReportsError && <div className="feed-warning"><strong>Archive unavailable</strong><span>{indiaReportsError} Your existing IDSP historical records remain available.</span></div>}
          {indiaReportsLoading && !indiaReports && <div className="loading-line"><span className="spinner"/> Fetching official NCDC report links…</div>}
          {indiaReports?.warning && <p className="feed-warning-text">{indiaReports.warning}</p>}
          <div className="feed-metadata"><span>Last checked: {formatDateTime(indiaReports?.last_checked_at)}</span><span>Last successful fetch: {formatDateTime(indiaReports?.last_successful_fetch_at)}</span><span>Auto-check: every 15 minutes while this page is open</span><span>{formatNumber(indiaReports?.count || 0)} catalogue entries</span></div>
          {indiaReports?.items?.length ? <div className="source-notice-list">{indiaReports.items.map((item, index) => <article className="source-notice" key={item.url || `${item.year}-${item.week}-${index}`}><div className="source-notice-meta"><Badge tone="blue">{item.report_type === 'pdf' ? 'OFFICIAL REPORT' : 'ARCHIVE ENTRY'}</Badge><span>{item.year ? `Year ${item.year}` : 'Year shown on source page'}{item.week ? ` · Week ${item.week}` : ''}</span></div><h3>{item.title || 'NCDC weekly outbreak report'}</h3><p>{item.report_type === 'pdf' ? 'Official report document. Open the source to read the reporting period, reported disease alerts and state/UT information.' : 'Official IDSP archive entry. Open it to access the underlying week report if available.'}</p><a className="source-link" href={item.url} target="_blank" rel="noreferrer">{item.report_type === 'pdf' ? 'Open official NCDC report ↗' : 'Open official archive entry ↗'}</a></article>)}</div> : !indiaReportsLoading ? <EmptyState title="No report links discovered" body={indiaReports?.source_error || 'The archive may have changed or may be temporarily unavailable. Use the official IDSP archive link below; no case data has been fabricated or imported.'}/> : null}
          <p className="method-note">Official archive: <a className="source-link" href={indiaReports?.source_url || 'https://ncdc.mohfw.gov.in/includes/WeeklyOutbreaks.php'} target="_blank" rel="noreferrer">Weekly Outbreaks · NCDC / IDSP ↗</a></p>
        </section>
        <section className="notice-panel"><strong>How to use these reports in the project</strong><p>This page discovers and links to official NCDC weekly outbreak reports; it does not automatically convert PDF tables into numeric case/death counts or modify the existing surveillance database. To expand the structured historical dataset, each report must be parsed and validated first. Missing numeric counts remain unknown, not zero. These weekly publication updates are not a continuous real-time case feed.</p></section>
      </>}

      {page === 'anomalies' && <>
        <section className="hero-compact"><div><Badge tone="blue">EXPLAINABLE SCREENING</Badge><h2>Find unusual changes in reported cases.</h2><p>Historical screening compares a point with its preceding observations using a trailing median and robust median absolute deviation (MAD). Human review remains essential.</p></div><div className="hero-compact-icon">⌁</div></section>
        <div className="action-row"><button className="button button-primary" disabled={working} onClick={runDetection}>{working ? 'Working…' : 'Run historical screening'}</button><button className="button button-outline" disabled={working} onClick={triggerDemo}>{working ? 'Working…' : 'Generate synthetic demo event'}</button><Badge tone="warning">Demo data never enters real records</Badge></div>
        <section className="metric-grid three-metrics"><MetricCard label="Flagged historical patterns" value={anomalies.length} footnote="Current screening results" accent="rose" glyph="⌁"/><MetricCard label="Connected live clients" value={wsStatus === 'live' ? 1 : 0} footnote="This browser connection status" accent="teal" glyph="↗"/><MetricCard label="Synthetic events shown here" value={liveEvents.filter((e) => e.is_synthetic).length} footnote="Local event history" accent="violet" glyph="◇"/></section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">HISTORICAL RESULTS</span><h3>Potential anomalies</h3><p className="muted small">Requires enough previous observations within the same state-and-disease series.</p></div><Badge>{anomalies.length} found</Badge></div>{anomalies.length ? <div className="anomaly-list">{anomalies.map((item, i) => <div className="anomaly-card" key={`${item.state}-${item.disease}-${item.year}-${item.week}-${i}`}><div className="anomaly-bullet">!</div><div className="anomaly-body"><div className="anomaly-title-row"><strong>{item.disease}</strong><Badge tone={item.severity === 'HIGH' ? 'danger' : item.severity === 'MODERATE' ? 'warning' : 'blue'}>{item.severity}</Badge></div><p>{item.message}</p><div className="meta-row"><span>{item.state}</span><span>{item.year} · Week {item.week}</span><span>{item.method}</span></div></div><div className="anomaly-values"><strong>{formatNumber(item.cases)}</strong><small>cases</small><span>Baseline {formatNumber(item.baseline_median)}</span>{item.mad_score !== null && <span>Robust score {item.mad_score}</span>}</div></div>)}</div> : <EmptyState title="No historical anomalies flagged" body="This does not prove no outbreak exists. It means the current rule did not flag any eligible records in the loaded dataset."/>}</section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">REAL-TIME NOTIFICATIONS</span><h3>Events received by this browser</h3></div><Badge tone={wsStatus === 'live' ? 'success' : 'neutral'}>{wsStatus}</Badge></div>{liveEvents.length ? <div className="event-list">{liveEvents.map((event) => <EventRow key={event.event_id || event.created_at} event={event}/>)}</div> : <EmptyState title="Waiting for an event" body="Keep the WebSocket connected and select Generate synthetic demo event to test the live delivery path."/>}</section>
      </>}

      {page === 'report-queue' && <NCDCReportReviewQueue />}
      {page === 'map' && <IndiaMapHotspots />}

      {page === 'staged-data' && <StagedNcdcPreviewPanel />}

      {page === 'report-review' && <ReportReviewQueuePanel />}

      {page === 'ica' && <>
        <section className="hero-compact ica-hero"><div><Badge tone="violet">EXPERIMENTAL RESEARCH MODULE</Badge><h2>Independent Component Analysis</h2><p>FastICA explores statistically independent combinations of weekly disease-count signals. It does not prove causality and is not used to issue official alerts.</p></div><div className="ica-glyph">IC<small>A</small></div></section>
        <section className="panel ica-controls"><div><h3>Configure the experiment</h3><p className="muted small">The backend selects top disease features, creates year-week samples, standardizes varying columns and runs FastICA.</p></div><div className="ica-form"><label>Number of components<select value={icaComponents} onChange={(e) => setIcaComponents(Number(e.target.value))}><option value={2}>2 components</option><option value={3}>3 components</option><option value={4}>4 components</option><option value={5}>5 components</option></select></label><button className="button button-primary" disabled={working} onClick={loadIca}>{working ? 'Analysing…' : 'Run FastICA'}</button></div></section>
        {icaResult ? <>
          <section className="metric-grid three-metrics"><MetricCard label="Reporting periods" value={icaResult.sample_count} footnote="Year-week samples" accent="blue" glyph="◷"/><MetricCard label="Input disease signals" value={icaResult.features?.length} footnote="Varying features selected" accent="teal" glyph="⌁"/><MetricCard label="Independent components" value={icaResult.n_components} footnote="Requested model output" accent="violet" glyph="◉"/></section>
          <section className="panel"><div className="panel-heading"><div><span className="eyebrow">COMPONENT SIGNALS</span><h3>ICA outputs across reporting weeks</h3></div><Badge tone="violet">FastICA</Badge></div><IcaPlot signals={icaResult.signals}/></section>
          <section className="panel"><div className="panel-heading"><div><span className="eyebrow">MIXING WEIGHTS</span><h3>Disease contribution weights</h3></div></div><div className="table-scroll"><table><thead><tr><th>Component</th>{(icaResult.features || []).map((f) => <th key={f}>{f}</th>)}</tr></thead><tbody>{(icaResult.loadings || []).map((row) => <tr key={row.component}><td><strong>{row.component}</strong></td>{(icaResult.features || []).map((feature) => <td className="number-cell" key={feature}>{row.disease_weights[feature]}</td>)}</tr>)}</tbody></table></div><p className="method-note">{icaResult.interpretation_note}</p></section>
        </> : <section className="panel"><EmptyState title="ICA experiment not run" body="Run FastICA to analyse the dataset. If there are too few weekly periods or varying disease signals, the API will explain what additional data is required."/></section>}
        <section className="notice-panel"><strong>How to explain ICA in the review</strong><p>“We use ICA as an exploratory unsupervised analysis to transform multiple correlated disease-count signals into components that are statistically independent under the model assumptions. The current prototype visualizes these components; we have not established that they correspond to actual disease causes or that ICA independently predicts outbreaks.”</p></section>
      </>}

      <footer className="main-footer"><span>Samraksha Kendra · Digital Disease Surveillance & Early Warning System</span><span>Research prototype · Not a medical or official outbreak declaration service</span></footer>
    </main>
  </div>;
}

function EventRow({ event }) {
  const synthetic = Boolean(event.is_synthetic);
  const time = event.created_at ? new Date(event.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Just now';
  return <div className="event-row"><div className={`event-icon ${synthetic ? 'synthetic' : ''}`}>{synthetic ? 'D' : '!'}</div><div className="event-main"><div className="event-title">{event.disease || 'Surveillance alert'} <Badge tone={synthetic ? 'warning' : event.severity === 'HIGH' ? 'danger' : 'neutral'}>{synthetic ? 'DEMO' : event.severity || 'SCREENING'}</Badge></div><p>{event.message || `${event.state || 'Unknown area'} · ${event.cases ?? '—'} cases`}</p><small>{event.state || 'Unknown state'} · {time}</small></div></div>;
}

function LoginScreen({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = await api('/auth/login', { method: 'POST', body: JSON.stringify({ username: username.trim(), password }) });
      onLogin(result.access_token);
    } catch (err) { setError(err.message || 'Sign in failed.'); }
    finally { setBusy(false); }
  };
  return <main className="auth-screen"><form className="auth-card" onSubmit={submit}>
    <div className="auth-brand-mark">SK</div>
    <p className="auth-eyebrow">PUBLIC HEALTH INTELLIGENCE</p>
    <h1>Samraksha Kendra</h1>
    <p className="auth-subtitle">Sign in to access the surveillance workspace.</p>
    <label className="auth-label">Username<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required maxLength={100} /></label>
    <label className="auth-label">Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required maxLength={256} /></label>
    {error && <div className="auth-error" role="alert">{error}</div>}
    <button className="auth-submit" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Secure sign in'}</button>
    <p className="auth-footnote">Access is configured by the project administrator. There is no public self-registration.</p>
  </form></main>;
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(() => Boolean(sessionStorage.getItem('sk_access_token')));
  useEffect(() => {
    const onExpired = () => setAuthenticated(Boolean(sessionStorage.getItem('sk_access_token')));
    window.addEventListener('sk-auth-expired', onExpired);
    return () => window.removeEventListener('sk-auth-expired', onExpired);
  }, []);
  const handleLogin = (token) => { sessionStorage.setItem('sk_access_token', token); setAuthenticated(true); };
  const handleLogout = () => { sessionStorage.removeItem('sk_access_token'); setAuthenticated(false); };
  return authenticated ? <Dashboard onLogout={handleLogout} /> : <LoginScreen onLogin={handleLogin} />;
}


import React, { useCallback, useEffect, useMemo, useState } from 'react';

const API_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000').replace(/\/$/, '');
const navItems = [
  { id: 'overview', label: 'Overview', glyph: '◫' },
  { id: 'history', label: 'Historical data', glyph: '▤' },
  { id: 'signals', label: 'Global signals', glyph: '↗' },
  { id: 'india-reports', label: 'India reports', glyph: '⌂' },
  { id: 'anomalies', label: 'Anomaly detection', glyph: '⌁' },
  { id: 'ica', label: 'ICA lab', glyph: '◉' },
];

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
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

export default function App() {
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
    if (page !== 'signals') return undefined;
    refreshGlobalSignals();
    const refreshTimer = window.setInterval(() => refreshGlobalSignals(), 15 * 60 * 1000);
    return () => window.clearInterval(refreshTimer);
  }, [page, refreshGlobalSignals]);

  useEffect(() => {
    if (page !== 'india-reports') return undefined;
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
      socket.onopen = () => { setWsStatus('live'); try { socket.send('ping'); } catch { /* connection is still establishing */ } };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'pong' || payload.type === 'connection_ready') return;
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
      <header className="topbar"><div><div className="eyebrow">SURVEILLANCE WORKSPACE / {pageMeta.label.toUpperCase()}</div><h1>{page === 'overview' ? 'Public health overview' : pageMeta.label}</h1><p>{page === 'overview' ? 'Understand available surveillance data and recent signals.' : page === 'history' ? 'Explore public, aggregate historical surveillance records.' : page === 'signals' ? 'View newly published official global outbreak notices.' : page === 'india-reports' ? 'Browse official Indian weekly outbreak reports.' : page === 'anomalies' ? 'Inspect statistical flags and safely test live event delivery.' : 'Explore statistical independent components from disease-count signals.'}</p></div><div className="topbar-actions"><Badge tone={wsStatus === 'live' ? 'success' : 'neutral'}>{wsStatus === 'live' ? 'LIVE STREAM ON' : 'STREAM '+wsStatus.toUpperCase()}</Badge><button className="button button-quiet" onClick={() => { setAppliedFilters({ state: '', district: '', disease: '', year: '' }); setFilters({ state: '', district: '', disease: '', year: '' }); setPageIndex(1); }} title="Clear all data filters">Reset filters</button></div></header>

      {error && <div className="alert-banner error-banner"><strong>API issue</strong><span>{error}</span><span className="hint">Confirm FastAPI is running and the enhancement router has been included.</span></div>}
      {notice && <div className="alert-banner info-banner"><strong>Update</strong><span>{notice}</span><button className="close-notice" aria-label="Dismiss notice" onClick={() => setNotice('')}>×</button></div>}
      {loading && <div className="loading-line"><span className="spinner" /> Loading surveillance data…</div>}

      {page === 'overview' && <>
        <section className="hero-panel"><div className="hero-copy"><Badge tone="blue">IDSP DATA EXPLORER</Badge><h2>Evidence-led monitoring.<br /><em>Earlier signals.</em></h2><p>A shared workspace to inspect historical reports, investigate possible anomalies and demonstrate real-time alert delivery.</p><div className="hero-actions"><button className="button button-primary" onClick={() => setPage('history')}>Explore historical data <span>→</span></button><button className="button button-outline" onClick={() => setPage('anomalies')}>Open anomaly lab</button></div></div><div className="hero-visual"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="hero-core"><span>SK</span><small>MONITORING</small></div><div className="orbit-tag tag-one"><span className="status-dot" /> DATA</div><div className="orbit-tag tag-two">↗ SIGNALS</div><div className="orbit-tag tag-three">◉ INSIGHTS</div></div></section>
        <div className="section-heading"><div><span className="eyebrow">CURRENT DATASET</span><h2>At a glance</h2></div><span className="muted small">Values reflect records loaded into this installation</span></div>
        <section className="metric-grid"><MetricCard label="Surveillance records" value={summary?.total_records} footnote="Available aggregate records" accent="blue" glyph="▤"/><MetricCard label="Reported cases" value={summary?.total_cases} footnote="Sum of available case counts" accent="teal" glyph="⌁"/><MetricCard label="Reported deaths" value={summary?.total_deaths} footnote="Sum of available death counts" accent="rose" glyph="＋"/><MetricCard label="States / UTs" value={summary?.states_count} footnote={`${formatNumber(summary?.diseases_count)} distinct disease labels`} accent="violet" glyph="◎"/></section>
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
        <section className="panel table-panel"><div className="panel-heading"><div><span className="eyebrow">RESULTS</span><h3>Surveillance records <span className="inline-count">{formatNumber(totalRecords)}</span></h3></div><a className="button button-outline" href={csvUrl}>↓ Export CSV</a></div>{recordsLoading ? <div className="loading-line"><span className="spinner"/> Loading records…</div> : records.length ? <div className="table-scroll"><table><thead><tr><th>Period</th><th>State / district</th><th>Disease</th><th>Cases</th><th>Deaths</th><th>Status</th><th>Source</th></tr></thead><tbody>{records.map((row) => <tr key={row.record_id || `${row.year}-${row.week}-${row.state}-${row.disease}`}><td><strong>{row.year}-W{String(row.week).padStart(2, '0')}</strong><small>{row.reporting_start_date || 'Date unavailable'}</small></td><td>{row.state || '—'}<small>{row.district || 'District not specified'}</small></td><td>{row.disease || '—'}</td><td className="number-cell">{formatNumber(row.cases)}</td><td className="number-cell">{formatNumber(row.deaths)}</td><td><Badge tone={/outbreak|alert/i.test(row.outbreak_status || '') ? 'warning' : 'neutral'}>{row.outbreak_status || 'Reported'}</Badge></td><td>{row.source_url ? <a className="source-link" href={row.source_url} target="_blank" rel="noreferrer">Source ↗</a> : <span className="muted">{row.source || '—'}</span>}</td></tr>)}</tbody></table></div> : <EmptyState title="No records matched" body="Try a broader state, district, disease or year filter."/>}<div className="pagination"><span className="muted small">Showing {records.length ? ((pageIndex-1)*30+1) : 0}–{Math.min(pageIndex*30,totalRecords)} of {formatNumber(totalRecords)}</span><div><button className="button button-quiet" disabled={pageIndex <= 1} onClick={() => setPageIndex((p) => Math.max(1, p-1))}>← Previous</button><span className="page-count">Page {pageIndex} / {pageCount}</span><button className="button button-quiet" disabled={pageIndex >= pageCount} onClick={() => setPageIndex((p) => Math.min(pageCount, p+1))}>Next →</button></div></div></section>
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

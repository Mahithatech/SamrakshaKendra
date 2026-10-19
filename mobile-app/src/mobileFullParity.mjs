const numeric = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : null;
};

export function normalizeStateKey(value) {
  let key = String(value ?? '').trim().toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/\b(state of|the|nct of)\b/g, ' ')
    .replace(/[^a-z0-9]+/g, '');
  const aliases = {
    orissa: 'odisha',
    uttaranchal: 'uttarakhand',
    delhi: 'delhi',
    nctofdelhi: 'delhi',
    jammuandkashmir: 'jammuandkashmir',
    jammukashmir: 'jammuandkashmir',
    andamanandnicobarislands: 'andamanandnicobarislands',
    andamanandnicobar: 'andamanandnicobarislands',
    dadraandnagarhavelianddamananddiu: 'dadraandnagarhavelianddamananddiu',
    dadraandnagarhaveli: 'dadraandnagarhavelianddamananddiu',
    damananddiu: 'dadraandnagarhavelianddamananddiu',
    puducherry: 'puducherry',
    pondicherry: 'puducherry',
  };
  return aliases[key] || key;
}

export function summarizeLatestStateReports(records) {
  const valid = (Array.isArray(records) ? records : [])
    .filter((row) => row && typeof row === 'object' && String(row.state ?? '').trim())
    .map((row) => ({
      ...row,
      _year: Number(row.year),
      _week: Number(row.week),
      _stateKey: normalizeStateKey(row.state),
    }))
    .filter((row) => Number.isInteger(row._year) && row._year >= 1900 && Number.isInteger(row._week) && row._week >= 1 && row._week <= 53 && row._stateKey);
  if (!valid.length) {
    return { period: null, latestEndDate: null, totalRecords: 0, statesCount: 0, totalCases: null, totalDeaths: null, states: [], rows: [] };
  }
  valid.sort((a, b) => b._year - a._year || b._week - a._week);
  const year = valid[0]._year;
  const week = valid[0]._week;
  const rows = valid.filter((row) => row._year === year && row._week === week);
  const groups = new Map();
  let knownCaseValues = 0;
  let knownDeathValues = 0;
  let totalCases = 0;
  let totalDeaths = 0;
  for (const row of rows) {
    const key = row._stateKey;
    if (!groups.has(key)) groups.set(key, { key, state: String(row.state).trim(), cases: 0, deaths: 0, knownCases: 0, knownDeaths: 0, records: 0, rows: [] });
    const item = groups.get(key);
    item.records += 1;
    item.rows.push(row);
    const cases = numeric(row.cases);
    const deaths = numeric(row.deaths);
    if (cases !== null) { item.cases += cases; item.knownCases += 1; totalCases += cases; knownCaseValues += 1; }
    if (deaths !== null) { item.deaths += deaths; item.knownDeaths += 1; totalDeaths += deaths; knownDeathValues += 1; }
  }
  const states = [...groups.values()].map((item) => ({
    ...item,
    cases: item.knownCases ? item.cases : null,
    deaths: item.knownDeaths ? item.deaths : null,
    latestEndDate: item.rows.map((row) => row.reporting_end_date || row.reporting_start_date || '').filter(Boolean).sort().slice(-1)[0] || null,
  })).sort((a, b) => (b.cases ?? -1) - (a.cases ?? -1) || a.state.localeCompare(b.state));
  const latestEndDate = rows.map((row) => row.reporting_end_date || row.reporting_start_date || '').filter(Boolean).sort().slice(-1)[0] || null;
  return {
    period: { year, week, label: `${year}-W${String(week).padStart(2, '0')}` },
    latestEndDate,
    totalRecords: rows.length,
    statesCount: groups.size,
    totalCases: knownCaseValues ? totalCases : null,
    totalDeaths: knownDeathValues ? totalDeaths : null,
    states,
    rows,
  };
}

export function colorForMapState(state, snapshot, anomalyStateKeys = []) {
  const key = normalizeStateKey(state);
  const item = (snapshot?.states || []).find((row) => row.key === key);
  if (!item) return { fill: '#E3EAF2', status: 'no-data', cases: null };
  const anomalous = new Set((Array.isArray(anomalyStateKeys) ? anomalyStateKeys : []).map(normalizeStateKey));
  if (anomalous.has(key)) return { fill: '#C63C32', status: 'historical-anomaly-candidate', cases: item.cases };
  const known = (snapshot?.states || []).map((row) => row.cases).filter((value) => value !== null && Number.isFinite(value));
  const max = Math.max(1, ...known);
  const ratio = item.cases === null ? 0 : item.cases / max;
  const fill = ratio >= 0.75 ? '#087F73' : ratio >= 0.4 ? '#32A99A' : ratio > 0 ? '#9ADBD2' : '#D7F1ED';
  return { fill, status: item.cases === null ? 'unknown-count' : 'reported-activity', cases: item.cases };
}

export function normalizeStagingSummary(payload) {
  const raw = payload?.status_counts && typeof payload.status_counts === 'object' && !Array.isArray(payload.status_counts)
    ? payload.status_counts : {};
  const counts = {};
  for (const [key, value] of Object.entries(raw)) {
    const n = Number(value);
    counts[key] = Number.isFinite(n) && n >= 0 ? n : 0;
  }
  const total = Number(payload?.total_records);
  return {
    totalRecords: Number.isFinite(total) && total >= 0 ? total : Object.values(counts).reduce((sum, value) => sum + value, 0),
    statusCounts: counts,
    pending: counts.pending_supervisor_review ?? counts.pending_review ?? counts.pending ?? 0,
    note: typeof payload?.note === 'string' ? payload.note : typeof payload?.data_note === 'string' ? payload.data_note : 'Staged rows remain separate from live IDSP surveillance totals.',
  };
}

export function normalizeReviewerQueue(payload) {
  const items = Array.isArray(payload?.items) ? payload.items.filter((row) => row && typeof row === 'object') : [];
  const total = Number(payload?.total);
  const pending = Number(payload?.pending_total);
  return {
    items,
    total: Number.isFinite(total) && total >= 0 ? total : items.length,
    pendingTotal: Number.isFinite(pending) && pending >= 0 ? pending : 0,
    note: typeof payload?.data_note === 'string' ? payload.data_note : 'Each staged row must be checked against its official source PDF.',
  };
}

export function buildReviewerDecision(record, decision, reviewer, notes = '') {
  const recordId = String(record?.record_id ?? '').trim();
  const reviewerName = String(reviewer ?? '').trim();
  const cleanNotes = String(notes ?? '').trim();
  if (!recordId) throw new Error('The selected row has no record ID.');
  if (!['approved', 'rejected', 'needs_correction'].includes(decision)) throw new Error('Unsupported review decision.');
  if (reviewerName.length < 2) throw new Error('Enter your reviewer name for the audit trail.');
  if (decision !== 'approved' && !cleanNotes) throw new Error('Add a review note before rejecting a record or requesting correction.');
  return { record_id: recordId, decision, reviewer: reviewerName, notes: cleanNotes.slice(0, 2000) };
}

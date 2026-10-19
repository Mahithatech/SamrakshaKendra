const safeText = (value) => String(value ?? '').trim();
const safeNumber = (value) => {
  const number = Number(value ?? 0);
  return Number.isFinite(number) && number > 0 ? number : 0;
};
const isoDate = (record) => {
  const value = safeText(record?.reporting_end_date || record?.reporting_start_date || record?.date);
  const match = value.match(/^\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : '';
};

export function filterTrendRecords(records, filters = {}) {
  const rows = Array.isArray(records) ? records : [];
  const disease = safeText(filters.disease).toLocaleLowerCase();
  const state = safeText(filters.state).toLocaleLowerCase();
  const from = /^\d{4}-\d{2}-\d{2}$/.test(safeText(filters.fromDate)) ? safeText(filters.fromDate) : '';
  const to = /^\d{4}-\d{2}-\d{2}$/.test(safeText(filters.toDate)) ? safeText(filters.toDate) : '';
  return rows.filter((record) => {
    if (disease && !safeText(record?.disease).toLocaleLowerCase().includes(disease)) return false;
    if (state && !safeText(record?.state).toLocaleLowerCase().includes(state)) return false;
    const date = isoDate(record);
    if (from && (!date || date < from)) return false;
    if (to && (!date || date > to)) return false;
    return true;
  });
}

export function aggregateDistrictTrends(records) {
  const groups = new Map();
  for (const record of Array.isArray(records) ? records : []) {
    const district = safeText(record?.district) || 'Not reported';
    const state = safeText(record?.state) || 'Not reported';
    const key = `${state.toLocaleLowerCase()}::${district.toLocaleLowerCase()}`;
    if (!groups.has(key)) groups.set(key, { district, state, cases: 0, deaths: 0, records: 0, latest: '', source_url: '' });
    const group = groups.get(key);
    group.cases += safeNumber(record?.cases);
    group.deaths += safeNumber(record?.deaths);
    group.records += 1;
    const date = isoDate(record);
    if (date > group.latest) {
      group.latest = date;
      group.source_url = safeText(record?.source_url);
    } else if (!group.source_url && record?.source_url) {
      group.source_url = safeText(record.source_url);
    }
  }
  return [...groups.values()].sort((a, b) => b.cases - a.cases || b.deaths - a.deaths || a.district.localeCompare(b.district));
}

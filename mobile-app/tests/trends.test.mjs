import test from 'node:test';
import assert from 'node:assert/strict';
import { aggregateDistrictTrends, filterTrendRecords, getDistrictReportDetails } from '../src/trends.mjs';

const sample = [
  { district: 'Mysuru', state: 'Karnataka', disease: 'Chickenpox', cases: 51, deaths: 1, reporting_end_date: '2026-03-01', source_url: 'https://example.org/mysuru' },
  { district: 'Mysuru', state: 'Karnataka', disease: 'Chickenpox', cases: 15, deaths: 0, reporting_end_date: '2026-03-08', source_url: 'https://example.org/mysuru-latest' },
  { district: 'Bengaluru Urban', state: 'Karnataka', disease: 'Dengue', cases: 22, deaths: 2, reporting_end_date: '2026-02-28', source_url: 'https://example.org/bengaluru' },
  { district: 'Ernakulam', state: 'Kerala', disease: 'Chickenpox', cases: 6, deaths: 0, reporting_end_date: '2026-03-05' },
];

test('filters by disease case-insensitively', () => {
  assert.equal(filterTrendRecords(sample, { disease: 'chicken' }).length, 3);
});

test('filters by state', () => {
  assert.equal(filterTrendRecords(sample, { state: 'karnataka' }).length, 3);
});

test('filters inclusive date bounds', () => {
  const result = filterTrendRecords(sample, { fromDate: '2026-03-01', toDate: '2026-03-05' });
  assert.deepEqual(result.map((row) => row.district), ['Mysuru', 'Ernakulam']);
});

test('ignores malformed date-filter values instead of excluding every row', () => {
  assert.equal(filterTrendRecords(sample, { fromDate: 'yesterday' }).length, 4);
});

test('aggregates district case counts and sorts highest first', () => {
  const result = aggregateDistrictTrends(sample);
  assert.equal(result[0].district, 'Mysuru');
  assert.equal(result[0].cases, 66);
  assert.equal(result[0].deaths, 1);
  assert.equal(result[0].records, 2);
});

test('uses latest report date and latest matching source', () => {
  const result = aggregateDistrictTrends(sample);
  const mysuru = result.find((row) => row.district === 'Mysuru');
  assert.equal(mysuru.latest, '2026-03-08');
  assert.equal(mysuru.source_url, 'https://example.org/mysuru-latest');
});

test('handles missing, non-array, negative and invalid numbers safely', () => {
  assert.deepEqual(filterTrendRecords(null), []);
  const result = aggregateDistrictTrends([{ district: 'X', state: 'Y', cases: -3, deaths: 'bad' }]);
  assert.equal(result[0].cases, 0);
  assert.equal(result[0].deaths, 0);
  assert.equal(result[0].records, 1);
});


test('returns selected district reports newest first with case-insensitive matching', () => {
  const result = getDistrictReportDetails(sample, 'mysuru', 'KARNATAKA');
  assert.equal(result.length, 2);
  assert.equal(result[0].reporting_end_date, '2026-03-08');
  assert.equal(result[1].reporting_end_date, '2026-03-01');
});

test('district report details return an empty list for invalid inputs or unmatched districts', () => {
  assert.deepEqual(getDistrictReportDetails(null, 'Mysuru', 'Karnataka'), []);
  assert.deepEqual(getDistrictReportDetails(sample, '', 'Karnataka'), []);
  assert.deepEqual(getDistrictReportDetails(sample, 'Mysuru', 'Tamil Nadu'), []);
});

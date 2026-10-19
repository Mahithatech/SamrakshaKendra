import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeStateKey, summarizeLatestStateReports, colorForMapState, normalizeStagingSummary, normalizeReviewerQueue, buildReviewerDecision } from '../src/mobileFullParity.mjs';

test('state aliases line up common desktop map labels and source labels', () => {
  assert.equal(normalizeStateKey('NCT of Delhi'), normalizeStateKey('Delhi'));
  assert.equal(normalizeStateKey('Orissa'), normalizeStateKey('Odisha'));
  assert.equal(normalizeStateKey('Jammu & Kashmir'), normalizeStateKey('Jammu and Kashmir'));
});

test('map snapshot uses only the latest available year-week', () => {
  const s = summarizeLatestStateReports([
    { year: 2026, week: 8, state: 'Karnataka', cases: 400, deaths: 1 },
    { year: 2026, week: 9, state: 'Karnataka', cases: 51, deaths: 0, reporting_end_date: '2026-03-01' },
    { year: 2026, week: 9, state: 'Kerala', cases: 80, deaths: 2 },
  ]);
  assert.equal(s.period.label, '2026-W09');
  assert.equal(s.totalRecords, 2);
  assert.equal(s.statesCount, 2);
  assert.equal(s.totalCases, 131);
  assert.equal(s.states.find(x => x.key === 'karnataka').cases, 51);
});

test('map snapshot preserves unknown values rather than converting them to zero', () => {
  const s = summarizeLatestStateReports([{ year: 2026, week: 9, state: 'Karnataka', cases: null, deaths: '' }]);
  assert.equal(s.totalCases, null);
  assert.equal(s.states[0].cases, null);
  assert.equal(colorForMapState('Karnataka', s).status, 'unknown-count');
});

test('map state distinguishes no-data and historical anomaly candidates', () => {
  const s = summarizeLatestStateReports([{ year: 2026, week: 9, state: 'Karnataka', cases: 51, deaths: 0 }]);
  assert.equal(colorForMapState('Goa', s).status, 'no-data');
  assert.equal(colorForMapState('Karnataka', s, ['Karnataka']).status, 'historical-anomaly-candidate');
});

test('staging summary handles counts and invalid values safely', () => {
  const s = normalizeStagingSummary({ total_records: 29, status_counts: { pending_supervisor_review: 21, approved: 7, rejected: 1, bad: -1 } });
  assert.equal(s.totalRecords, 29);
  assert.equal(s.pending, 21);
  assert.equal(s.statusCounts.bad, 0);
});

test('reviewer queue normalizes malformed payloads', () => {
  assert.deepEqual(normalizeReviewerQueue({ items: [null, {record_id:'r1'}], total: '1', pending_total: 'NaN' }), { items:[{record_id:'r1'}], total:1, pendingTotal:0, note:'Each staged row must be checked against its official source PDF.' });
});

test('review decision requires reviewer and notes for non-approval decisions', () => {
  assert.deepEqual(buildReviewerDecision({record_id:'r1'}, 'approved', 'Review Team'), {record_id:'r1', decision:'approved', reviewer:'Review Team', notes:''});
  assert.throws(() => buildReviewerDecision({record_id:'r1'}, 'rejected', 'Review Team', ''), /review note/);
  assert.throws(() => buildReviewerDecision({record_id:'r1'}, 'approved', ''), /reviewer name/);
});

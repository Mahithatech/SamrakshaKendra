import test from 'node:test';
import assert from 'node:assert/strict';
import { compactPeriodLabel, displayStatValue, prepareIcaSignalData, prepareRankingBars, prepareWeeklyChartPoints, safePageLabel } from '../src/mobileVisuals.mjs';

test('weekly chart data keeps valid recent points and normalizes invalid values', () => {
  assert.deepEqual(prepareWeeklyChartPoints([
    { period: '2026-W01', cases: '12' }, { period: '2026-W02', cases: -3 }, null, { label: 'latest', cases: 'bad' },
  ]), [
    { period: '2026-W01', cases: 12 }, { period: '2026-W02', cases: 0 }, { period: 'latest', cases: 0 },
  ]);
});

test('weekly chart data defaults invalid inputs to empty arrays', () => {
  assert.deepEqual(prepareWeeklyChartPoints(null), []);
  assert.deepEqual(prepareWeeklyChartPoints('bad'), []);
});

test('period labels fit narrow mobile chart columns', () => {
  assert.equal(compactPeriodLabel('2025-W24'), '25-W24');
  assert.equal(compactPeriodLabel('Week labels too long'), 'Week lab…');
});

test('ranked bars sort descending and calculate bounded percentages', () => {
  assert.deepEqual(prepareRankingBars([
    { name: 'small', cases: 5 }, { state: 'large', cases: 10 }, { disease: 'invalid', cases: -2 },
  ]), [
    { name: 'large', value: 10, percent: 100 },
    { name: 'small', value: 5, percent: 50 },
    { name: 'invalid', value: 0, percent: 0 },
  ]);
});

test('ranked bars handle missing/malformed records', () => {
  assert.deepEqual(prepareRankingBars(null), []);
  assert.deepEqual(prepareRankingBars([null, 5, {}, { name: '', value: 'oops' }]), []);
});

test('page label never renders NaN', () => {
  assert.equal(safePageLabel(1, 8), '1/8');
  assert.equal(safePageLabel('bad', NaN), '1/1');
  assert.equal(safePageLabel(4, 2), '2/2');
});

test('stat formatting preserves nonnumeric display strings', () => {
  assert.equal(displayStatValue('1/8'), '1/8');
  assert.equal(displayStatValue('—'), '—');
  assert.equal(displayStatValue(undefined), '—');
  assert.equal(displayStatValue(7133), '7,133');
});


test('ICA signal helper keeps recent periods, finite values and component names', () => {
  const result = prepareIcaSignalData([
    { period: 'W1', IC1: 0.5, IC2: -1 },
    { period: 'W2', IC1: 'bad', IC2: 2 },
    null,
  ]);
  assert.deepEqual(result.components, ['IC1', 'IC2']);
  assert.equal(result.periods.length, 2);
  assert.deepEqual(result.periods[1].values, [{ component: 'IC1', value: 0 }, { component: 'IC2', value: 2 }]);
  assert.equal(result.maxAbs, 2);
});

test('ICA chart data handles empty input', () => {
  assert.deepEqual(prepareIcaSignalData(null), { components: [], periods: [], maxAbs: 1 });
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildHistoryQuery, apiToWebSocketUrl, isSessionRejectedMessage,
  normalizeFeed, normalizePagedRecords, SNAPSHOT_REFRESH_MS,
  OFFICIAL_FEED_REFRESH_MS, SOCKET_HEARTBEAT_MS, SOCKET_RETRY_MS,
} from '../src/mobileParity.mjs';

test('historical query filters whitespace and encodes values', () => {
  assert.equal(buildHistoryQuery({ state: ' Karnataka ', district: 'Bengaluru Urban', disease: '', year: '2026' }, 2, 30), 'state=Karnataka&district=Bengaluru+Urban&year=2026&page=2&page_size=30');
});
test('historical CSV query omits pagination when unspecified', () => {
  assert.equal(buildHistoryQuery({ disease: 'Chickenpox' }), 'disease=Chickenpox');
});
test('empty historical query does not create fake filters', () => {
  assert.equal(buildHistoryQuery({}), '');
});
test('HTTP backend URL converts to websocket alert URL', () => {
  assert.equal(apiToWebSocketUrl('https://samraksha-kendra-api.onrender.com/'), 'wss://samraksha-kendra-api.onrender.com/ws/alerts');
  assert.equal(apiToWebSocketUrl('http://127.0.0.1:8000'), 'ws://127.0.0.1:8000/ws/alerts');
});
test('invalid websocket URL protocols are rejected', () => {
  assert.throws(() => apiToWebSocketUrl('file:///tmp/api'), /HTTP or HTTPS/);
});
test('session rejection recognises middleware auth failures', () => {
  assert.equal(isSessionRejectedMessage('Authentication required. Sign in to continue.'), true);
  assert.equal(isSessionRejectedMessage('Invalid or expired session'), true);
  assert.equal(isSessionRejectedMessage('Request failed (HTTP 401).'), true);
  assert.equal(isSessionRejectedMessage('Network request failed'), false);
});
test('feed normalization handles missing and malformed payloads safely', () => {
  assert.deepEqual(normalizeFeed(null), { status: 'unknown', count: 0, items: [], lastCheckedAt: null, lastSuccessfulFetchAt: null, warning: '', sourceError: '' });
  assert.equal(normalizeFeed({ count: -2, items: [null, 'bad', { title: 'X' }] }).count, 0);
  assert.equal(normalizeFeed({ items: [null, 'bad', { title: 'X' }] }).items.length, 1);
});
test('paged records normalize missing fields and preserve valid items', () => {
  assert.deepEqual(normalizePagedRecords({ items: [{ id: 1 }, null], total: 4, pages: 2 }), { items: [{ id: 1 }], total: 4, pages: 2 });
  assert.deepEqual(normalizePagedRecords({ items: 'bad' }), { items: [], total: 0, pages: 1 });
});
test('mobile refresh intervals are bounded and source-aware', () => {
  assert.equal(SNAPSHOT_REFRESH_MS, 60_000);
  assert.equal(OFFICIAL_FEED_REFRESH_MS, 900_000);
  assert.equal(SOCKET_HEARTBEAT_MS, 25_000);
  assert.equal(SOCKET_RETRY_MS, 4_000);
});

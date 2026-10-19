import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_API_BASE_URL,
  normalizeApiBase,
  normalizeQuestion,
  buildAssistantRequest,
  parseSummary,
  parseSourceStatus,
  requestJSON,
  extractAccessToken,
} from '../src/api.mjs';

test('default API URL is the deployed Samraksha Kendra backend', () => {
  assert.equal(normalizeApiBase(), DEFAULT_API_BASE_URL);
});

test('normalizes trailing slash and rejects credentials embedded in URL', () => {
  assert.equal(normalizeApiBase('https://example.test///'), 'https://example.test');
  assert.throws(() => normalizeApiBase('https://user:pass@example.test'), /credentials/);
  assert.throws(() => normalizeApiBase('file:///tmp/api'), /HTTP or HTTPS/);
});

test('trims questions without requiring a question mark', () => {
  assert.equal(normalizeQuestion('  total cases in Karnataka  '), 'total cases in Karnataka');
  assert.equal(normalizeQuestion('hi'), 'hi');
  assert.throws(() => normalizeQuestion('   '), /1 and 400/);
  assert.throws(() => normalizeQuestion('x'.repeat(401)), /1 and 400/);
});

test('assistant request accepts supported language and defaults unknown language to English', () => {
  assert.deepEqual(buildAssistantRequest(' top diseases ', 'te'), { question: 'top diseases', language: 'te' });
  assert.deepEqual(buildAssistantRequest('top diseases', 'xx'), { question: 'top diseases', language: 'en' });
});

test('summary parser handles expected values and missing/invalid fields safely', () => {
  assert.deepEqual(parseSummary({ total_records: 246, total_cases: '7133', total_deaths: 24, states_count: 26, diseases_count: 36, weekly_trend: [{ week: 1 }] }), {
    records: 246, cases: 7133, deaths: 24, states: 26, diseases: 36, weeklyTrend: [{ week: 1 }],
  });
  assert.deepEqual(parseSummary({ total_cases: -4, total_deaths: 'bad' }), {
    records: 0, cases: 0, deaths: 0, states: 0, diseases: 0, weeklyTrend: [],
  });
});

test('source status parser ignores malformed entries', () => {
  assert.deepEqual(parseSourceStatus({ sources: [{ name: 'WHO' }, null, {}, { name: 'NCDC' }] }), [{ name: 'WHO' }, { name: 'NCDC' }]);
  assert.deepEqual(parseSourceStatus({ sources: 'not an array' }), []);
});

test('requestJSON posts JSON and parses structured response', async () => {
  let captured;
  const fakeFetch = async (url, init) => {
    captured = { url, init };
    return { ok: true, status: 200, text: async () => JSON.stringify({ answer: 'ok' }) };
  };
  const result = await requestJSON('/public/assistant/query', { method: 'POST', body: { question: 'top diseases' } }, fakeFetch, 'https://api.example.test/');
  assert.deepEqual(result, { answer: 'ok' });
  assert.equal(captured.url, 'https://api.example.test/public/assistant/query');
  assert.equal(captured.init.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(captured.init.body), { question: 'top diseases' });
});

test('requestJSON surfaces server validation errors without credentials', async () => {
  const fakeFetch = async () => ({ ok: false, status: 422, text: async () => JSON.stringify({ detail: 'Question must contain 3–400 characters.' }) });
  await assert.rejects(() => requestJSON('/public/assistant/query', { method: 'POST', body: {} }, fakeFetch), /Question must contain/);
});


test('extracts an access token from supported login response fields', () => {
  assert.equal(extractAccessToken({ access_token: 'abc' }), 'abc');
  assert.equal(extractAccessToken({ token: 'xyz' }), 'xyz');
  assert.equal(extractAccessToken({ accessToken: 'def' }), 'def');
  assert.throws(() => extractAccessToken({}), /did not include an access token/);
});

test('requestJSON sends bearer token only when supplied', async () => {
  let captured;
  const fakeFetch = async (url, init) => {
    captured = { url, init };
    return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true }) };
  };
  await requestJSON('/hospitals/count', { token: 'secure-token' }, fakeFetch, 'https://api.example.test');
  assert.equal(captured.init.headers.Authorization, 'Bearer secure-token');
  await requestJSON('/auth/login', { method: 'POST', body: { username: 'u', password: 'p' } }, fakeFetch, 'https://api.example.test');
  assert.equal(captured.init.headers.Authorization, undefined);
});

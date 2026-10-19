export const DEFAULT_API_BASE_URL = 'https://samraksha-kendra-api.onrender.com';
export const SUPPORTED_LANGUAGES = new Set(['en', 'te', 'kn', 'hi']);

export function normalizeApiBase(value = DEFAULT_API_BASE_URL) {
  const candidate = String(value || DEFAULT_API_BASE_URL).trim().replace(/\/+$/, '');
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error('API base URL must be a valid absolute URL.');
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('API base URL must use HTTP or HTTPS.');
  }
  if (parsed.username || parsed.password) {
    throw new Error('Do not embed credentials in the API base URL.');
  }
  return candidate;
}

export function normalizeQuestion(value) {
  const question = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (question.length < 1 || question.length > 400) {
    throw new Error('Enter a question between 1 and 400 characters.');
  }
  return question;
}

export function buildAssistantRequest(question, language = 'en') {
  const cleanQuestion = normalizeQuestion(question);
  const cleanLanguage = SUPPORTED_LANGUAGES.has(language) ? language : 'en';
  return { question: cleanQuestion, language: cleanLanguage };
}

export function parseSummary(payload = {}) {
  const number = (value) => {
    const parsed = Number(value ?? 0);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
  };
  return {
    records: number(payload.total_records),
    cases: number(payload.total_cases),
    deaths: number(payload.total_deaths),
    states: number(payload.states_count),
    diseases: number(payload.diseases_count),
    weeklyTrend: Array.isArray(payload.weekly_trend) ? payload.weekly_trend : [],
  };
}

export function parseSourceStatus(payload = {}) {
  return Array.isArray(payload.sources) ? payload.sources.filter((source) =>
    source && typeof source.name === 'string'
  ) : [];
}

export async function requestJSON(path, options = {}, fetchImpl = globalThis.fetch, baseUrl = DEFAULT_API_BASE_URL) {
  if (typeof fetchImpl !== 'function') throw new Error('Fetch is not available in this runtime.');
  const base = normalizeApiBase(baseUrl);
  const method = String(options.method || 'GET').toUpperCase();
  const headers = { Accept: 'application/json', ...(options.headers || {}) };
  const init = { method, headers };
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(options.body);
  }
  const response = await fetchImpl(`${base}${path.startsWith('/') ? path : `/${path}`}`, init);
  const raw = await response.text();
  let data = {};
  if (raw) {
    try { data = JSON.parse(raw); }
    catch { throw new Error(`Server returned invalid JSON (HTTP ${response.status}).`); }
  }
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : `Request failed (HTTP ${response.status}).`;
    throw new Error(detail);
  }
  return data;
}

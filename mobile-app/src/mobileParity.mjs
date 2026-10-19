export const SNAPSHOT_REFRESH_MS = 60_000;
export const OFFICIAL_FEED_REFRESH_MS = 15 * 60_000;
export const SOCKET_HEARTBEAT_MS = 25_000;
export const SOCKET_RETRY_MS = 4_000;

export function buildHistoryQuery(filters = {}, page = null, pageSize = null) {
  const params = new URLSearchParams();
  for (const key of ['state', 'district', 'disease', 'year']) {
    const value = String(filters?.[key] ?? '').trim();
    if (value) params.set(key, value);
  }
  if (Number.isInteger(page) && page > 0) params.set('page', String(page));
  if (Number.isInteger(pageSize) && pageSize > 0) params.set('page_size', String(pageSize));
  return params.toString();
}

export function apiToWebSocketUrl(apiBase) {
  const base = String(apiBase || '').trim().replace(/\/$/, '');
  if (!/^https?:\/\//i.test(base)) throw new Error('API URL must use HTTP or HTTPS.');
  return `${base.replace(/^http/i, 'ws')}/ws/alerts`;
}

export function isSessionRejectedMessage(message) {
  return /authentication required|invalid or expired session|session was rejected|\b401\b/i.test(String(message || ''));
}

export function normalizeFeed(payload) {
  return {
    status: typeof payload?.status === 'string' ? payload.status : 'unknown',
    count: Math.max(0, Number(payload?.count) || 0),
    items: Array.isArray(payload?.items) ? payload.items.filter((item) => item && typeof item === 'object') : [],
    lastCheckedAt: payload?.last_checked_at || null,
    lastSuccessfulFetchAt: payload?.last_successful_fetch_at || null,
    warning: typeof payload?.warning === 'string' ? payload.warning : '',
    sourceError: typeof payload?.source_error === 'string' ? payload.source_error : '',
  };
}

export function normalizePagedRecords(payload) {
  const items = Array.isArray(payload?.items) ? payload.items.filter((item) => item && typeof item === 'object') : [];
  const total = Math.max(0, Number(payload?.total) || 0);
  const pages = Math.max(1, Number(payload?.pages) || Math.ceil(total / 30) || 1);
  return { items, total, pages };
}

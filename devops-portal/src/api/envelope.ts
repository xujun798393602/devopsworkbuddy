/**
 * Transport envelope + optimistic-concurrency conventions shared by every
 * domain API module.
 *
 * Every rule below was verified against the REAL backend sources, not against
 * the OpenAPI contract or the architecture document:
 *
 *  1. `api<T>(path, init)` (src/api/client.ts) passes `path` to `fetch`
 *     verbatim — it does NOT prepend `/bff/api`. Always pass the full
 *     browser path, e.g. `/bff/api/v1/projects/{pid}/defects`.
 *  2. EVERY response — list *and* single resource — is wrapped in
 *     `{ data, meta }`:
 *       - project list          → `{ data: Project[],           meta }`
 *       - project detail        → `{ data: Project,             meta }`
 *       - requirement/defect/test-case/test-plan list
 *                               → `{ data: { items: T[] }, meta: { next_cursor, has_more } }`
 *       - any single resource   → `{ data: T,                   meta }`
 *  3. The gateway rebuilds every proxied response with `jsonify(body)`
 *     (devops-api-gateway/src/gateway/app.py `proxy`), so the upstream `ETag`
 *     response header is DROPPED before it reaches the browser. `api()` also
 *     discards response headers. The concurrency token must therefore be read
 *     from the response body field `data.version`.
 *  4. Every upstream compares the request header literally against
 *     `f'"{resource.version}"'` (td/requirement/tp `app.py`), so `If-Match`
 *     MUST include the surrounding double quotes: `If-Match: "3"`.
 *     A bare `3` is answered with 412 PRECONDITION_FAILED.
 *  5. `content-type`, `idempotency-key`, `if-match` and `x-trace-id` are the
 *     ONLY request headers the gateway forwards upstream
 *     (`proxy_headers` allow-list). Anything else is silently dropped.
 */

/** Response `meta` block; individual services populate different subsets. */
export interface ResponseMeta {
  trace_id?: string;
  next_cursor?: string | null;
  has_more?: boolean;
  count?: number;
}

/** `{ data, meta }` wrapper used by every endpoint, including single resources. */
export interface Envelope<T> {
  data: T;
  meta?: ResponseMeta;
}

/** Cursor-paginated list wrapper: `{ data: { items }, meta: { next_cursor, has_more } }`. */
export interface ListEnvelope<T> {
  data: { items: T[] };
  meta: { next_cursor: string | null; has_more: boolean; trace_id?: string };
}

/** Normalised page shape every list API function returns. */
export interface PageResult<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

/** Query for opaque-cursor pagination (requirements / defects / test-cases / test-plans). */
export interface CursorQuery {
  cursor?: string | null;
  limit?: number;
}

/** Query for offset pagination (`after` + `limit`, e.g. project tasks). */
export interface OffsetQuery {
  after?: number | null;
  limit?: number;
}

/**
 * An `If-Match` token, already quoted and ready to be used as a header value.
 *
 * Always produced by {@link formatIfMatch} so callers never have to remember
 * the quoting rule.
 */
export type ETag = string;

/**
 * Build the exact `If-Match` header value the backends expect.
 *
 * The upstreams compare the raw header against `"<version>"`, quotes included.
 * Accepts a bare version (`3`, `'3'`) or an already-quoted token (`'"3"'`) so
 * that re-formatting an ETag is idempotent.
 */
export function formatIfMatch(version: number | string): ETag {
  const raw = String(version).trim();
  if (raw.startsWith('"') && raw.endsWith('"') && raw.length >= 3) {
    return raw;
  }
  return `"${raw.replace(/^"|"$/g, '')}"`;
}

/** Headers for a mutating request that carries an optimistic-concurrency token. */
export function ifMatchHeaders(etag: number | string): Record<string, string> {
  return { 'If-Match': formatIfMatch(etag) };
}

/** Headers for an idempotent create/transition request. */
export function idempotencyHeaders(key: string): Record<string, string> {
  return { 'Idempotency-Key': key };
}

/** Flatten a `ListEnvelope` into the normalised {@link PageResult} shape. */
export function toPage<T>(response: ListEnvelope<T>): PageResult<T> {
  return {
    items: response?.data?.items ?? [],
    next_cursor: response?.meta?.next_cursor ?? null,
    has_more: response?.meta?.has_more ?? false,
  };
}

/**
 * Serialise a cursor query into a `?limit=&cursor=` suffix.
 *
 * Empty/absent values are omitted so the backend applies its own defaults
 * (`parse_portal_limit` rejects an empty `limit` string with 422).
 */
export function cursorSearch(query: CursorQuery = {}): string {
  const params = new URLSearchParams();
  if (query.limit !== undefined && query.limit !== null) {
    params.set('limit', String(query.limit));
  }
  if (query.cursor) {
    params.set('cursor', query.cursor);
  }
  const search = params.toString();
  return search ? `?${search}` : '';
}

/** Serialise an offset query into a `?limit=&after=` suffix. */
export function offsetSearch(query: OffsetQuery = {}): string {
  const params = new URLSearchParams();
  if (query.limit !== undefined && query.limit !== null) {
    params.set('limit', String(query.limit));
  }
  if (query.after !== undefined && query.after !== null) {
    params.set('after', String(query.after));
  }
  const search = params.toString();
  return search ? `?${search}` : '';
}

/** Base path for every project-scoped v1 resource, including the `/bff/api` prefix. */
export function projectPath(projectId: string, suffix = ''): string {
  return `/bff/api/v1/projects/${projectId}${suffix}`;
}

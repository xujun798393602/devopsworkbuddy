/**
 * Cursor-paginated list composable (requirements / defects / test-cases / plans).
 *
 * The backend returns an opaque-cursor envelope `{ data:{items}, meta:{next_cursor, has_more} }`.
 * This composable owns the `items` accumulator, the `loading`/`error` flags and the
 * `reload()` / `loadMore()` controls, and is transport-agnostic: the caller supplies a
 * `loader(cursor, limit)` that returns the `ListEnvelope`. Components wire it to the
 * relevant `api/*` function; tests supply a stub loader (so `api` stays mocked).
 */
import { ref, type Ref } from 'vue';
import type { ListEnvelope } from '../api/envelope';

/** Options for {@link useCursorPage}. */
export interface CursorPageOptions<T> {
  /** Fetch one page. Receives the opaque cursor (`null` for the first page). */
  loader: (cursor: string | null, limit: number) => Promise<ListEnvelope<T>>;
  /** Page size. Defaults to 20. */
  limit?: number;
  /** Auto-load the first page on creation. Defaults to `true`. */
  immediate?: boolean;
}

/** Returned reactive handles for {@link useCursorPage}. */
export interface UseCursorPage<T> {
  items: Ref<T[]>;
  loading: Ref<boolean>;
  error: Ref<Error | null>;
  hasMore: Ref<boolean>;
  nextCursor: Ref<string | null>;
  /** Reset and fetch the first page. */
  reload: () => Promise<void>;
  /** Append the next page when `hasMore` is true. */
  loadMore: () => Promise<void>;
}

/**
 * Manage an opaque-cursor list. `reload()` replaces the list; `loadMore()` appends.
 * On failure the error is captured (and re-thrown) so callers can react.
 */
export function useCursorPage<T>(options: CursorPageOptions<T>): UseCursorPage<T> {
  const limit = options.limit ?? 20;
  const items = ref<T[]>([]) as Ref<T[]>;
  const loading = ref(false);
  const error = ref<Error | null>(null);
  const hasMore = ref(false);
  const nextCursor = ref<string | null>(null);

  async function fetchPage(cursor: string | null, append: boolean): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const response = await options.loader(cursor, limit);
      const pageItems = response?.data?.items ?? [];
      items.value = append ? [...items.value, ...pageItems] : pageItems;
      nextCursor.value = response?.meta?.next_cursor ?? null;
      hasMore.value = response?.meta?.has_more ?? false;
    } catch (e) {
      // Capture the error for the caller (AsyncSection etc.); do NOT rethrow so the
      // fire-and-forget immediate load cannot produce an unhandled rejection.
      error.value = e instanceof Error ? e : new Error(String(e));
    } finally {
      loading.value = false;
    }
  }

  function reload(): Promise<void> {
    nextCursor.value = null;
    return fetchPage(null, false);
  }

  function loadMore(): Promise<void> {
    if (loading.value || !hasMore.value) return Promise.resolve();
    return fetchPage(nextCursor.value, true);
  }

  if (options.immediate ?? true) {
    void reload();
  }

  return { items, loading, error, hasMore, nextCursor, reload, loadMore };
}

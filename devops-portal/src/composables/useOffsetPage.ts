/**
 * Offset-paginated list composable (project tasks, and any `after`+`limit` feed).
 *
 * Unlike the cursor envelope, offset feeds return `{ data: T[], meta? }` (the array
 * lives directly under `data`). `after` is derived from the number of items already
 * loaded, so `loadMore()` keeps fetching the next slice until `has_more` is false (or,
 * when the upstream omits `meta.has_more`, until a short page is returned).
 *
 * Transport-agnostic: the caller supplies `loader(after, limit)`; tests use a stub.
 */
import { ref, type Ref } from 'vue';

/** An offset page envelope: the array sits directly under `data`. */
export interface OffsetEnvelope<T> {
  data: T[];
  meta?: { count?: number; has_more?: boolean };
}

/** Options for {@link useOffsetPage}. */
export interface OffsetPageOptions<T> {
  loader: (after: number, limit: number) => Promise<OffsetEnvelope<T>>;
  limit?: number;
  immediate?: boolean;
}

/** Returned reactive handles for {@link useOffsetPage}. */
export interface UseOffsetPage<T> {
  items: Ref<T[]>;
  loading: Ref<boolean>;
  error: Ref<Error | null>;
  hasMore: Ref<boolean>;
  total: Ref<number | null>;
  reload: () => Promise<void>;
  loadMore: () => Promise<void>;
}

/** Manage an offset list keyed by `after = items.length`. */
export function useOffsetPage<T>(options: OffsetPageOptions<T>): UseOffsetPage<T> {
  const limit = options.limit ?? 50;
  const items = ref<T[]>([]) as Ref<T[]>;
  const loading = ref(false);
  const error = ref<Error | null>(null);
  const hasMore = ref(true);
  const total = ref<number | null>(null);

  async function fetchPage(after: number, append: boolean): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const response = await options.loader(after, limit);
      const page = response?.data ?? [];
      items.value = append ? [...items.value, ...page] : page;
      if (typeof response?.meta?.count === 'number') {
        total.value = response.meta.count;
      }
      const explicit = response?.meta?.has_more;
      hasMore.value = explicit === undefined ? page.length >= limit : explicit;
    } catch (e) {
      error.value = e instanceof Error ? e : new Error(String(e));
    } finally {
      loading.value = false;
    }
  }

  function reload(): Promise<void> {
    return fetchPage(0, false);
  }

  function loadMore(): Promise<void> {
    if (loading.value || !hasMore.value) return Promise.resolve();
    return fetchPage(items.value.length, true);
  }

  if (options.immediate ?? true) {
    void reload();
  }

  return { items, loading, error, hasMore, total, reload, loadMore };
}

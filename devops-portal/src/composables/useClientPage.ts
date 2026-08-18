/**
 * Client-side pager over an already-loaded in-memory array.
 *
 * Some lists are fetched once (e.g. a small project collection) and only need to be
 * sliced for an "infinite scroll" UX. This composable exposes the SAME surface as the
 * cursor/offset pagers (`items`, `hasMore`, `reload`, `loadMore`) so call sites stay
 * uniform, but it operates purely on a `Ref<T[]>` / getter with no network calls.
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue';

/** Options for {@link useClientPage}. */
export interface ClientPageOptions<T> {
  /** The full, already-loaded array (reactive ref or a getter). */
  source: Ref<T[]> | (() => T[]);
  limit?: number;
}

/** Returned reactive handles for {@link useClientPage}. */
export interface UseClientPage<T> {
  items: ComputedRef<T[]>;
  loading: Ref<boolean>;
  error: Ref<Error | null>;
  hasMore: ComputedRef<boolean>;
  reload: () => void;
  loadMore: () => void;
}

/** Slice a client array into a growing window. */
export function useClientPage<T>(options: ClientPageOptions<T>): UseClientPage<T> {
  const limit = options.limit ?? 20;
  const offset = ref(limit);
  const loading = ref(false);
  const error = ref<Error | null>(null);

  const resolve = (): T[] =>
    typeof options.source === 'function'
      ? (options.source as () => T[])()
      : options.source.value;

  const items = computed<T[]>(() => resolve().slice(0, offset.value));
  const hasMore = computed<boolean>(() => offset.value < resolve().length);

  function reload(): void {
    offset.value = limit;
    error.value = null;
  }

  function loadMore(): void {
    offset.value += limit;
  }

  reload();

  return { items, loading, error, hasMore, reload, loadMore };
}

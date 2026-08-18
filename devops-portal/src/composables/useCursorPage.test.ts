import { flushPromises } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { useCursorPage } from './useCursorPage';
import type { ListEnvelope } from '../api/envelope';

function makeEnvelope<T>(
  items: T[],
  hasMore: boolean,
  nextCursor: string | null,
): ListEnvelope<T> {
  return { data: { items }, meta: { next_cursor: nextCursor, has_more: hasMore, trace_id: 't' } };
}

describe('useCursorPage', () => {
  it('loads the first page on creation and exposes items', async () => {
    const loader = vi.fn(async () => makeEnvelope([{ id: '1' }, { id: '2' }], false, null));
    const page = useCursorPage<{ id: string }>({ loader });

    expect(page.loading.value).toBe(true);
    await flushPromises();

    expect(loader).toHaveBeenCalledTimes(1);
    expect(page.items.value).toEqual([{ id: '1' }, { id: '2' }]);
    expect(page.hasMore.value).toBe(false);
    expect(page.loading.value).toBe(false);
  });

  it('loadMore appends the next page and advances the cursor', async () => {
    const loader = vi.fn(async (cursor: string | null) =>
      cursor === null
        ? makeEnvelope([{ id: '1' }], true, 'c2')
        : makeEnvelope([{ id: '2' }], false, null),
    );
    const page = useCursorPage<{ id: string }>({ loader, limit: 20 });

    await page.reload();
    expect(page.items.value).toEqual([{ id: '1' }]);
    expect(page.hasMore.value).toBe(true);

    await page.loadMore();
    expect(loader).toHaveBeenLastCalledWith('c2', 20);
    expect(page.items.value).toEqual([{ id: '1' }, { id: '2' }]);
  });

  it('does not call loadMore again once hasMore is false', async () => {
    const loader = vi.fn(async () => makeEnvelope([{ id: '1' }], false, null));
    const page = useCursorPage<{ id: string }>({ loader, immediate: false });

    await page.reload();
    await page.loadMore(); // no-op because !hasMore

    expect(loader).toHaveBeenCalledTimes(1);
  });

  it('captures loader errors on the reactive error flag', async () => {
    const loader = vi.fn(async () => {
      throw new Error('boom');
    });
    const page = useCursorPage<{ id: string }>({ loader });

    await flushPromises();

    expect(page.error.value?.message).toBe('boom');
    expect(page.items.value).toEqual([]);
    expect(page.loading.value).toBe(false);
  });
});

import { flushPromises } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { useOffsetPage } from './useOffsetPage';
import type { OffsetEnvelope } from './useOffsetPage';

function makeOffset<T>(items: T[], hasMore?: boolean, count?: number): OffsetEnvelope<T> {
  return { data: items, meta: { has_more: hasMore, count } };
}

describe('useOffsetPage', () => {
  it('loads the first page with after=0 and exposes items', async () => {
    const loader = vi.fn(async (after: number, limit: number) => makeOffset([after, after + limit]));
    const page = useOffsetPage<number>({ loader, limit: 2 });

    await flushPromises();

    expect(loader).toHaveBeenCalledWith(0, 2);
    expect(page.items.value).toEqual([0, 2]);
    expect(page.total.value).toBeNull();
  });

  it('loadMore appends and advances `after` by the current length', async () => {
    const loader = vi.fn(async (after: number) => makeOffset([after, after + 1, after + 2], true));
    const page = useOffsetPage<number>({ loader, limit: 3 });

    await page.reload();
    expect(page.items.value).toEqual([0, 1, 2]);
    expect(page.hasMore.value).toBe(true);

    await page.loadMore();
    expect(loader).toHaveBeenLastCalledWith(3, 3);
    expect(page.items.value).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it('honours meta.has_more when the upstream provides it', async () => {
    const loader = vi.fn(async () => makeOffset([1, 2], false));
    const page = useOffsetPage<number>({ loader });

    await page.reload();
    expect(page.hasMore.value).toBe(false);
  });

  it('captures loader errors without throwing and keeps items empty', async () => {
    const loader = vi.fn(async () => {
      throw new Error('nope');
    });
    const page = useOffsetPage<number>({ loader });

    await page.reload();

    expect(page.error.value?.message).toBe('nope');
    expect(page.items.value).toEqual([]);
  });
});

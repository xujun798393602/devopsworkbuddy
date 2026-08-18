import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';

import DashboardCard from './DashboardCard.vue';

const SLOT = { default: '<p class="payload">real content</p>' };

describe('DashboardCard', () => {
  it('renders the default slot in the ready state', () => {
    const wrapper = mount(DashboardCard, { props: { title: '测试统计' }, slots: SLOT });

    expect(wrapper.find('.dcard__title').text()).toBe('测试统计');
    expect(wrapper.find('.payload').exists()).toBe(true);
    expect(wrapper.attributes('aria-busy')).toBe('false');
    expect(wrapper.find('.dcard__badge').exists()).toBe(false);
  });

  it('shows a skeleton and hides content while loading', () => {
    const wrapper = mount(DashboardCard, { props: { title: 'x', loading: true }, slots: SLOT });

    expect(wrapper.find('.dcard__skeleton').exists()).toBe(true);
    expect(wrapper.find('.payload').exists()).toBe(false);
    expect(wrapper.attributes('aria-busy')).toBe('true');
  });

  it('shows the guided empty state instead of content', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'x', empty: true, emptyText: '你还没有参与任何项目' },
      slots: SLOT,
    });

    expect(wrapper.find('.dcard__empty').text()).toBe('你还没有参与任何项目');
    expect(wrapper.find('.payload').exists()).toBe(false);
  });

  it('falls back to a retry affordance when the domain is degraded', async () => {
    const wrapper = mount(DashboardCard, { props: { title: 'x', degraded: true }, slots: SLOT });

    expect(wrapper.classes()).toContain('dcard--degraded');
    expect(wrapper.find('.dcard__badge').text()).toBe('降级');
    expect(wrapper.find('.dcard__fallback-text').text()).toBe('该模块数据暂不可用');
    expect(wrapper.find('.payload').exists()).toBe(false);

    await wrapper.find('.dcard__retry').trigger('click');
    expect(wrapper.emitted('retry')).toHaveLength(1);
  });

  it('prefers the empty state over the degraded fallback but keeps the badge', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'x', empty: true, degraded: true },
      slots: SLOT,
    });

    expect(wrapper.find('.dcard__empty').exists()).toBe(true);
    expect(wrapper.find('.dcard__fallback').exists()).toBe(false);
    expect(wrapper.find('.dcard__badge').text()).toBe('降级');
  });
});

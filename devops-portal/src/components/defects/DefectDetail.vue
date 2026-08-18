<script setup lang="ts">
/**
 * DefectDetail — read-only defect inspector with the workflow timeline.
 *
 * Opens only when `modelValue` flips true; it then fetches the full defect plus its
 * history (`getDefect` + `getDefectHistory`). The history rows use `from`/`to` status
 * values (NOT `from_status`/`to_status`) — see src/api/types/defect.ts and
 * td_service/app.py `get_history`. Mounting with the dialog closed performs no network
 * call, so embedding it in a list is cheap.
 */
import { ref, watch } from 'vue';
import { getDefect, getDefectHistory } from '../../api/defects';
import type { Defect, DefectHistoryEntry } from '../../api/types/defect';
import AsyncSection from '../common/AsyncSection.vue';
import StatusChip from '../common/StatusChip.vue';

const props = defineProps<{ modelValue: boolean; projectId: string; defect: Defect | null }>();
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>();

const detail = ref<Defect | null>(null);
const history = ref<DefectHistoryEntry[]>([]);
const loading = ref(false);
const error = ref<Error | null>(null);

async function load(): Promise<void> {
  if (!props.defect) return;
  loading.value = true;
  error.value = null;
  try {
    const [d, h] = await Promise.all([
      getDefect(props.projectId, props.defect.id),
      getDefectHistory(props.projectId, props.defect.id),
    ]);
    detail.value = d;
    history.value = h;
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      detail.value = props.defect;
      history.value = [];
      void load();
    }
  },
);
</script>

<template>
  <v-dialog
    :model-value="props.modelValue"
    max-width="720"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <v-card>
      <v-card-title v-if="detail">{{ detail.business_no }} · {{ detail.title }}</v-card-title>
      <v-card-text>
        <AsyncSection :loading="loading" :error="error">
          <template v-if="detail">
            <div class="defect-detail__meta">
              <StatusChip :status="detail.status" />
              <span>严重度：{{ detail.severity }}</span>
              <span>优先级：{{ detail.priority }}</span>
              <span>类型：{{ detail.defect_type }}</span>
              <span>负责人：{{ detail.assignee_id ?? '—' }}</span>
            </div>
            <p class="defect-detail__desc">{{ detail.description || '（无描述）' }}</p>

            <h4 class="mt-3">流转历史</h4>
            <v-timeline v-if="history.length" density="compact" side="end">
              <v-timeline-item v-for="h in history" :key="h.sequence_no">
                <div>
                  <strong>{{ h.action }}</strong>
                  <span class="defect-detail__status">（{{ h.from }} → {{ h.to }}）</span>
                  <div v-if="h.reason" class="text-caption">原因：{{ h.reason }}</div>
                </div>
              </v-timeline-item>
            </v-timeline>
            <p v-else class="text-caption">暂无流转记录</p>
          </template>
        </AsyncSection>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="emit('update:modelValue', false)">关闭</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

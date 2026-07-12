<template>
  <div>
    <div v-if="!items.length" class="empty-state">
      <p class="muted" style="margin: 0">No habits yet. Create one in the bot.</p>
    </div>
    <ul v-else class="habit-list">
      <li v-for="item in items" :key="item.habit_id" class="habit-row">
        <div class="habit-head">
          <span class="habit-title">{{ item.title || "Untitled" }}</span>
          <span class="muted">
            {{ item.completed }}/{{ item.total }} · {{ item.completion_rate }}%
          </span>
        </div>
        <div class="bar-track" aria-hidden="true">
          <div
            class="bar-fill"
            :style="{ width: barWidth(item.completion_rate) }"
          />
        </div>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import type { HabitBreakdownItem } from "@/api/stats"

defineProps<{
  items: HabitBreakdownItem[]
}>()

function barWidth(rate: number): string {
  const n = Number.isFinite(rate) ? Math.max(0, Math.min(100, rate)) : 0
  return `${n}%`
}
</script>

<style scoped>
.habit-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.85rem;
}

.habit-row {
  display: grid;
  gap: 0.35rem;
}

.habit-head {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  font-size: 0.95rem;
}

.habit-title {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bar-track {
  height: 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #3d8bfd, #7fd99a);
  min-width: 0;
  transition: width 0.25s ease;
}

.empty-state {
  min-height: 100px;
  display: grid;
  place-items: center;
  border: 1px dashed var(--border);
  border-radius: 12px;
  background: var(--accent-soft);
}
</style>

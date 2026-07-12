<template>
  <div>
    <div v-if="!items.length" class="empty-state">
      <p class="muted" style="margin: 0">
        {{ t("schedule.empty", lang) }}
      </p>
    </div>
    <div v-else class="days">
      <section v-for="group in groups" :key="group.date" class="day-group">
        <h3 class="day-title">{{ group.date }}</h3>
        <ul class="task-list">
          <li
            v-for="task in group.tasks"
            :key="task.id"
            class="task-row"
            :class="{ done: task.is_completed }"
          >
            <span class="time">
              {{ task.start_time
              }}<template v-if="task.end_time">–{{ task.end_time }}</template>
            </span>
            <span class="title">{{
              task.title || t("schedule.untitled", lang)
            }}</span>
            <span class="badge" :class="task.is_completed ? 'ok' : 'pending'">
              {{
                task.is_completed
                  ? t("schedule.done", lang)
                  : t("schedule.open", lang)
              }}
            </span>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import type { ScheduleItem } from "@/api/stats"
import { t, type Lang } from "@/i18n"

const props = withDefaults(
  defineProps<{
    items: ScheduleItem[]
    lang?: Lang
  }>(),
  {
    lang: "ru",
  },
)

type DayGroup = { date: string; tasks: ScheduleItem[] }

const groups = computed((): DayGroup[] => {
  const map = new Map<string, ScheduleItem[]>()
  for (const item of props.items ?? []) {
    if (!item) continue
    const key = item.date || "unknown"
    const list = map.get(key) ?? []
    list.push(item)
    map.set(key, list)
  }
  return Array.from(map.entries()).map(([date, tasks]) => ({ date, tasks }))
})
</script>

<style scoped>
.days {
  display: grid;
  gap: 1rem;
}

.day-title {
  margin: 0 0 0.45rem;
  font-size: 0.9rem;
  color: var(--muted);
  font-weight: 600;
}

.task-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.4rem;
}

.task-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.65rem;
  align-items: center;
  padding: 0.55rem 0.7rem;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
}

.task-row.done {
  opacity: 0.75;
}

.time {
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  font-size: 0.85rem;
  white-space: nowrap;
}

.title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badge {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  border: 1px solid var(--border);
}

.badge.ok {
  color: var(--ok);
  border-color: rgba(127, 217, 154, 0.35);
}

.badge.pending {
  color: var(--muted);
}

.empty-state {
  min-height: 100px;
  display: grid;
  place-items: center;
  border: 1px dashed var(--border);
  border-radius: 12px;
  background: var(--accent-soft);
}

@media (max-width: 560px) {
  .task-row {
    grid-template-columns: 1fr auto;
    grid-template-areas:
      "title badge"
      "time badge";
  }

  .title {
    grid-area: title;
  }

  .time {
    grid-area: time;
  }

  .badge {
    grid-area: badge;
    align-self: start;
  }
}
</style>

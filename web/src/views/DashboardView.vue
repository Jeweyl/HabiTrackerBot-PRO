<template>
  <div class="page">
    <header class="header">
      <div>
        <h1>HabiTracker Dashboard</h1>
        <p class="muted" style="margin: 0.25rem 0 0">
          Read-only stats · last {{ days }} days
        </p>
      </div>
      <div class="header-actions">
        <div class="range-toggle" role="group" aria-label="Range">
          <button
            type="button"
            class="btn"
            :class="{ 'btn-primary': days === 7 }"
            @click="setDays(7)"
          >
            7d
          </button>
          <button
            type="button"
            class="btn"
            :class="{ 'btn-primary': days === 30 }"
            @click="setDays(30)"
          >
            30d
          </button>
        </div>
        <button type="button" class="btn btn-ghost" @click="logout">
          Log out
        </button>
      </div>
    </header>

    <div v-if="loading" class="card center" style="min-height: 200px">
      <div class="spinner" />
      <p class="muted">Loading stats…</p>
    </div>

    <template v-else>
      <div v-if="loadError" class="card" style="margin-bottom: 1rem">
        <p class="error-title" style="margin: 0">{{ loadError }}</p>
        <p class="muted" style="margin: 0.5rem 0 0">
          Partial data may still be shown below.
        </p>
      </div>

      <section class="grid" style="margin-bottom: 1rem">
        <article class="card stat-card">
          <h3>Completion</h3>
          <div class="value">
            {{ overview ? `${overview.completion_rate}%` : "—" }}
          </div>
          <p class="muted" style="margin: 0.35rem 0 0; font-size: 0.85rem">
            {{
              overview
                ? `${overview.completed_tasks}/${overview.total_tasks} tasks`
                : "No data"
            }}
          </p>
        </article>
        <article class="card stat-card">
          <h3>Streak</h3>
          <div class="value">🔥 {{ overview ? overview.streak : "—" }}</div>
          <p class="muted" style="margin: 0.35rem 0 0; font-size: 0.85rem">
            days in a row
          </p>
        </article>
        <article class="card stat-card">
          <h3>Habits</h3>
          <div class="value">
            {{ overview ? overview.habits_count : "—" }}
          </div>
          <p class="muted" style="margin: 0.35rem 0 0; font-size: 0.85rem">
            templates
          </p>
        </article>
        <article class="card stat-card">
          <h3>Missed</h3>
          <div class="value">
            {{ overview ? overview.missed_tasks : "—" }}
          </div>
          <p class="muted" style="margin: 0.35rem 0 0; font-size: 0.85rem">
            incomplete
          </p>
        </article>
      </section>

      <section class="card" style="margin-bottom: 1rem">
        <h2 class="section-title">Completion chart</h2>
        <CompletionChart :series="dailySeries" />
      </section>

      <section class="card" style="margin-bottom: 1rem">
        <h2 class="section-title">Habit breakdown</h2>
        <HabitBreakdown :items="habits" />
      </section>

      <section class="card">
        <h2 class="section-title">Schedule</h2>
        <ScheduleList :items="schedule" />
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue"
import { useRouter } from "vue-router"
import { ApiError } from "@/api/client"
import {
  fetchDaily,
  fetchHabitBreakdown,
  fetchOverview,
  fetchSchedule,
  type DailyPoint,
  type HabitBreakdownItem,
  type OverviewResponse,
  type ScheduleItem,
} from "@/api/stats"
import { clearAccessToken } from "@/auth/session"
import CompletionChart from "@/components/CompletionChart.vue"
import HabitBreakdown from "@/components/HabitBreakdown.vue"
import ScheduleList from "@/components/ScheduleList.vue"
import { rangeLastDays } from "@/utils/dates"

const router = useRouter()
const loading = ref(true)
const loadError = ref<string | null>(null)
const days = ref(7)
const overview = ref<OverviewResponse | null>(null)
const dailySeries = ref<DailyPoint[]>([])
const schedule = ref<ScheduleItem[]>([])
const habits = ref<HabitBreakdownItem[]>([])

function logout() {
  clearAccessToken()
  void router.replace({
    name: "error",
    query: { reason: "not_authenticated" },
  })
}

function setDays(value: 7 | 30) {
  if (days.value === value) {
    return
  }
  days.value = value
}

async function loadAll() {
  loading.value = true
  loadError.value = null
  const range = rangeLastDays(days.value)

  try {
    const [ov, daily, sched, habitData] = await Promise.all([
      fetchOverview(days.value),
      fetchDaily(range.from, range.to),
      fetchSchedule(range.from, range.to),
      fetchHabitBreakdown(days.value),
    ])
    overview.value = ov
    dailySeries.value = daily?.series ?? []
    schedule.value = sched?.items ?? []
    habits.value = habitData?.items ?? []
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      clearAccessToken()
      await router.replace({
        name: "error",
        query: { reason: "invalid_token" },
      })
      return
    }
    loadError.value =
      err instanceof Error ? err.message : "Failed to load dashboard data"
    // Keep previous data if any; ensure arrays stay defined
    overview.value = overview.value
    dailySeries.value = dailySeries.value ?? []
    schedule.value = schedule.value ?? []
    habits.value = habits.value ?? []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadAll()
})

watch(days, () => {
  void loadAll()
})
</script>

<style scoped>
.header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.range-toggle {
  display: inline-flex;
  gap: 0.35rem;
}

.section-title {
  margin: 0 0 0.75rem;
  font-size: 1.05rem;
}
</style>

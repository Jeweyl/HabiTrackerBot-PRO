<template>
  <div class="page">
    <header class="header">
      <div>
        <h1>HabiTracker Dashboard</h1>
        <p class="muted" style="margin: 0.25rem 0 0">
          Read-only overview · charts arrive in C3
        </p>
      </div>
      <button type="button" class="btn btn-ghost" @click="logout">
        Log out
      </button>
    </header>

    <div v-if="loading" class="card center" style="min-height: 200px">
      <div class="spinner" />
      <p class="muted">Loading stats…</p>
    </div>

    <template v-else>
      <div v-if="loadError" class="card" style="margin-bottom: 1rem">
        <p class="error-title" style="margin: 0">{{ loadError }}</p>
        <p class="muted" style="margin: 0.5rem 0 0">
          Shell still loads — data will appear when the API is reachable.
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
                ? `${overview.completed_tasks}/${overview.total_tasks} tasks · ${overview.days}d`
                : "Last 7 days"
            }}
          </p>
        </article>
        <article class="card stat-card">
          <h3>Streak</h3>
          <div class="value">
            {{ overview ? overview.streak : "—" }}
          </div>
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
            active templates
          </p>
        </article>
        <article class="card stat-card">
          <h3>Missed</h3>
          <div class="value">
            {{ overview ? overview.missed_tasks : "—" }}
          </div>
          <p class="muted" style="margin: 0.35rem 0 0; font-size: 0.85rem">
            incomplete tasks
          </p>
        </article>
      </section>

      <section class="card" style="margin-bottom: 1rem">
        <h2 style="margin: 0 0 0.75rem; font-size: 1.05rem">
          Completion chart
        </h2>
        <div class="placeholder">Chart placeholder (C3)</div>
      </section>

      <section class="card">
        <h2 style="margin: 0 0 0.75rem; font-size: 1.05rem">Schedule</h2>
        <div class="placeholder">Schedule list placeholder (C3)</div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { ApiError } from "@/api/client"
import { fetchOverview, type OverviewResponse } from "@/api/stats"
import { clearAccessToken } from "@/auth/session"

const router = useRouter()
const loading = ref(true)
const loadError = ref<string | null>(null)
const overview = ref<OverviewResponse | null>(null)

function logout() {
  clearAccessToken()
  void router.replace({ name: "error", query: { reason: "not_authenticated" } })
}

onMounted(async () => {
  try {
    overview.value = await fetchOverview(7)
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
      err instanceof Error ? err.message : "Failed to load overview"
    overview.value = null
  } finally {
    loading.value = false
  }
})
</script>

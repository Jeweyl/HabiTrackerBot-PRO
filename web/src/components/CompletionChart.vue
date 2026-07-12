<template>
  <div class="chart-wrap">
    <div v-if="!hasData" class="empty-state">
      <p class="muted" style="margin: 0">
        No completion data for this period yet.
      </p>
    </div>
    <Bar v-else :data="chartData" :options="chartOptions" />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Title,
  Tooltip,
} from "chart.js"
import { Bar } from "vue-chartjs"
import type { DailyPoint } from "@/api/stats"
import { formatShortDate } from "@/utils/dates"

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend)

const props = defineProps<{
  series: DailyPoint[]
}>()

const hasData = computed(() => {
  if (!props.series?.length) {
    return false
  }
  return props.series.some((p) => (p?.total ?? 0) > 0)
})

const chartData = computed(() => {
  const series = props.series ?? []
  return {
    labels: series.map((p) => formatShortDate(p.date)),
    datasets: [
      {
        label: "Completed",
        backgroundColor: "rgba(127, 217, 154, 0.85)",
        borderRadius: 4,
        data: series.map((p) => p.completed ?? 0),
      },
      {
        label: "Missed",
        backgroundColor: "rgba(240, 113, 120, 0.75)",
        borderRadius: 4,
        data: series.map((p) => p.missed ?? 0),
      },
    ],
  }
})

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      labels: { color: "#9aadc2" },
    },
  },
  scales: {
    x: {
      stacked: true,
      ticks: { color: "#9aadc2", maxRotation: 0 },
      grid: { color: "rgba(255,255,255,0.06)" },
    },
    y: {
      stacked: true,
      beginAtZero: true,
      ticks: {
        color: "#9aadc2",
        precision: 0,
      },
      grid: { color: "rgba(255,255,255,0.06)" },
    },
  },
}
</script>

<style scoped>
.chart-wrap {
  height: 240px;
  position: relative;
}


.empty-state {
  min-height: 180px;
  display: grid;
  place-items: center;
  border: 1px dashed var(--border);
  border-radius: 12px;
  background: var(--accent-soft);
}
</style>

<template>
  <div class="backdrop-blur-lg bg-white/20 border border-white/20 rounded-2xl p-6 shadow-xl space-y-4">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold text-black">Metrics</h1>
      <div class="text-xs text-gray-500">
        {{ lastUpdated ? lastUpdated.toLocaleTimeString() : '—' }}
      </div>
    </div>

    <!-- Tabs -->
    <div class="border-b border-gray-300">
      <nav class="-mb-px flex space-x-6">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          @click="activeTab = tab.id"
          :class="[
            'py-2 px-3 border-b-2 text-sm font-medium transition',
            activeTab === tab.id
              ? 'border-purple-500 text-purple-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300',
          ]"
        >
          {{ tab.label }}
        </button>
      </nav>
    </div>

    <div v-if="connected">
      <!-- Metrics Table -->
      <div v-if="activeTab === 'metrics'">
        <div class="overflow-x-auto rounded-lg shadow-inner">
          <table class="table-auto w-full text-sm border-separate border-spacing-0 bg-white/30">
            <thead>
              <tr class="bg-gradient-to-r from-purple-500 to-blue-400 text-white">
                <th class="px-2 py-1 text-left border-b border-dashed border-black/30">Metric</th>
                <th class="px-2 py-1 text-left border-b border-dashed border-black/30">Current</th>
                <th class="px-2 py-1 text-left border-b border-dashed border-black/30">Average</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(value, key) in normalMetrics"
                :key="key"
                class="hover:bg-gray-50 transition"
              >
                <td class="px-2 py-1 border-b border-dashed border-black/30">
                  {{ friendlyLabels[key] ?? key }}
                  <span v-if="getMetricUnit(key)" class="text-gray-500 text-xs">
                    ({{ getMetricUnit(key) }})
                  </span>
                </td>
                <td class="px-2 py-1 border-b border-dashed border-black/30">
                  <span v-if="key === 'zone_name' && typeof value === 'number'">
                    {{ zoneReverseMap[value] ?? value }}
                  </span>
                  <span v-else-if="typeof value === 'number'">{{ Math.round(value) }}</span>
                  <span v-else>{{ value ?? '—' }}</span>
                  {{ getMetricUnit(key) }}
                </td>
                <td class="px-2 py-1 border-b border-dashed border-black/30">
                  <span v-if="key === 'zone_name' && typeof getMovingAverage(key) === 'number'">
                    {{ zoneReverseMap[getMovingAverage(key)] ?? getMovingAverage(key) }}
                  </span>
                  <span v-else-if="typeof getMovingAverage(key) === 'number'">
                    {{ Math.round(getMovingAverage(key)) }}
                  </span>
                  <span v-else>{{ getMovingAverage(key) ?? '—' }}</span>
                  {{ getMetricUnit(key) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Chart Tab -->
      <div v-else-if="activeTab === 'chart'">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div
            v-for="group in chartGroups"
            :key="group.id"
            class="border rounded-lg bg-white/50 p-3 shadow-md"
          >
            <div
              class="flex justify-between items-center cursor-pointer"
              @click="toggleChart(group.id)"
            >
              <h2 class="text-gray-700 font-semibold capitalize">{{ group.label }}</h2>
              <span class="text-gray-500">{{ isChartOpen(group.id) ? '▼' : '►' }}</span>
            </div>
            <div v-show="isChartOpen(group.id)" class="h-64 mt-3">
              <Line :data="getChartDataForGroup(group)" :options="getChartOptionsForGroup(group)" />
            </div>
          </div>
        </div>
      </div>

      <!-- Targets Tab -->
      <div v-else-if="activeTab === 'target'">
        <div class="overflow-x-auto rounded-lg shadow-inner">
          <table class="table-auto w-full text-sm bg-white/30">
            <thead>
              <tr class="bg-gradient-to-r from-purple-500 to-blue-400 text-white">
                <th class="px-3 py-2 text-left border-b border-dashed border-black/30">Metric</th>
                <th class="px-3 py-2 text-left border-b border-dashed border-black/30">Lower Bound</th>
                <th class="px-3 py-2 text-left border-b border-dashed border-black/30">Upper Bound</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="key in metricKeys" :key="key" class="hover:bg-gray-50 transition">
                <td class="px-3 py-2 border-b border-dashed border-black/30">
                  {{ friendlyLabels[key] ?? key }}
                </td>
                <td class="px-3 py-2 border-b border-dashed border-black/30">
                  <input
                    type="number"
                    v-model.number="metricBounds[key].lower"
                    class="border rounded px-2 py-1 w-24"
                  />
                </td>
                <td class="px-3 py-2 border-b border-dashed border-black/30">
                  <input
                    type="number"
                    v-model.number="metricBounds[key].upper"
                    class="border rounded px-2 py-1 w-24"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-else class="p-4 bg-red-100 text-red-600 rounded-lg">Not connected</div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  Title,
  Tooltip,
  Legend,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
} from 'chart.js'
import annotationPlugin from 'chartjs-plugin-annotation'
import { useMetricsStream } from '../composables/singletonStreams.js'

ChartJS.register(Title, Tooltip, Legend, LineElement, PointElement, LinearScale, CategoryScale, annotationPlugin)

// ---------------- STREAM ----------------
const { metrics, lastUpdated, connected } = useMetricsStream()

// ---------------- TABS ----------------
const activeTab = ref('metrics')
const tabs = [
  { id: 'metrics', label: 'Metrics Table' },
  { id: 'chart', label: 'Metrics Chart' },
  { id: 'target', label: 'Target Metrics' },
]

// ---------------- LABELS & UNITS ----------------
const metricUnits = {
  power: 'W',
  speed: 'km/h',
  cadence: 'RPM',
  heart_rate: 'bpm',
  heart_rate_percent: '%',
  distance: 'm',
}
const friendlyLabels = {
  power: 'Power',
  speed: 'Speed',
  cadence: 'Cadence',
  heart_rate: 'Heart Rate',
  heart_rate_percent: 'Heart Rate %',
  distance: 'Distance',
  zone_name: 'Zone',
}

// ---------------- ZONES ----------------
const zoneMap = { UNKNOWN: -1, RESTING: 0, ZONE_1: 1, ZONE_2: 2, ZONE_3: 3, ZONE_4: 4, ZONE_5: 5 }
const zoneReverseMap = Object.fromEntries(Object.entries(zoneMap).map(([k, v]) => [v, k]))

// ---------------- TABLE ----------------
const metricKeys = ['power', 'speed', 'cadence', 'heart_rate', 'heart_rate_percent', 'distance', 'zone_name']

const normalMetrics = computed(() => {
  const data = metrics || {}
  const result = {}
  metricKeys.forEach((key) => {
    result[key] = key in data ? data[key] : null
  })
  return result
})

function getMetricUnit(metric) {
  return metricUnits[metric] ?? ''
}
function getMovingAverage(key) {
  return metrics?.[`ma_${key}`] ?? null
}

// ---------------- CHART ----------------
const MAX_POINTS = 60
const chartGroups = [
  { id: 'power', label: 'Power', metrics: ['power'], onlyMA: false },
  { id: 'speed', label: 'Speed', metrics: ['speed'], onlyMA: false },
  { id: 'cadence', label: 'Cadence', metrics: ['cadence'], onlyMA: false },
  { id: 'heart_rate', label: 'Heart Rate', metrics: ['heart_rate', 'heart_rate_percent'], onlyMA: false },
  { id: 'distance', label: 'Distance', metrics: ['distance'], onlyMA: true },
  { id: 'zone', label: 'Zone', metrics: ['zone_name'], onlyMA: false },
]

const history = ref([])
const openCharts = ref(chartGroups.reduce((acc, g) => ({ ...acc, [g.id]: true }), {}))

const skipped = (ctx, value) => (ctx.p0.skip || ctx.p1.skip ? value : undefined)

watch(
  metrics,
  (newMetrics) => {
    if (!newMetrics) return
    const snapshot = {}
    metricKeys.forEach((key) => {
      if (key === 'zone_name') {
        snapshot[key] = zoneMap[newMetrics[key]] ?? -1
        snapshot[`ma_${key}`] = zoneMap[newMetrics[`ma_${key}`]] ?? -1
      } else {
        snapshot[key] = newMetrics[key] ?? null
        snapshot[`ma_${key}`] = newMetrics[`ma_${key}`] ?? null
      }
    })
    history.value.push(snapshot)
    if (history.value.length > MAX_POINTS) history.value.shift()
  },
  { deep: true }
)

function getChartDataForGroup(group) {
  const labels = history.value.map((_, i) => i + 1)
  const datasets = []

  group.metrics.forEach((key) => {
    if (!group.onlyMA) {
      datasets.push({
        label: friendlyLabels[key],
        data: history.value.map((h) => (h[key] != null ? Math.round(h[key]) : null)),
        borderColor: '#7c3aed',
        tension: 0.3,
        spanGaps: true,
        segment: { borderDash: (ctx) => skipped(ctx, [3, 3]) },
      })
    }
    datasets.push({
      label: `MA ${friendlyLabels[key]}`,
      data: history.value.map((h) => (h[`ma_${key}`] != null ? Math.round(h[`ma_${key}`]) : null)),
      borderColor: '#EC4899',
      tension: 0.3,
      spanGaps: true,
      segment: { borderDash: (ctx) => skipped(ctx, [3, 3]) },
    })
  })

  return { labels, datasets }
}

// ---------------- TARGETS (Shared via localStorage) ----------------
function useSharedLocalStorage(key, defaultValue) {
  const state = ref(JSON.parse(localStorage.getItem(key)) ?? defaultValue)

  watch(
    state,
    (v) => localStorage.setItem(key, JSON.stringify(v)),
    { deep: true }
  )

  window.addEventListener('storage', (e) => {
    if (e.key === key) state.value = JSON.parse(e.newValue)
  })

  return state
}

const metricBounds = useSharedLocalStorage(
  'metricBounds',
  metricKeys.reduce((acc, key) => ({ ...acc, [key]: { lower: null, upper: null } }), {})
)

function getChartOptionsForGroup(group) {
  const isZone = group.id === 'zone'
  const annotations = {}
  group.metrics.forEach((key) => {
    const bounds = metricBounds.value[key]
    if (!bounds) return
    if (typeof bounds.lower === 'number') {
      annotations[`${key}_lower`] = {
        type: 'line',
        yMin: bounds.lower,
        yMax: bounds.lower,
        borderColor: 'red',
        borderDash: [10, 10],
        borderWidth: 2,
      }
    }
    if (typeof bounds.upper === 'number') {
      annotations[`${key}_upper`] = {
        type: 'line',
        yMin: bounds.upper,
        yMax: bounds.upper,
        borderColor: 'green',
        borderDash: [10, 10],
        borderWidth: 2,
      }
    }
  })

  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: { legend: { display: true, position: 'top' }, annotation: { annotations } },
    scales: {
      x: { display: false },
      y: isZone
        ? { min: -1, max: 5, ticks: { stepSize: 1, callback: (value) => zoneReverseMap[value] ?? value } }
        : {},
    },
  }
}

// ---------------- UTILITY ----------------
function toggleChart(id) {
  openCharts.value[id] = !openCharts.value[id]
}
function isChartOpen(id) {
  return openCharts.value[id]
}
</script>
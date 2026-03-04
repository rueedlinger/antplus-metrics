<template>
  <div class="backdrop-blur-lg bg-white/80 rounded-2xl shadow-xl p-6 text-center space-y-6">
    <h2 class="text-2xl font-semibold text-center text-black mb-4">Settings</h2>

    <table class="table-auto w-full text-sm border-separate border-spacing-0 bg-white/30">
      <thead>
        <tr class="bg-gradient-to-r from-purple-500 to-blue-400 text-white">
          <th class="px-2 py-1 text-left border-b border-dashed border-black/30">Setting</th>
          <th class="px-2 py-1 text-left border-b border-dashed border-black/30">Value</th>
        </tr>
      </thead>

      <tbody>
        <!-- Speed Wheel -->
        <tr class="hover:bg-gray-50 transition">
          <td class="px-2 py-1 border-b border-dashed border-black/30 text-left">
            Speed Wheel Circumference (m)
          </td>
          <td class="px-2 py-1 border-b border-dashed border-black/30">
            <input
              v-model.number="localSettings.speed_wheel_circumference_m"
              type="number"
              step="0.001"
              min="0"
              :disabled="isRunning || loading"
              class="border rounded px-2 py-1 w-full bg-white/50"
              placeholder="0.000"
            />
            <p class="text-xs text-gray-500 mt-1">Optional. Leave empty for null.</p>
          </td>
        </tr>

        <!-- Distance Wheel -->
        <tr class="hover:bg-gray-50 transition">
          <td class="px-2 py-1 border-b border-dashed border-black/30 text-left">
            Distance Wheel Circumference (m)
          </td>
          <td class="px-2 py-1 border-b border-dashed border-black/30">
            <input
              v-model.number="localSettings.distance_wheel_circumference_m"
              type="number"
              step="0.001"
              min="0"
              :disabled="isRunning || loading"
              class="border rounded px-2 py-1 w-full bg-white/50"
              placeholder="0.000"
            />
            <p class="text-xs text-gray-500 mt-1">Optional. Leave empty for null.</p>
          </td>
        </tr>

        <!-- Age -->
        <tr class="hover:bg-gray-50 transition">
          <td class="px-2 py-1 border-b border-dashed border-black/30 text-left">Age</td>
          <td class="px-2 py-1 border-b border-dashed border-black/30">
            <input
              v-model.number="localSettings.age"
              type="number"
              min="1"
              :disabled="isRunning || loading"
              class="border rounded px-2 py-1 w-full bg-white/50"
              placeholder="18"
            />
            <p class="text-xs text-gray-500 mt-1">Optional. Leave empty for null.</p>
          </td>
        </tr>

        <!-- Device IDs -->
        <tr class="hover:bg-gray-50 transition">
          <td class="px-2 py-1 border-b border-dashed border-black/30 text-left">Device IDs</td>
          <td class="px-2 py-1 border-b border-dashed border-black/30">
            <input
              v-model="deviceIdsInput"
              type="text"
              :disabled="isRunning || loading"
              class="border rounded px-2 py-1 w-full bg-white/50"
              placeholder="e.g. 1,2,3"
            />
            <p class="text-xs text-gray-500 mt-1">Comma separated values. Leave empty for null.</p>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- Submit -->
    <div class="flex justify-center mt-4">
      <button
        :disabled="loading || isRunning"
        class="px-6 py-2 rounded-2xl font-semibold bg-gradient-to-r from-purple-500 to-blue-400 text-white shadow disabled:opacity-50"
        @click="submitSettings"
      >
        <span v-if="!loading">Update Settings</span>
        <span v-else>Updating...</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, watch, onMounted, computed } from 'vue';
import axios from 'axios';
import { API } from '../config.js';
import { ToastType } from '../constants/toastType.js';
import { useMetricsStream } from '../composables/useStreams.js';

const emit = defineEmits(['show-toast']);
const loading = ref(false);

const { metrics } = useMetricsStream();
const isRunning = computed(() => !!metrics.is_running);

const localSettings = reactive({
  speed_wheel_circumference_m: null,
  distance_wheel_circumference_m: null,
  age: null,
  device_ids: null,
});

/*
|--------------------------------------------------------------------------
| Device IDs Mapper (String <-> Array)
|--------------------------------------------------------------------------
*/
const deviceIdsInput = computed({
  get() {
    if (!localSettings.device_ids || !Array.isArray(localSettings.device_ids)) return '';
    return localSettings.device_ids.join(',');
  },
  set(value) {
    if (!value || value.trim() === '') {
      localSettings.device_ids = null;
      return;
    }

    localSettings.device_ids = value
      .split(',')
      .map((v) => Number(v.trim()))
      .filter((v) => !isNaN(v));
  },
});

/*
|--------------------------------------------------------------------------
| Load Settings
|--------------------------------------------------------------------------
*/
async function loadSettings() {
  try {
    const { data } = await axios.get(API.baseUrl + API.endpoints.getSettings);

    Object.assign(localSettings, {
      speed_wheel_circumference_m: data.speed_wheel_circumference_m ?? null,
      distance_wheel_circumference_m: data.distance_wheel_circumference_m ?? null,
      age: data.age ?? null,
      device_ids: data.device_ids ? [...data.device_ids] : null,
    });
  } catch (err) {
    emit('show-toast', {
      message: err.response?.data?.message || err.message || 'Failed to load settings',
      title: 'Error',
      type: ToastType.ERROR,
    });
  }
}

/*
|--------------------------------------------------------------------------
| Submit Settings (Reload After Save = FIX)
|--------------------------------------------------------------------------
*/
async function submitSettings() {
  if (loading.value) return;
  loading.value = true;

  try {
    const payload = {
      speed_wheel_circumference_m: localSettings.speed_wheel_circumference_m ?? null,
      distance_wheel_circumference_m: localSettings.distance_wheel_circumference_m ?? null,
      age: localSettings.age ?? null,
      device_ids:
        localSettings.device_ids && localSettings.device_ids.length
          ? [...localSettings.device_ids]
          : null,
    };

    await axios.post(API.baseUrl + API.endpoints.updateSettings, payload);

    // 🔥 CRITICAL FIX: Always reload after save
    await loadSettings();

    emit('show-toast', {
      message: 'Settings updated successfully!',
      title: 'Settings',
      type: ToastType.SUCCESS,
    });
  } catch (err) {
    emit('show-toast', {
      message:
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        'Failed to update settings',
      title: 'Error',
      type: ToastType.ERROR,
    });
  } finally {
    loading.value = false;
  }
}

/*
|--------------------------------------------------------------------------
| Auto reload when stopped
|--------------------------------------------------------------------------
*/
watch(isRunning, (running) => {
  if (!running) loadSettings();
});

onMounted(loadSettings);
</script>

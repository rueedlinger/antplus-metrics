// src/composables/useStreams.js
import { ref, reactive, onUnmounted } from 'vue';
import { API } from '../config.js';

/* =========================================================
   STREAM SINGLETON STORE
========================================================= */
const streams = {};

/* =========================================================
   REUSABLE SSE SINGLETON
========================================================= */
function createSSEStreamSingleton(key, url, onData, options = {}) {
  const { heartbeatMs = 5000, reconnectDelay = 2000 } = options;

  // If stream already exists, return it
  if (streams[key]) {
    streams[key].subscribers++;
    return streams[key];
  }

  // Reactive state for this stream
  const connected = ref(false);
  const lastUpdated = ref(null);
  const subscribers = 1; // tracks number of components using this stream

  let source = null;
  let heartbeatTimeout = null;
  let reconnectTimeout = null;

  function clearTimers() {
    clearTimeout(heartbeatTimeout);
    clearTimeout(reconnectTimeout);
  }

  function resetHeartbeat() {
    clearTimeout(heartbeatTimeout);
    heartbeatTimeout = setTimeout(() => {
      connected.value = false;
      source?.close();
      scheduleReconnect();
    }, heartbeatMs);
  }

  function scheduleReconnect() {
    if (reconnectTimeout) return;
    reconnectTimeout = setTimeout(() => {
      reconnectTimeout = null;
      connect();
    }, reconnectDelay);
  }

  function connect() {
    clearTimers();
    source?.close();

    source = new EventSource(url);

    source.onopen = () => {
      connected.value = true;
      resetHeartbeat();
    };

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onData(data);
        lastUpdated.value = new Date();
        connected.value = true;
        resetHeartbeat();
      } catch (err) {
        console.warn('SSE parse error:', err);
      }
    };

    source.onerror = () => {
      connected.value = false;
      source?.close();
      scheduleReconnect();
    };
  }

  // start the stream
  connect();

  // Store singleton info
  streams[key] = { connected, lastUpdated, subscribers, cleanup };

  // Cleanup function
  function cleanup() {
    subscribers--;
    if (subscribers <= 0) {
      clearTimers();
      source?.close();
      delete streams[key];
    }
  }

  return streams[key];
}

/* =========================================================
   METRICS STREAM
========================================================= */
export function useMetricsStream() {
  const metrics = reactive({});
  const { connected, lastUpdated, cleanup } = createSSEStreamSingleton(
    'metrics',
    API.baseUrl + API.endpoints.metricsStream,
    (data) => Object.assign(metrics, data)
  );

  onUnmounted(() => cleanup?.());

  return { metrics, connected, lastUpdated };
}

/* =========================================================
   DEVICES STREAM
========================================================= */
export function useDevicesStream() {
  const devices = ref([]);
  const { connected, lastUpdated, cleanup } = createSSEStreamSingleton(
    'devices',
    API.baseUrl + API.endpoints.devicesStream,
    (data) => (devices.value = data)
  );

  onUnmounted(() => cleanup?.());

  return { devices, connected, lastUpdated };
}

/* =========================================================
   WORKOUT STREAM
========================================================= */
export function useWorkoutStream() {
  const workout = reactive({});
  const { connected, lastUpdated, cleanup } = createSSEStreamSingleton(
    'workout',
    API.baseUrl + API.endpoints.workoutStream,
    (data) => Object.assign(workout, data)
  );

  onUnmounted(() => cleanup?.());

  return { workout, connected, lastUpdated };
}
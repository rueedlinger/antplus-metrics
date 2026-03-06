// src/composables/useStreams.js
import { ref, reactive, onUnmounted } from 'vue';
import { API } from '../config.js';

/* =========================================================
   STREAM SINGLETON STORE
   Each stream is created only once per session
========================================================= */
const streams = {};

/* =========================================================
   CREATE SSE STREAM SINGLETON
========================================================= */
function createSSEStreamSingleton(key, url, onData, options = {}) {
  const { heartbeatMs = 5000, reconnectDelay = 2000 } = options;

  if (streams[key]) {
    streams[key].subscribers++;
    return streams[key];
  }

  const connected = ref(false);
  const lastUpdated = ref(null);
  let subscribers = 1;

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
        console.warn(`SSE parse error on stream ${key}:`, err);
      }
    };

    source.onerror = () => {
      connected.value = false;
      source?.close();
      scheduleReconnect();
    };
  }

  function cleanup() {
    subscribers = Math.max(0, subscribers - 1);
    if (subscribers <= 0) {
      clearTimers();
      source?.close();
      delete streams[key];
    }
  }

  streams[key] = { connected, lastUpdated, cleanup, subscribers };

  connect();

  return streams[key];
}

/* =========================================================
   GENERIC STREAM HOOK
========================================================= */
function useStream(key, url, initialValue = {}, isArray = false) {
  const state = isArray ? ref(initialValue) : reactive(initialValue);

  const { connected, lastUpdated, cleanup } = createSSEStreamSingleton(
    key,
    url,
    (data) => (isArray ? (state.value = data) : Object.assign(state, data))
  );

  onUnmounted(() => cleanup?.());

  return { state, connected, lastUpdated };
}

/* =========================================================
   METRICS STREAM
========================================================= */
export function useMetricsStream() {
  const { state: metrics, connected, lastUpdated } = useStream(
    'metrics',
    API.baseUrl + API.endpoints.metricsStream
  );
  return { metrics, connected, lastUpdated };
}

/* =========================================================
   DEVICES STREAM
========================================================= */
export function useDevicesStream() {
  const { state: devices, connected, lastUpdated } = useStream(
    'devices',
    API.baseUrl + API.endpoints.devicesStream,
    [],
    true
  );
  return { devices, connected, lastUpdated };
}

/* =========================================================
   WORKOUT STREAM
========================================================= */
export function useWorkoutStream() {
  const { state: workout, connected, lastUpdated } = useStream(
    'workout',
    API.baseUrl + API.endpoints.workoutStream
  );
  return { workout, connected, lastUpdated };
}
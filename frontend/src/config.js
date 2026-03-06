export const API = {
  baseUrl: import.meta.env.VITE_API_BASE_URL || '',

  endpoints: {
    status: "/status",
    startMetrics: '/metrics/start',
    stopMetrics: '/metrics/stop',
    getSettings: '/metrics/settings',
    updateSettings: '/metrics/settings',
    metricsStream: '/metrics/stream',
    devicesStream: '/metrics/devices/stream',
    getWorkout: '/workout',
    setWorkout: '/workout',
    workoutStream: '/workout/stream',
    startWorkout: '/workout/start',
    stopWorkout: '/workout/stop',
  },
};

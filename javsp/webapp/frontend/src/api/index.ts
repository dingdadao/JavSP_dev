import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export async function fetchConfig(group?: string) {
  const { data } = await api.get('/config', { params: { group } })
  return data
}

export async function updateConfig(updates: { group: string; key: string; value: any }[]) {
  const { data } = await api.put('/config', updates)
  return data
}

export async function createScrapeTask(params: {
  source?: string
  dest?: string
  translate?: boolean
  move_files?: boolean
  type?: string
}) {
  const { data } = await api.post('/scrape', params)
  return data
}

export async function fetchTasks(limit = 50, offset = 0, status?: string) {
  const { data } = await api.get('/tasks', { params: { limit, offset, status } })
  return data
}

export async function fetchTask(taskId: string) {
  const { data } = await api.get(`/tasks/${taskId}`)
  return data
}

export async function fetchScrapeStatus() {
  const { data } = await api.get('/scrape/status')
  return data
}

export async function fetchWatcher() {
  const { data } = await api.get('/watcher')
  return data
}

export async function addWatchPath(path: string) {
  const { data } = await api.post('/watcher', { path })
  return data
}

export async function removeWatchPath(path: string) {
  const { data } = await api.delete('/watcher', { data: { path } })
  return data
}

export async function toggleWatchPath(path: string, enabled: boolean) {
  const { data } = await api.post('/watcher/toggle', { path, enabled })
  return data
}

export async function fetchLogs(limit = 100, level?: string) {
  const { data } = await api.get('/logs', { params: { limit, level } })
  return data
}

export async function fetchSystemInfo() {
  const { data } = await api.get('/system/info')
  return data
}

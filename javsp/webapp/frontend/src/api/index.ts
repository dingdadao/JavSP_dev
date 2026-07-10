import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// 请求拦截器：在浏览器控制台打印请求数据
api.interceptors.request.use((config) => {
  console.group(`🌐 API Request: ${config.method?.toUpperCase()} ${config.url}`)
  console.log('params:', config.params || null)
  console.log('data:', config.data || null)
  console.groupEnd()
  return config
}, (error) => {
  console.error('🌐 API Request Error', error)
  return Promise.reject(error)
})

// 响应拦截器：在浏览器控制台打印响应数据
api.interceptors.response.use((response) => {
  console.group(`✅ API Response: ${response.config.method?.toUpperCase()} ${response.config.url}`)
  console.log('status:', response.status)
  console.log('data:', response.data)
  console.groupEnd()
  return response
}, (error) => {
  console.error('❌ API Response Error', error.response?.status, error.response?.data || error.message)
  return Promise.reject(error)
})

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

export async function stopScrapeTask() {
  const { data } = await api.post('/scrape/stop')
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

export async function fetchMovie(dvdid: string, path: string) {
  const { data } = await api.get(`/movies/${encodeURIComponent(dvdid)}`, { params: { path } })
  return data
}

export async function updateMovie(dvdid: string, path: string, values: any) {
  const { data } = await api.put(`/movies/${encodeURIComponent(dvdid)}`, values, { params: { path } })
  return data
}

export async function fetchCheckerDefaultPath() {
  const { data } = await api.get('/checker/default-path')
  return data
}

export async function fetchCheckerScan(params: { path: string; convention?: string; modified_after?: string; modified_before?: string; created_after?: string; created_before?: string }) {
  const { data } = await api.post('/checker/scan', params)
  return data
}

export async function fetchCheckerScanCache(path: string) {
  const { data } = await api.get('/checker/scan/cache', { params: { path } })
  return data
}

export async function fixCheckerIssues(items: any[], convention = 'avid') {
  const { data } = await api.post('/checker/fix', { items, convention })
  return data
}

export async function repairChecker(video_paths: string[]) {
  const { data } = await api.post('/checker/repair', { video_paths })
  return data
}

export async function fetchCheckerTasks() {
  const { data } = await api.get('/checker/tasks')
  return data
}

export async function fetchCheckerTaskDetail(taskId: string) {
  const { data } = await api.get(`/checker/tasks/${encodeURIComponent(taskId)}`)
  return data
}

export async function mergeCheckerDuplicates(video_paths: string[]) {
  const { data } = await api.post('/checker/merge', { video_paths })
  return data
}

export async function fetchCheckerLogs() {
  const { data } = await api.get('/checker/logs')
  return data
}

// ==================== 媒体库 ====================
export async function fetchMediaLibraries() {
  const { data } = await api.get('/media-libraries')
  return data
}

export async function createMediaLibrary(params: { name: string; path: string; is_default?: boolean }) {
  const { data } = await api.post('/media-libraries', params)
  return data
}

export async function updateMediaLibrary(libId: number, params: { name?: string; path?: string; is_default?: boolean }) {
  const { data } = await api.put(`/media-libraries/${libId}`, params)
  return data
}

export async function deleteMediaLibrary(libId: number) {
  const { data } = await api.delete(`/media-libraries/${libId}`)
  return data
}

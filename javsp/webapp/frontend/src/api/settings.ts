import { fetchConfig, updateConfig } from './index'

// --- Media Library types ---
export interface MediaLibrary {
  id?: number
  name: string
  path: string
  is_default?: boolean
  created_at?: string
}

// --- Settings helpers (wraps existing /api/config endpoints) ---

export async function fetchScannerSettings() {
  const { data } = await fetchConfig('scanner')
  return data?.scanner || {}
}

export async function fetchSummarizerSettings() {
  const { data } = await fetchConfig('summarizer')
  return data?.summarizer || {}
}

export async function fetchTranslatorSettings() {
  const { data } = await fetchConfig('translator')
  return data?.translator || {}
}

export async function fetchNetworkSettings() {
  const { data } = await fetchConfig('network')
  return data?.network || {}
}

export async function fetchCoverSettings() {
  const { data } = await fetchConfig('cover')
  return data?.cover || {}
}

export async function fetchWatcherSettings() {
  const { data } = await fetchConfig('watcher')
  return data?.watcher || {}
}

export async function saveSettings(group: string, values: Record<string, any>) {
  const updates = Object.entries(values).map(([key, value]) => ({ group, key, value }))
  return updateConfig(updates)
}

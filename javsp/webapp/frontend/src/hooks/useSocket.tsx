import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { io, Socket } from 'socket.io-client'

interface ScrapeProgress {
  task_id: string
  status: string
  total?: number
  completed?: number
  success?: number
  failed?: number
  current?: string
  message?: string
}

interface WatcherEvent {
  type: string
  path: string
  files?: string[]
  message?: string
}

interface RepairProgress {
  task_id: string
  status: string
  total?: number
  completed?: number
  success?: number
  failed?: number
  current?: string
  message?: string
}

interface ScanProgress {
  task_id: string
  status: string
  phase?: string       // 'scanning' | 'analyzing' | 'done'
  dirs_scanned?: number
  total_dirs?: number
  current?: string
  message?: string
  data?: any           // 扫描完成时携带完整结果
}

interface SocketContextType {
  socket: Socket | null
  connected: boolean
  lastProgress: ScrapeProgress | null
  lastWatcherEvent: WatcherEvent | null
  lastRepairProgress: RepairProgress | null
  lastFixProgress: RepairProgress | null
  lastScanProgress: ScanProgress | null
}

const SocketContext = createContext<SocketContextType>({
  socket: null,
  connected: false,
  lastProgress: null,
  lastWatcherEvent: null,
  lastRepairProgress: null,
  lastFixProgress: null,
  lastScanProgress: null,
})

export function SocketProvider({ children }: { children: ReactNode }) {
  const [socket, setSocket] = useState<Socket | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastProgress, setLastProgress] = useState<ScrapeProgress | null>(null)
  const [lastWatcherEvent, setLastWatcherEvent] = useState<WatcherEvent | null>(null)
  const [lastRepairProgress, setLastRepairProgress] = useState<RepairProgress | null>(null)
  const [lastFixProgress, setLastFixProgress] = useState<RepairProgress | null>(null)
  const [lastScanProgress, setLastScanProgress] = useState<ScanProgress | null>(null)

  useEffect(() => {
    // 开发环境 Vite 会代理 /socket.io，生产环境由后端同时提供静态资源和 Socket.IO
    const s = io(window.location.origin, {
      path: '/socket.io/',
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
    })

    s.on('connect', () => {
      console.log('[socket] 已连接')
      setConnected(true)
    })
    s.on('disconnect', (reason) => {
      console.log('[socket] 断开:', reason)
      setConnected(false)
    })
    s.on('connect_error', (err) => {
      console.error('[socket] 连接错误:', err.message)
    })
    s.on('scrape_progress', (data: ScrapeProgress) => {
      console.log('[socket] scrape_progress:', data)
      setLastProgress(data)
    })
    s.on('watcher_event', (data: WatcherEvent) => {
      console.log('[socket] watcher_event:', data)
      setLastWatcherEvent(data)
    })
    s.on('repair_progress', (data: RepairProgress) => {
      console.log('[socket] repair_progress:', data)
      setLastRepairProgress(data)
    })
    s.on('fix_progress', (data: RepairProgress) => {
      console.log('[socket] fix_progress:', data)
      setLastFixProgress(data)
    })
    s.on('scan_progress', (data: ScanProgress) => {
      console.log('[socket] scan_progress:', data)
      setLastScanProgress(data)
    })

    setSocket(s)
    return () => { s.disconnect() }
  }, [])

  return (
    <SocketContext.Provider value={{ socket, connected, lastProgress, lastWatcherEvent, lastRepairProgress, lastFixProgress, lastScanProgress }}>
      {children}
    </SocketContext.Provider>
  )
}

export function useSocket() {
  return useContext(SocketContext)
}

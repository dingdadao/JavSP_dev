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

interface SocketContextType {
  socket: Socket | null
  connected: boolean
  lastProgress: ScrapeProgress | null
  lastWatcherEvent: WatcherEvent | null
}

const SocketContext = createContext<SocketContextType>({
  socket: null,
  connected: false,
  lastProgress: null,
  lastWatcherEvent: null,
})

export function SocketProvider({ children }: { children: ReactNode }) {
  const [socket, setSocket] = useState<Socket | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastProgress, setLastProgress] = useState<ScrapeProgress | null>(null)
  const [lastWatcherEvent, setLastWatcherEvent] = useState<WatcherEvent | null>(null)

  useEffect(() => {
    const s = io(window.location.origin, {
      transports: ['websocket', 'polling'],
      reconnection: true,
    })

    s.on('connect', () => setConnected(true))
    s.on('disconnect', () => setConnected(false))
    s.on('scrape_progress', (data: ScrapeProgress) => setLastProgress(data))
    s.on('watcher_event', (data: WatcherEvent) => setLastWatcherEvent(data))

    setSocket(s)
    return () => { s.disconnect() }
  }, [])

  return (
    <SocketContext.Provider value={{ socket, connected, lastProgress, lastWatcherEvent }}>
      {children}
    </SocketContext.Provider>
  )
}

export function useSocket() {
  return useContext(SocketContext)
}

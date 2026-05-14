/** WebSocket 自动重连 */
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000, 30000]

export function connectWebSocket(
  onMessage: (data: any) => void,
  onStatus?: (connected: boolean) => void,
) {
  let ws: WebSocket | null = null
  let retries = 0
  let closed = false

  function connect() {
    if (closed) return
    ws = new WebSocket('ws://localhost:8000/ws/progress')

    ws.onopen = () => {
      retries = 0
      onStatus?.(true)
    }

    ws.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data))
      } catch { /* ignore */ }
    }

    ws.onclose = () => {
      onStatus?.(false)
      if (closed) return
      const delay = RECONNECT_DELAYS[Math.min(retries, RECONNECT_DELAYS.length - 1)]
      retries++
      setTimeout(connect, delay)
    }

    ws.onerror = () => ws?.close()
  }

  connect()

  return () => {
    closed = true
    ws?.close()
  }
}

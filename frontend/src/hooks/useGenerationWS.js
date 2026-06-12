import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Manages a WebSocket connection to a generation endpoint.
 *
 * @param {'notes'|'mcq'|'flashcards'} type
 * @returns {{ connect, disconnect, status, stages, currentStageIndex, result, error }}
 */
export function useGenerationWS(type) {
  const [status, setStatus] = useState('idle')       // idle | connecting | running | done | error
  const [stages, setStages] = useState([])           // array of { stage, label } received so far
  const [currentStageIndex, setCurrentStageIndex] = useState(-1)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const wsRef = useRef(null)

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onclose = null  // prevent the error handler from firing on intentional close
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  // Clean up on unmount
  useEffect(() => () => disconnect(), [disconnect])

  const connect = useCallback((params) => {
    disconnect()

    const token = localStorage.getItem('ss_token')
    if (!token) {
      setStatus('error')
      setError({ code: 'unauthorized', detail: 'Not logged in.' })
      return
    }

    setStatus('connecting')
    setStages([])
    setCurrentStageIndex(-1)
    setResult(null)
    setError(null)

    // In dev, Vite proxies /api → localhost:8000 including WS.
    // In prod, replace window.location.host with your actual host.
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/api/ws/generate/${type}?token=${encodeURIComponent(token)}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setStatus('running')
      ws.send(JSON.stringify(params))
    }

    ws.onmessage = (event) => {
      let msg
      try {
        msg = JSON.parse(event.data)
      } catch {
        return
      }

      if (msg.type === 'progress') {
        setStages(prev => {
          // Avoid duplicate entries for the same stage
          if (prev.some(s => s.stage === msg.stage)) return prev
          return [...prev, { stage: msg.stage, label: msg.label }]
        })
        setCurrentStageIndex(msg.stage_index)
      } else if (msg.type === 'result') {
        setCurrentStageIndex(msg.total_stages ?? 5)  // advance past last stage
        setStatus('done')
        setResult(msg.data)
      } else if (msg.type === 'error') {
        setStatus('error')
        setError({ code: msg.code, detail: msg.detail })
      }
    }

    ws.onerror = () => {
      setStatus('error')
      setError({ code: 'connection_error', detail: "Can't reach the server. Check your connection and try again." })
    }

    ws.onclose = (event) => {
      wsRef.current = null
      // Only treat as error if we didn't already land in done/error
      if (event.code !== 1000 && event.code !== 1001) {
        setStatus(prev => (prev === 'done' || prev === 'error') ? prev : 'error')
        setError(prev => prev ?? { code: 'disconnected', detail: 'Connection closed unexpectedly.' })
      }
    }
  }, [type, disconnect])

  return { connect, disconnect, status, stages, currentStageIndex, result, error }
}

// ============================================================
// Hook que conecta ao WebSocket de progresso de um job.
//
// Uso:
//   const { progress, isConnected } = useJobProgress(jobId);
//
// Reconecta automaticamente se a conexao cair.
// ============================================================

import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { ProgressMessage } from "./types";

export function useJobProgress(jobId: string | null) {
  const [progress, setProgress] = useState<ProgressMessage | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!jobId) {
      setProgress(null);
      setIsConnected(false);
      return;
    }

    // Reseta estado quando troca de job
    setProgress(null);
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(api.wsUrl(jobId));
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) {
          ws.close();
          return;
        }
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as ProgressMessage;
          setProgress(msg);
        } catch (e) {
          console.error("WS parse error:", e);
        }
      };

      ws.onerror = (e) => {
        console.warn("WS error:", e);
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        // Reconecta automaticamente apos 2s, se ainda nao foi cancelado
        if (!cancelled) {
          reconnectTimer = setTimeout(connect, 2000);
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [jobId]);

  return { progress, isConnected };
}

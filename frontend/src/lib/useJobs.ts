"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, POLL_MS, WS_URL, type Job, type JobEvent } from "./api";

export type Connection = "connecting" | "live" | "polling";

/**
 * Keeps an up-to-date map of jobs. Primary source is the backend WebSocket
 * (/api/ws); when it is down we fall back to polling /api/jobs.
 */
export function useJobs() {
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [connection, setConnection] = useState<Connection>("connecting");
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listJobs({ limit: 200 });
      setJobs(Object.fromEntries(list.map((j) => [j.id, j])));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    const stopPolling = () => {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
    };
    const startPolling = () => {
      if (pollTimer) return;
      pollTimer = setInterval(() => void refresh(), POLL_MS);
    };

    const connect = () => {
      if (!alive) return;
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => {
        if (!alive) return;
        setConnection("live");
        stopPolling();
        void refresh(); // catch anything that happened while disconnected
      };
      ws.onmessage = (ev) => {
        let msg: JobEvent;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (msg.type === "job") {
          setJobs((prev) => ({ ...prev, [msg.job.id]: msg.job }));
        }
      };
      ws.onclose = () => {
        if (!alive) return;
        setConnection("polling");
        startPolling();
        retryTimer = setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();
    };

    // Initial load runs as a callback so no state is set synchronously inside the effect.
    Promise.resolve().then(() => refresh());
    connect();
    return () => {
      alive = false;
      if (retryTimer) clearTimeout(retryTimer);
      stopPolling();
      wsRef.current?.close();
    };
  }, [refresh]);

  const remove = useCallback((id: string) => {
    setJobs((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  return { jobs, connection, error, refresh, remove };
}

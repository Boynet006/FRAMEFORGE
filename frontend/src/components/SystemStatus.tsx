"use client";

import { useEffect, useState } from "react";

import { api, API_URL, POLL_MS, type ComfyStatus, type Health } from "@/lib/api";
import { Card, KV } from "./Card";
import { StatusDot } from "./StatusDot";

type Poll<T> = { data: T | null; error: string | null; at: number | null };

function usePoll<T>(fn: () => Promise<T>, intervalMs: number): Poll<T> {
  const [state, setState] = useState<Poll<T>>({ data: null, error: null, at: null });
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const data = await fn();
        if (alive) setState({ data, error: null, at: Date.now() });
      } catch (e) {
        if (alive) setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e), at: Date.now() }));
      }
    };
    void tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [fn, intervalMs]);
  return state;
}

function fmtMb(bytes?: number) {
  return bytes == null ? "—" : `${Math.round(bytes / 1024 / 1024)} MB`;
}

export function SystemStatus() {
  const health = usePoll<Health>(api.health, POLL_MS);
  const comfy = usePoll<ComfyStatus>(api.comfyStatus, POLL_MS);

  const backendTone = health.error ? "bad" : health.data?.status === "ok" ? "ok" : health.data ? "warn" : "idle";
  const comfyTone = comfy.data?.reachable ? "ok" : comfy.data || comfy.error ? "bad" : "idle";

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Card
        title="Backend"
        right={
          <span className="flex items-center gap-2 text-xs text-muted">
            <StatusDot tone={backendTone} pulse={backendTone === "idle"} />
            {health.error ? "unreachable" : health.data ? health.data.status : "connecting"}
          </span>
        }
      >
        {health.error && (
          <p className="text-sm text-bad break-words">
            Cannot reach <span className="font-mono text-xs">{API_URL}</span>: {health.error}
          </p>
        )}
        {health.data && (
          <>
            <KV k="Version" v={health.data.version} mono />
            <KV k="Uptime" v={`${Math.round(health.data.uptime_s)} s`} />
            <KV k="Database" v={health.data.database_ok ? "ok" : "error"} />
            <KV k="Python" v={health.data.python} mono />
            <KV k="Platform" v={health.data.platform} />
            <KV
              k="NVIDIA GPU"
              v={
                health.data.gpu.length === 0
                  ? <span className="text-warn">none detected</span>
                  : health.data.gpu.map((g) => `${g.name} (${g.memory_total_mb ?? "?"} MB)`).join(", ")
              }
            />
          </>
        )}
      </Card>

      <Card
        title="ComfyUI"
        right={
          <span className="flex items-center gap-2 text-xs text-muted">
            <StatusDot tone={comfyTone} pulse={comfyTone === "idle"} />
            {comfy.data ? (comfy.data.reachable ? "connected" : "unreachable") : comfy.error ? "check failed" : "checking"}
          </span>
        }
      >
        <KV k="URL" v={comfy.data?.url ?? "—"} mono />
        {comfy.data && !comfy.data.reachable && (
          <p className="text-sm text-bad break-words">{comfy.data.error}</p>
        )}
        {comfy.error && <p className="text-sm text-bad break-words">{comfy.error}</p>}
        {comfy.data?.reachable && (
          <>
            <KV k="Latency" v={`${comfy.data.latency_ms} ms`} />
            <KV k="ComfyUI" v={comfy.data.comfyui_version ?? "—"} mono />
            <KV k="PyTorch" v={comfy.data.pytorch_version ?? "—"} mono />
            <KV
              k="Queue"
              v={`${comfy.data.queue_running ?? 0} running / ${comfy.data.queue_pending ?? 0} pending`}
            />
            {comfy.data.devices.map((d, i) => (
              <KV
                key={i}
                k={d.name ?? `device ${i}`}
                v={`${fmtMb(d.vram_free)} free of ${fmtMb(d.vram_total)}`}
              />
            ))}
          </>
        )}
        {!comfy.data?.reachable && (
          <p className="text-xs text-muted">
            Expected until ComfyUI runs on the configured URL. The card refreshes every{" "}
            {Math.round(POLL_MS / 1000)} s.
          </p>
        )}
      </Card>
    </div>
  );
}

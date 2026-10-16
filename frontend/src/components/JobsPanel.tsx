"use client";

import { useState } from "react";

import { api, outputUrl, type Job, type JobStatus, type Project } from "@/lib/api";
import type { Connection } from "@/lib/useJobs";
import { Card } from "./Card";
import { StatusDot, type Tone } from "./StatusDot";

const tone: Record<JobStatus, Tone> = {
  queued: "idle",
  running: "warn",
  succeeded: "ok",
  failed: "bad",
  cancelled: "idle",
};

function fmtBytes(n: number) {
  return n > 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.round(n / 1000)} KB`;
}

function Output({ job, o }: { job: Job; o: { filename: string; kind: string; size: number } }) {
  const url = outputUrl(job.id, o.filename);
  return (
    <div className="flex flex-col gap-1">
      {o.kind === "image" && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt={o.filename} className="max-h-48 rounded-md border border-border object-contain" />
      )}
      {o.kind === "video" && (
        <video src={url} controls className="max-h-48 rounded-md border border-border" preload="metadata" />
      )}
      {o.kind === "audio" && <audio src={url} controls className="w-full" />}
      <a href={url} download={o.filename} className="font-mono text-[11px] text-accent hover:underline">
        {o.filename} · {fmtBytes(o.size)}
      </a>
    </div>
  );
}

export function JobsPanel({
  jobs,
  projects,
  connection,
  error,
  onChanged,
  onRemoved,
  filterProjectId,
}: {
  jobs: Job[];
  projects: Project[];
  connection: Connection;
  error: string | null;
  onChanged: () => void;
  onRemoved: (id: string) => void;
  filterProjectId: string | null;
}) {
  const [actionError, setActionError] = useState<string | null>(null);
  const titles = Object.fromEntries(projects.map((p) => [p.id, p.title]));
  const shown = filterProjectId ? jobs.filter((j) => j.project_id === filterProjectId) : jobs;

  const act = async (fn: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Card
      title={`Jobs${shown.length ? ` (${shown.length})` : ""}`}
      right={
        <span className="flex items-center gap-2 text-xs text-muted">
          <StatusDot tone={connection === "live" ? "ok" : connection === "polling" ? "warn" : "idle"} pulse={connection === "connecting"} />
          {connection === "live" ? "live" : connection === "polling" ? "polling" : "connecting"}
        </span>
      }
    >
      {(error || actionError) && <p className="text-sm text-bad break-words">{error ?? actionError}</p>}
      {shown.length === 0 && <p className="text-sm text-muted">No jobs yet.</p>}
      <ul className="flex flex-col divide-y divide-border">
        {shown.map((j) => {
          const outputs = (j.result?.outputs as Array<{ filename: string; kind: string; size: number }> | undefined) ?? [];
          const wf = (j.payload?.workflow as string) ?? j.kind;
          const active = j.status === "queued" || j.status === "running";
          return (
            <li key={j.id} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
              <div className="flex items-start gap-3">
                <StatusDot tone={tone[j.status]} pulse={j.status === "running"} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="font-medium">
                      {wf}
                      <span className="ml-2 text-xs text-muted">{titles[j.project_id] ?? j.project_id}</span>
                    </span>
                    <span className="font-mono text-[11px] text-muted">
                      {j.id} · {j.status} · attempt {j.attempt}/{j.max_attempts}
                    </span>
                  </div>
                  {active && (
                    <div className="mt-1 h-1.5 w-full overflow-hidden rounded bg-surface-2">
                      <div
                        className={`h-full transition-[width] duration-300 ${j.status === "running" ? "bg-accent" : "bg-muted/40"}`}
                        style={{ width: `${Math.round(j.progress * 100)}%` }}
                      />
                    </div>
                  )}
                  {j.error && <p className="mt-1 text-xs text-bad break-words">{j.error}</p>}
                  {j.status === "succeeded" && (
                    <p className="mt-1 text-xs text-muted">
                      {String(j.result?.duration_s ?? "?")} s · ComfyUI prompt {String(j.payload?.prompt_id ?? "")}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 gap-2 text-xs">
                  {active && (
                    <button onClick={() => void act(() => api.cancelJob(j.id))} className="text-muted hover:text-warn">
                      cancel
                    </button>
                  )}
                  {(j.status === "failed" || j.status === "cancelled") && (
                    <button onClick={() => void act(() => api.retryJob(j.id))} className="text-muted hover:text-ok">
                      retry
                    </button>
                  )}
                  {!active && (
                    <button
                      onClick={() => void act(async () => { await api.deleteJob(j.id); onRemoved(j.id); })}
                      className="text-muted hover:text-bad"
                    >
                      delete
                    </button>
                  )}
                </div>
              </div>
              {outputs.length > 0 && (
                <div className="flex flex-wrap gap-3 pl-6">
                  {outputs.map((o) => (
                    <Output key={o.filename} job={j} o={o} />
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

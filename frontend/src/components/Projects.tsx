"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, type Project, type ProjectStatus } from "@/lib/api";
import { Card } from "./Card";
import { StatusDot, type Tone } from "./StatusDot";

const statusTone: Record<ProjectStatus, Tone> = {
  draft: "idle",
  planning: "warn",
  generating: "warn",
  assembling: "warn",
  completed: "ok",
  failed: "bad",
  cancelled: "idle",
};

const DURATIONS = [30, 60, 120, 300, 600];
const ASPECTS = ["16:9", "9:16", "1:1"];
const STYLES = ["cinematic", "cartoon", "3d-animated", "photoreal", "anime"];
const QUALITY = ["draft", "final"];

export function Projects() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState(60);
  const [aspect, setAspect] = useState("16:9");
  const [style, setStyle] = useState("cinematic");
  const [quality, setQuality] = useState("draft");

  const refresh = useCallback(async () => {
    try {
      setProjects(await api.listProjects());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    let alive = true;
    api
      .listProjects()
      .then((list) => {
        if (alive) {
          setProjects(list);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.createProject({
        title: title.trim() || prompt.trim().slice(0, 60),
        prompt: prompt.trim(),
        settings: { duration_s: duration, aspect_ratio: aspect, style, quality },
      });
      setTitle("");
      setPrompt("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (id: string) => {
    if (!confirm("Delete this project and all its jobs?")) return;
    try {
      await api.deleteProject(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const select =
    "rounded-md border border-border bg-surface-2 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/60";

  return (
    <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
      <Card title="New project">
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title (optional)"
            className={select}
            maxLength={200}
          />
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            required
            rows={5}
            placeholder="Describe the video. Example: A funny, cinematic conversation between two cats about why humans are terrible at choosing food…"
            className={`${select} resize-y leading-relaxed`}
          />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <label className="flex flex-col gap-1 text-xs text-muted">
              Duration
              <select value={duration} onChange={(e) => setDuration(Number(e.target.value))} className={select}>
                {DURATIONS.map((d) => (
                  <option key={d} value={d}>
                    {d >= 60 ? `${d / 60} min` : `${d} s`}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Aspect
              <select value={aspect} onChange={(e) => setAspect(e.target.value)} className={select}>
                {ASPECTS.map((a) => <option key={a}>{a}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Style
              <select value={style} onChange={(e) => setStyle(e.target.value)} className={select}>
                {STYLES.map((s) => <option key={s}>{s}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Quality
              <select value={quality} onChange={(e) => setQuality(e.target.value)} className={select}>
                {QUALITY.map((q) => <option key={q}>{q}</option>)}
              </select>
            </label>
          </div>
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted">
              Phase 1 stores the project. Generation is wired up in Phase 2.
            </p>
            <button
              type="submit"
              disabled={busy || !prompt.trim()}
              className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-black disabled:opacity-40 hover:brightness-110"
            >
              {busy ? "Saving…" : "Create project"}
            </button>
          </div>
        </form>
      </Card>

      <Card
        title={`Projects${projects ? ` (${projects.length})` : ""}`}
        right={
          <button onClick={() => void refresh()} className="text-xs text-muted hover:text-foreground">
            refresh
          </button>
        }
      >
        {error && <p className="text-sm text-bad break-words">{error}</p>}
        {projects === null && !error && <p className="text-sm text-muted">Loading…</p>}
        {projects?.length === 0 && <p className="text-sm text-muted">No projects yet.</p>}
        <ul className="flex flex-col divide-y divide-border">
          {projects?.map((p) => (
            <li key={p.id} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
              <StatusDot tone={statusTone[p.status]} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-medium">{p.title}</span>
                  <span className="shrink-0 font-mono text-[11px] text-muted">{p.id}</span>
                </div>
                <p className="line-clamp-2 text-sm text-muted">{p.prompt}</p>
                <p className="mt-1 text-xs text-muted">
                  {p.status} · {String(p.settings.duration_s ?? "?")} s · {String(p.settings.aspect_ratio ?? "")}{" "}
                  · {String(p.settings.style ?? "")} · {p.job_count} jobs ·{" "}
                  {new Date(p.created_at).toLocaleString()}
                </p>
              </div>
              <button
                onClick={() => void onDelete(p.id)}
                className="shrink-0 text-xs text-muted hover:text-bad"
                aria-label={`Delete ${p.title}`}
              >
                delete
              </button>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

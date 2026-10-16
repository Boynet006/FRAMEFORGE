"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  fileUrl,
  type Job,
  type PlanSummary,
  type ProductionPlan,
  type Project,
  type RenderInfo,
} from "@/lib/api";
import { Card, KV } from "./Card";
import { StatusDot, type Tone } from "./StatusDot";

type StageKey = "plan" | "tts" | "refs" | "animate" | "assemble";

const STAGES: Array<{ key: StageKey; label: string; kind: string; help: string }> = [
  { key: "plan", label: "Script", kind: "plan.generate", help: "Local LLM writes characters, scenes and dialogue" },
  { key: "tts", label: "Voices", kind: "tts.generate", help: "Kokoro speaks every line; builds the dialogue timeline" },
  { key: "refs", label: "References", kind: "refs.generate", help: "ComfyUI renders character and environment images" },
  { key: "animate", label: "Animate", kind: "animate.render", help: "Shots, lip movement, blinks, camera moves" },
  { key: "assemble", label: "Assemble", kind: "assemble.render", help: "Subtitles, music, final MP4 with checks" },
];

const btn = "rounded-md border border-border bg-surface-2 px-3 py-1.5 text-xs hover:border-accent/60 disabled:opacity-40";
const field = "rounded-md border border-border bg-surface-2 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-accent/60 w-full";

function fmtBytes(n: number) {
  return n > 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.round(n / 1000)} KB`;
}

export function ProjectWorkspace({ project, jobs }: { project: Project; jobs: Job[] }) {
  const [plan, setPlan] = useState<ProductionPlan | null>(null);
  const [summary, setSummary] = useState<PlanSummary | null>(null);
  const [render, setRender] = useState<RenderInfo | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const projectJobs = useMemo(() => jobs.filter((j) => j.project_id === project.id), [jobs, project.id]);
  const activeJob = projectJobs.find((j) => j.status === "running" || j.status === "queued") ?? null;
  const pipelineJob = projectJobs.find((j) => j.kind === "pipeline.full") ?? null;
  const jobsKey = projectJobs.map((j) => `${j.id}:${j.status}:${Math.round(j.progress * 20)}`).join(",");

  const refresh = useCallback(() => {
    api.getRender(project.id).then(setRender).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    if (project.has_plan) {
      api
        .getPlan(project.id)
        .then((r) => {
          setPlan(r.plan);
          setSummary(r.summary);
        })
        .catch(() => undefined);
    } else {
      setPlan(null);
      setSummary(null);
    }
  }, [project.id, project.has_plan]);

  // Refresh outputs whenever a job of this project changes state.
  useEffect(() => {
    Promise.resolve().then(refresh);
  }, [refresh, jobsKey]);

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const latestOfKind = (kind: string) => projectJobs.find((j) => j.kind === kind) ?? null;
  const stageTone = (key: StageKey): Tone => {
    const j = latestOfKind(STAGES.find((s) => s.key === key)!.kind);
    const done =
      key === "plan" ? project.has_plan
      : key === "tts" ? Boolean(render?.dialogue)
      : key === "refs" ? (render?.refs.length ?? 0) > 0
      : key === "animate" ? Boolean(render?.video_silent)
      : Boolean(render?.final);
    if (j && (j.status === "running" || j.status === "queued")) return "warn";
    if (j && j.status === "failed") return "bad";
    return done ? "ok" : "idle";
  };

  const savePlan = async () => {
    if (!plan) return;
    setSaving(true);
    await run(async () => {
      const r = await api.putPlan(project.id, plan);
      setPlan(r.plan);
      setSummary(r.summary);
    });
    setSaving(false);
  };

  const names = Object.fromEntries((plan?.characters ?? []).map((c) => [c.id, c.name]));

  return (
    <div className="flex flex-col gap-4">
      <Card
        title={`Production · ${project.title}`}
        right={
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} className="accent-accent" />
            advanced mode
          </label>
        }
      >
        {error && <p className="text-sm text-bad break-words">{error}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => void run(() => api.generateFull(project.id))}
            disabled={Boolean(activeJob)}
            className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-black disabled:opacity-40 hover:brightness-110"
          >
            {activeJob ? "Working…" : render?.final ? "Regenerate missing stages" : "Generate complete video"}
          </button>
          {advanced && (
            <button onClick={() => void run(() => api.generateFull(project.id, true))} disabled={Boolean(activeJob)} className={btn}>
              force full re-run
            </button>
          )}
          {pipelineJob && (pipelineJob.status === "running" || pipelineJob.status === "queued") && (
            <div className="flex min-w-[220px] flex-1 flex-col gap-1">
              <div className="h-2 w-full overflow-hidden rounded bg-surface-2">
                <div className="h-full bg-accent transition-[width] duration-500" style={{ width: `${Math.round(pipelineJob.progress * 100)}%` }} />
              </div>
              <span className="text-xs text-muted">
                pipeline {Math.round(pipelineJob.progress * 100)}% · attempt {pipelineJob.attempt}/{pipelineJob.max_attempts}
              </span>
            </div>
          )}
          {pipelineJob?.status === "failed" && <span className="text-xs text-bad break-words">{pipelineJob.error}</span>}
        </div>

        <ol className="grid gap-2 sm:grid-cols-5">
          {STAGES.map((s) => {
            const j = latestOfKind(s.kind);
            const running = j && (j.status === "running" || j.status === "queued");
            return (
              <li key={s.key} className="flex flex-col gap-1 rounded-md border border-border bg-surface-2/40 p-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <StatusDot tone={stageTone(s.key)} pulse={Boolean(running)} />
                  {s.label}
                </div>
                <p className="text-[11px] leading-snug text-muted">{s.help}</p>
                {running && (
                  <div className="h-1 w-full overflow-hidden rounded bg-surface">
                    <div className="h-full bg-accent" style={{ width: `${Math.round(j!.progress * 100)}%` }} />
                  </div>
                )}
                {j?.status === "failed" && <p className="text-[11px] text-bad line-clamp-3">{j.error}</p>}
                {advanced && (
                  <button
                    onClick={() => void run(() => api.runStage(project.id, s.key))}
                    disabled={Boolean(activeJob) || (s.key !== "plan" && !project.has_plan)}
                    className={`${btn} mt-auto`}
                  >
                    run {s.label.toLowerCase()}
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      </Card>

      {render?.final && (
        <Card title="Final video" right={<a href={render.final.url} download className="text-xs text-accent hover:underline">download MP4 · {fmtBytes(render.final.size)}</a>}>
          <video key={render.final.size} src={render.final.url} controls className="w-full rounded-md border border-border bg-black" preload="metadata" />
          <div className="flex flex-wrap gap-4 text-xs text-muted">
            {render.subtitles && <a href={render.subtitles.url} download className="hover:text-foreground">subtitles.srt</a>}
            {render.dialogue && <a href={render.dialogue.url} download className="hover:text-foreground">dialogue.wav</a>}
            {render.music && <a href={render.music.url} download className="hover:text-foreground">music.wav</a>}
            {render.video_silent && <a href={render.video_silent.url} download className="hover:text-foreground">picture track (silent)</a>}
          </div>
        </Card>
      )}

      {plan && summary && (
        <Card
          title={`Script · ${plan.title}`}
          right={
            advanced ? (
              <button onClick={() => void savePlan()} disabled={saving} className={btn}>
                {saving ? "saving…" : "save edits"}
              </button>
            ) : (
              <span className="text-xs text-muted">
                {summary.lines} lines · {summary.words} words · ~{Math.round(summary.estimated_duration_s)} s of {summary.target_duration_s} s
              </span>
            )
          }
        >
          {plan.logline && <p className="text-sm italic text-muted">{plan.logline}</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            {plan.characters.map((c, ci) => (
              <div key={c.id} className="flex gap-3 rounded-md border border-border bg-surface-2/40 p-2">
                {c.reference_image ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={fileUrl(project.id, c.reference_image)} alt={c.name} className="h-24 w-20 shrink-0 rounded object-cover" />
                ) : (
                  <div className="flex h-24 w-20 shrink-0 items-center justify-center rounded bg-surface text-[10px] text-muted">no ref yet</div>
                )}
                <div className="min-w-0 flex-1 text-xs">
                  <div className="text-sm font-medium">{c.name} <span className="text-muted">· {c.role}</span></div>
                  {advanced ? (
                    <>
                      <textarea className={`${field} mt-1`} rows={2} value={c.personality}
                        onChange={(e) => setPlan({ ...plan, characters: plan.characters.map((x, i) => i === ci ? { ...x, personality: e.target.value } : x) })} />
                      <textarea className={`${field} mt-1`} rows={2} value={c.image_prompt}
                        onChange={(e) => setPlan({ ...plan, characters: plan.characters.map((x, i) => i === ci ? { ...x, image_prompt: e.target.value } : x) })} />
                      <div className="mt-1 flex gap-2">
                        <input className={field} value={c.voice.voice}
                          onChange={(e) => setPlan({ ...plan, characters: plan.characters.map((x, i) => i === ci ? { ...x, voice: { ...x.voice, voice: e.target.value } } : x) })} />
                        <input className={`${field} w-20`} type="number" step={0.05} min={0.6} max={1.5} value={c.voice.speed}
                          onChange={(e) => setPlan({ ...plan, characters: plan.characters.map((x, i) => i === ci ? { ...x, voice: { ...x.voice, speed: Number(e.target.value) } } : x) })} />
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="text-muted">{c.personality}</p>
                      <p className="mt-1 text-muted">voice {c.voice.voice} · {c.appearance}</p>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-3">
            {plan.environments.map((e) => (
              <div key={e.id} className="flex items-center gap-2 text-xs text-muted">
                {e.reference_image && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={fileUrl(project.id, e.reference_image)} alt={e.name} className="h-14 w-24 rounded object-cover" />
                )}
                <span><span className="text-foreground">{e.name}</span> · {e.description}</span>
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-3">
            {plan.scenes.map((s, si) => (
              <div key={s.id} className="rounded-md border border-border p-2">
                <p className="text-xs text-muted">
                  <span className="font-semibold text-foreground">Scene {si + 1}</span> · {s.summary} · {s.time_of_day}
                </p>
                <ul className="mt-1 flex flex-col gap-1">
                  {s.lines.map((l, li) => (
                    <li key={l.id} className="flex gap-2 text-sm">
                      <span className="w-24 shrink-0 text-right text-xs text-accent">{names[l.character_id] ?? l.character_id}</span>
                      {advanced ? (
                        <input className={field} value={l.text}
                          onChange={(e) => setPlan({ ...plan, scenes: plan.scenes.map((sc, i) => i === si ? { ...sc, lines: sc.lines.map((x, j) => j === li ? { ...x, text: e.target.value } : x) } : sc) })} />
                      ) : (
                        <span>{l.text} <span className="text-[10px] text-muted">({l.emotion})</span></span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          {advanced && (
            <p className="text-xs text-muted">After editing, re-run Voices (and Animate/Assemble) so the audio and picture match the new text.</p>
          )}
        </Card>
      )}

      {!plan && (
        <Card title="Script">
          <p className="text-sm text-muted">No script yet. Press “Generate complete video”, or in advanced mode run the Script stage alone.</p>
          <KV k="Prompt" v={project.prompt} />
          <KV k="Settings" v={`${String(project.settings.duration_s ?? "?")} s · ${String(project.settings.style ?? "")} · ${String(project.settings.aspect_ratio ?? "")} · ${String(project.settings.quality ?? "")}`} />
        </Card>
      )}
    </div>
  );
}

"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";

import { api, type Project, type Workflow } from "@/lib/api";
import { Card } from "./Card";

const field =
  "rounded-md border border-border bg-surface-2 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/60 w-full";

export function GeneratePanel({
  project,
  onQueued,
}: {
  project: Project | null;
  onQueued?: () => void;
}) {
  const [workflows, setWorkflows] = useState<Workflow[] | null>(null);
  const [selected, setSelected] = useState<string>("");
  // User edits are kept per (template, project) so switching either resets to defaults.
  const [overrides, setOverrides] = useState<{ key: string; values: Record<string, unknown> }>({ key: "", values: {} });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .listWorkflows()
      .then((list) => {
        if (!alive) return;
        setWorkflows(list);
        if (list.length && !selected) setSelected(list[0].key);
      })
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const workflow = useMemo(() => workflows?.find((w) => w.key === selected) ?? null, [workflows, selected]);

  // Defaults come from the template; the project's prompt seeds the "prompt" parameter.
  const formKey = `${workflow?.key ?? ""}:${project?.id ?? ""}`;
  // Plain derivation; the React Compiler memoizes it.
  const values: Record<string, unknown> = {};
  if (workflow) {
    for (const [k, spec] of Object.entries(workflow.inputs)) values[k] = spec.default;
    if ("prompt" in workflow.inputs && project?.prompt) values.prompt = project.prompt;
    if (overrides.key === formKey) Object.assign(values, overrides.values);
  }

  const setValue = (name: string, v: unknown) =>
    setOverrides((prev) => ({
      key: formKey,
      values: { ...(prev.key === formKey ? prev.values : {}), [name]: v },
    }));

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!project || !workflow) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const job = await api.createJob(project.id, {
        workflow: workflow.name,
        version: workflow.version,
        params: values,
      });
      setNotice(`Queued job ${job.id}`);
      onQueued?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title="Single workflow run (advanced)"
      right={
        project ? (
          <span className="truncate text-xs text-muted">for “{project.title}”</span>
        ) : (
          <span className="text-xs text-warn">select a project</span>
        )
      }
    >
      {error && <p className="text-sm text-bad break-words">{error}</p>}
      {workflows && workflows.length === 0 && <p className="text-sm text-muted">No workflow templates found.</p>}
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Workflow template
          <select value={selected} onChange={(e) => setSelected(e.target.value)} className={field}>
            {workflows?.map((w) => (
              <option key={w.key} value={w.key}>
                {w.name} v{w.version} · {w.output_kind}
                {w.validated ? "" : " · unvalidated"}
              </option>
            ))}
          </select>
        </label>
        {workflow && (
          <>
            <p className="text-xs text-muted">{workflow.description}</p>
            {!workflow.validated && (
              <p className="rounded-md border border-warn/40 bg-warn/10 px-2 py-1 text-xs text-warn">
                This template has not been validated on real hardware yet. Requires:{" "}
                {(workflow.requires.models ?? []).join(", ") || "see template"}.
              </p>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(workflow.inputs).map(([name, spec]) => {
                const isText = spec.type === "string" && (name.includes("prompt") || String(spec.default ?? "").length > 40);
                const v = values[name];
                return (
                  <label
                    key={name}
                    className={`flex flex-col gap-1 text-xs text-muted ${isText ? "sm:col-span-2" : ""}`}
                  >
                    {spec.label}
                    {spec.type === "boolean" ? (
                      <input
                        type="checkbox"
                        checked={Boolean(v)}
                        onChange={(e) => setValue(name, e.target.checked)}
                        className="h-4 w-4 accent-accent"
                      />
                    ) : isText ? (
                      <textarea
                        rows={3}
                        value={String(v ?? "")}
                        onChange={(e) => setValue(name, e.target.value)}
                        className={`${field} resize-y`}
                      />
                    ) : (
                      <input
                        type={spec.type === "string" ? "text" : "number"}
                        value={String(v ?? "")}
                        min={spec.min ?? undefined}
                        max={spec.max ?? undefined}
                        step={spec.step ?? (spec.type === "number" ? "any" : 1)}
                        onChange={(e) =>
                          setValue(name, spec.type === "string" ? e.target.value : Number(e.target.value))
                        }
                        className={field}
                      />
                    )}
                  </label>
                );
              })}
            </div>
          </>
        )}
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-muted">{notice}</span>
          <button
            type="submit"
            disabled={busy || !project || !workflow}
            className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-black disabled:opacity-40 hover:brightness-110"
          >
            {busy ? "Queueing…" : "Generate"}
          </button>
        </div>
      </form>
    </Card>
  );
}

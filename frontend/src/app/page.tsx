"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { GeneratePanel } from "@/components/GeneratePanel";
import { JobsPanel } from "@/components/JobsPanel";
import { NewProject, ProjectList } from "@/components/Projects";
import { ProjectWorkspace } from "@/components/ProjectWorkspace";
import { SimpleCreate } from "@/components/SimpleCreate";
import { EngineSummary, SystemStatus } from "@/components/SystemStatus";
import { api, type Project } from "@/lib/api";
import { useJobs } from "@/lib/useJobs";
import { useStoredString, type UiMode } from "@/lib/useStored";

function ModeToggle({ mode, onChange }: { mode: UiMode; onChange: (m: UiMode) => void }) {
  const opts: Array<[UiMode, string, string]> = [
    ["simple", "Simple", "Describe a video and get the finished MP4"],
    ["advanced", "Advanced", "Engine details, stage-by-stage control, script editing, raw workflows and jobs"],
  ];
  return (
    <div role="radiogroup" aria-label="Interface mode" className="flex rounded-full border border-border bg-surface p-0.5 text-xs">
      {opts.map(([m, label, title]) => (
        <button
          key={m}
          role="radio"
          aria-checked={mode === m}
          title={title}
          onClick={() => onChange(m)}
          className={`rounded-full px-3 py-1 transition-colors ${
            mode === m ? "bg-accent font-semibold text-black" : "text-muted hover:text-foreground"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export default function Home() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [mode, setMode] = useStoredString<UiMode>("frameforge.mode", "simple");
  const [selectedId, setSelectedId] = useStoredString<string>("frameforge.project", null);
  const uiMode: UiMode = mode === "advanced" ? "advanced" : "simple";
  const simple = uiMode === "simple";
  const { jobs, connection, error: jobsError, refresh: refreshJobs, remove } = useJobs();

  const refreshProjects = useCallback(() => {
    api
      .listProjects()
      .then((list) => {
        setProjects(list);
        setProjectsError(null);
      })
      .catch((e: unknown) => setProjectsError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    refreshProjects();
  }, [refreshProjects]);

  // Job state changes alter project status / job counts; refresh the list when any job settles.
  const settledKey = useMemo(
    () => Object.values(jobs).map((j) => `${j.id}:${j.status}`).join(","),
    [jobs],
  );
  useEffect(() => {
    if (projects !== null) refreshProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settledKey]);

  // A remembered project that no longer exists (deleted elsewhere) is simply not shown.
  const selected = projects?.find((p) => p.id === selectedId) ?? null;
  const jobList = useMemo(
    () => Object.values(jobs).sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [jobs],
  );

  const onCreated = (p: Project) => {
    setSelectedId(p.id);
    refreshProjects();
    refreshJobs();
  };

  const list = (
    <ProjectList
      projects={projects}
      selectedId={selectedId}
      onSelect={setSelectedId}
      onRefresh={refreshProjects}
      error={projectsError}
      simple={simple}
    />
  );

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            <span className="text-accent">FRAME</span>FORGE
          </h1>
          <p className="text-sm text-muted">Local AI video studio · one prompt to a finished MP4</p>
        </div>
        <div className="flex items-center gap-3">
          <ModeToggle mode={uiMode} onChange={setMode} />
          {!simple && (
            <span className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted">v0.4.0</span>
          )}
        </div>
      </header>

      {simple ? (
        <>
          <EngineSummary />
          <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
            <SimpleCreate onCreated={onCreated} />
            {list}
          </div>
          {selected && <ProjectWorkspace key={selected.id} project={selected} jobs={jobList} mode="simple" />}
        </>
      ) : (
        <>
          <SystemStatus />
          <div className="grid gap-4 lg:grid-cols-2">
            <NewProject onCreated={onCreated} />
            {list}
          </div>
          {selected && <ProjectWorkspace key={selected.id} project={selected} jobs={jobList} mode="advanced" />}
          <div className="grid gap-4 lg:grid-cols-[1fr_1.3fr]">
            <GeneratePanel project={selected} onQueued={refreshJobs} />
            <JobsPanel
              jobs={jobList}
              projects={projects ?? []}
              connection={connection}
              error={jobsError}
              onChanged={refreshJobs}
              onRemoved={remove}
              filterProjectId={selectedId}
            />
          </div>
        </>
      )}
    </div>
  );
}

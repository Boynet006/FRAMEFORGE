"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { GeneratePanel } from "@/components/GeneratePanel";
import { JobsPanel } from "@/components/JobsPanel";
import { NewProject, ProjectList } from "@/components/Projects";
import { ProjectWorkspace } from "@/components/ProjectWorkspace";
import { SystemStatus } from "@/components/SystemStatus";
import { api, type Project } from "@/lib/api";
import { useJobs } from "@/lib/useJobs";

export default function Home() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
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

  const selected = projects?.find((p) => p.id === selectedId) ?? null;
  const jobList = useMemo(
    () => Object.values(jobs).sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [jobs],
  );

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            <span className="text-accent">FRAME</span>FORGE
          </h1>
          <p className="text-sm text-muted">Local AI video studio · one prompt to a finished MP4</p>
        </div>
        <span className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted">v0.3.0</span>
      </header>

      <SystemStatus />

      <div className="grid gap-4 lg:grid-cols-2">
        <NewProject
          onCreated={(p) => {
            setSelectedId(p.id);
            refreshProjects();
          }}
        />
        <ProjectList
          projects={projects}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onRefresh={refreshProjects}
          error={projectsError}
        />
      </div>

      {selected && <ProjectWorkspace project={selected} jobs={jobList} />}

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
    </div>
  );
}

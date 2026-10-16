/**
 * Typed client for the FRAMEFORGE backend API.
 * Every function throws ApiError on non-2xx; callers decide how to show it.
 */

export const API_URL =
  (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export const POLL_MS = Number(process.env.NEXT_PUBLIC_POLL_MS ?? 5000);

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------- types mirrored from backend/app/schemas.py ----------

export interface GpuInfo {
  name: string;
  driver_version: string | null;
  memory_total_mb: number | null;
  memory_used_mb: number | null;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  uptime_s: number;
  time: string;
  database_ok: boolean;
  gpu: GpuInfo[];
  python: string;
  platform: string;
}

export interface ComfyStatus {
  reachable: boolean;
  url: string;
  latency_ms: number | null;
  comfyui_version: string | null;
  python_version: string | null;
  pytorch_version: string | null;
  devices: Array<{
    name?: string;
    type?: string;
    vram_total?: number;
    vram_free?: number;
    torch_vram_total?: number;
    torch_vram_free?: number;
  }>;
  queue_running: number | null;
  queue_pending: number | null;
  error: string | null;
}

export type ProjectStatus =
  | "draft" | "planning" | "generating" | "assembling" | "completed" | "failed" | "cancelled";

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Project {
  id: string;
  title: string;
  prompt: string;
  settings: Record<string, unknown>;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  job_count: number;
}

export interface Job {
  id: string;
  project_id: string;
  kind: string;
  status: JobStatus;
  progress: number;
  attempt: number;
  max_attempts: number;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ProjectDetail extends Project {
  jobs: Job[];
}

export interface ProjectCreate {
  title: string;
  prompt: string;
  settings: Record<string, unknown>;
}

export interface WorkflowInput {
  type: "string" | "integer" | "number" | "boolean";
  default: unknown;
  label: string;
  min: number | null;
  max: number | null;
  step: number | null;
}

export interface Workflow {
  name: string;
  version: number;
  key: string;
  engine: string;
  description: string;
  output_kind: "image" | "video" | "audio";
  validated: boolean;
  requires: { models?: string[] };
  inputs: Record<string, WorkflowInput>;
  outputs: Array<{ node: string; kind: string }>;
}

export interface JobCreate {
  workflow: string;
  version?: number;
  params: Record<string, unknown>;
}

export interface JobOutput {
  filename: string;
  kind: "image" | "video" | "audio" | "file";
  node: string;
  size: number;
}

export type JobEvent =
  | { type: "hello" }
  | { type: "ping" }
  | { type: "job"; job: Job }
  | { type: "project"; project: { id: string; status: ProjectStatus } };

export const WS_URL = API_URL.replace(/^http/, "ws") + "/api/ws";

export function outputUrl(jobId: string, filename: string): string {
  return `${API_URL}/api/jobs/${jobId}/outputs/${encodeURIComponent(filename)}`;
}

// ---------- calls ----------

export const api = {
  health: () => request<Health>("/api/health"),
  comfyStatus: () => request<ComfyStatus>("/api/comfy/status"),
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<ProjectDetail>(`/api/projects/${id}`),
  createProject: (body: ProjectCreate) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),
  listJobs: (params?: { project_id?: string; status?: JobStatus; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.project_id) q.set("project_id", params.project_id);
    if (params?.status) q.set("status", params.status);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<Job[]>(`/api/jobs${qs ? `?${qs}` : ""}`);
  },
  listWorkflows: () => request<Workflow[]>("/api/workflows"),
  createJob: (projectId: string, body: JobCreate) =>
    request<Job>(`/api/projects/${projectId}/jobs`, { method: "POST", body: JSON.stringify(body) }),
  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),
  deleteJob: (id: string) => request<void>(`/api/jobs/${id}`, { method: "DELETE" }),
  comfyFree: () => request<void>("/api/comfy/free", { method: "POST" }),
};

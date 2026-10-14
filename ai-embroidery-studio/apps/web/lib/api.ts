// Typed client for the FastAPI backend (services/api).
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const USER_KEY = "emb.devUser";

export type FabricPreset = "woven_cotton" | "knit_cotton" | "canvas" | "other";
export type JobStatus = "queued" | "preprocessing" | "planning" | "compiling" | "validating" | "exporting" | "ready" | "failed";

export interface Project {
  id: string; name: string; fabricPreset: FabricPreset; status: "draft" | "awaiting_test_sew" | "accepted";
  currentRevision: number; compiledRevision: number | null; widthMm: number | null; heightMm: number | null;
  colorCount: number | null; stitchCount: number | null; createdAt: string; updatedAt: string;
}
export interface Region {
  id: string; name: string; colorId: string; order: number; stitchType: "fill" | "running";
  params: Record<string, number | boolean>; warnings: string[];
}
export interface Design {
  schemaVersion: 1; projectId: string; revision: number; sizeMm: { width: number; height: number };
  lockAspect: boolean; fabricPreset: FabricPreset; geometry: { viewBox: [number, number, number, number] };
  palette: { id: string; hex: string; threadCode: string | null }[]; regions: Region[]; warnings: string[];
  source?: { filename: string };
}
export interface Job {
  jobId: string; projectId: string; kind: "analyze" | "compile" | "export"; revision: number | null;
  status: JobStatus; progress: number; errorCode: string | null; errorMessage: string | null;
  result: Record<string, unknown> | null;
}
export interface Artifact { id: string; kind: string; revision: number; sizeBytes: number; createdAt: string }
export interface ProjectDetail { project: Project; design: Design | null; artifacts: Artifact[]; jobs: Job[] }
export interface Stitches {
  revision: number; widthMm: number; heightMm: number; colors: string[]; points: number[];
  summary: { stitches: number; jumps: number; trims: number; color_changes: number; color_blocks: number; width_mm: number; height_mm: number };
}

export class ApiError extends Error {
  constructor(public status: number, public code: string) { super(code); }
}

export function getDevUser(): string | null {
  try { return localStorage.getItem(USER_KEY); } catch { return null; }
}
export function setDevUser(name: string | null) {
  try { if (name) localStorage.setItem(USER_KEY, name); else localStorage.removeItem(USER_KEY); } catch { /* storage blocked */ }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const user = getDevUser();
  if (user) headers.set("X-Dev-User", user);
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    let code = `http_${res.status}`;
    try {
      const body = await res.json();
      code = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? "invalid_input" : code;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, code);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  listProjects: () => request<Project[]>("/api/v1/projects"),
  createProject: (b: { name: string; widthMm: number; heightMm?: number; lockAspect: boolean; fabricPreset: FabricPreset }) =>
    request<Project>("/api/v1/projects", { method: "POST", body: json(b) }),
  getProject: (id: string) => request<ProjectDetail>(`/api/v1/projects/${id}`),
  uploadUrl: (id: string, file: File) => request<{ uploadId: string; uploadUrl: string }>(
    `/api/v1/projects/${id}/upload-url`,
    { method: "POST", body: json({ filename: file.name, contentType: file.type || "image/svg+xml", sizeBytes: file.size }) }),
  async putUpload(url: string, file: File) {
    const res = await fetch(url, { method: "PUT", body: file });
    if (!res.ok) throw new ApiError(res.status, res.status === 413 ? "file_too_large" : "upload_failed");
  },
  analyze: (id: string, uploadId: string) => request<Job>(`/api/v1/projects/${id}/analyze`, { method: "POST", body: json({ uploadId }) }),
  patchDesign: (id: string, b: { baseRevision: number; sizeMm?: { width: number; height?: number }; lockAspect?: boolean; fabricPreset?: FabricPreset }) =>
    request<{ revision: number; design: Design }>(`/api/v1/projects/${id}/design`, { method: "PATCH", body: json(b) }),
  compile: (id: string, revision: number) => request<Job>(`/api/v1/projects/${id}/compile`, { method: "POST", body: json({ revision }) }),
  exportZip: (id: string, revision: number) => request<Job>(`/api/v1/projects/${id}/exports`, { method: "POST", body: json({ revision }) }),
  stitches: (id: string, revision?: number) =>
    request<Stitches>(`/api/v1/projects/${id}/stitches${revision ? `?revision=${revision}` : ""}`),
  downloadUrl: (id: string, artifactId: string) => request<{ url: string }>(`/api/v1/projects/${id}/exports/${artifactId}`),
  job: (jobId: string) => request<Job>(`/api/v1/jobs/${jobId}`),
};

export async function waitForJob(job: Job, onUpdate?: (j: Job) => void, timeoutMs = 10 * 60_000): Promise<Job> {
  const start = Date.now();
  let current = job;
  while (current.status !== "ready" && current.status !== "failed") {
    if (Date.now() - start > timeoutMs) throw new ApiError(0, "job_timeout");
    await new Promise(r => setTimeout(r, 800));
    current = await api.job(job.jobId);
    onUpdate?.(current);
  }
  return current;
}

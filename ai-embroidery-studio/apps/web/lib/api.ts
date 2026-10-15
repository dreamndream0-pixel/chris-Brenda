// Typed client for the FastAPI backend (services/api).
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
import { authHeaders } from "./auth";

export type FabricPreset = "woven_cotton" | "knit_cotton" | "canvas" | "other";
export type JobStatus = "queued" | "preprocessing" | "planning" | "compiling" | "validating" | "exporting" | "ready" | "failed";

export interface Project {
  id: string; name: string; fabricPreset: FabricPreset; status: "draft" | "awaiting_test_sew" | "accepted";
  currentRevision: number; compiledRevision: number | null; widthMm: number | null; heightMm: number | null;
  colorCount: number | null; stitchCount: number | null; createdAt: string; updatedAt: string;
}
export type StitchType = "fill" | "running" | "satin";
export type DetailLevel = "standard" | "fine" | "ultra";
export type ContourDetail = "preserve" | "balanced" | "clean";
export interface RegionPlan {
  source: "rules" | "ai"; suggested: StitchType; applied: StitchType; reason: string; needsReview: boolean;
  confidence: number | null; aiReason: string | null; override: string | null; manual?: boolean;
}
export interface Region {
  id: string; name: string; colorId: string; order: number; stitchType: StitchType;
  params: Record<string, number | boolean>; warnings: string[]; hidden?: boolean;
  shape?: "area" | "line"; runningPath?: "centerline" | "outline"; plan?: RegionPlan;
  svgPath: string; bbox?: [number, number, number, number]; strokeWidthUnits?: number;
}
export interface Design {
  schemaVersion: 1; projectId: string; revision: number; sizeMm: { width: number; height: number };
  lockAspect: boolean; fabricPreset: FabricPreset; detailLevel?: DetailLevel; geometry: { viewBox: [number, number, number, number] };
  palette: { id: string; hex: string; threadCode: string | null }[]; regions: Region[]; warnings: string[];
  source?: { filename: string; uploadId: string };
  raster?: { pixels: [number, number]; colors: string[]; backgroundHex: string | null; autoColors: boolean;
    analysisVersion?: number; detailMode?: ContourDetail; minFeatureMm?: number; removedFraction?: number;
    options?: AnalyzeOptions };
  planner?: { ai: boolean; model?: string; colorChangesBefore?: number; colorChangesAfter?: number };
  aiReview?: { summary: string; risks: { code: string; regionIds: string[]; message: string }[]; model: string; basedOnRevision: number };
}
export interface AppConfig { aiEnabled: boolean; aiModel: string | null; authMode: "dev" | "supabase" }
export interface AnalyzeOptions { colors?: number | null; removeBackground?: boolean; backgroundHex?: string | null;
  backgroundScope?: "edge" | "all"; detailMode?: ContourDetail; widthMm?: number; fitHeightMm?: number }
export interface RegionPatch { id: string; stitchType?: StitchType; colorId?: string; hidden?: boolean }
export interface Job {
  jobId: string; projectId: string; kind: "analyze" | "compile" | "export" | "ai_plan"; revision: number | null;
  status: JobStatus; progress: number; errorCode: string | null; errorMessage: string | null;
  result: Record<string, unknown> | null; createdAt?: string | null; updatedAt?: string | null;
}
export interface Artifact { id: string; kind: string; revision: number; sizeBytes: number; createdAt: string }
export interface ProjectDetail {
  project: Project; design: Design | null; artifacts: Artifact[]; jobs: Job[];
  allowedStitches: Record<string, Record<StitchType, string | null>>;
}
export interface Stitches {
  revision: number; widthMm: number; heightMm: number; colors: string[]; points: number[];
  summary: { stitches: number; jumps: number; trims: number; color_changes: number; color_blocks: number; width_mm: number; height_mm: number };
}

export class ApiError extends Error {
  constructor(public status: number, public code: string) { super(code); }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  for (const [k, v] of Object.entries(await authHeaders())) headers.set(k, v);
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

export const ACCEPTED = { ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg" } as const;
export function contentTypeFor(file: File): string {
  const ext = file.name.toLowerCase().match(/\.[a-z]+$/)?.[0] as keyof typeof ACCEPTED | undefined;
  return (ext && ACCEPTED[ext]) || file.type;
}
export const isRaster = (file: File) => contentTypeFor(file) !== "image/svg+xml";

export const api = {
  listProjects: () => request<Project[]>("/api/v1/projects"),
  createProject: (b: { name: string; widthMm: number; heightMm?: number; lockAspect: boolean; fabricPreset: FabricPreset }) =>
    request<Project>("/api/v1/projects", { method: "POST", body: json(b) }),
  getProject: (id: string) => request<ProjectDetail>(`/api/v1/projects/${id}`),
  uploadUrl: (id: string, file: File) => request<{ uploadId: string; uploadUrl: string; headers: Record<string, string> }>(
    `/api/v1/projects/${id}/upload-url`,
    { method: "POST", body: json({ filename: file.name, contentType: contentTypeFor(file), sizeBytes: file.size }) }),
  async putUpload(url: string, file: File, headers: Record<string, string> = {}) {
    // Local: the API's own upload endpoint. Supabase: a signed upload URL straight into the private bucket.
    const res = await fetch(url, { method: "PUT", body: file, headers });
    if (!res.ok) throw new ApiError(res.status, res.status === 413 ? "file_too_large" : "upload_failed");
  },
  analyze: (id: string, uploadId: string, opts: AnalyzeOptions = {}) =>
    request<Job>(`/api/v1/projects/${id}/analyze`, { method: "POST", body: json({ uploadId, ...opts }) }),
  previews: (id: string, revision: number) =>
    request<Partial<Record<"source_preview" | "quantized_preview", string>>>(`/api/v1/projects/${id}/previews?revision=${revision}`),
  patchDesign: (id: string, b: { baseRevision: number; sizeMm?: { width: number; height?: number }; lockAspect?: boolean;
    fabricPreset?: FabricPreset; detailLevel?: DetailLevel; regions?: RegionPatch[]; palette?: { id: string; hex: string }[] }) =>
    request<{ revision: number; design: Design }>(`/api/v1/projects/${id}/design`, { method: "PATCH", body: json(b) }),
  compile: (id: string, revision: number) => request<Job>(`/api/v1/projects/${id}/compile`, { method: "POST", body: json({ revision }) }),
  exportZip: (id: string, revision: number) => request<Job>(`/api/v1/projects/${id}/exports`, { method: "POST", body: json({ revision }) }),
  stitches: (id: string, revision?: number) =>
    request<Stitches>(`/api/v1/projects/${id}/stitches${revision ? `?revision=${revision}` : ""}`),
  downloadUrl: (id: string, artifactId: string) => request<{ url: string }>(`/api/v1/projects/${id}/exports/${artifactId}`),
  job: (jobId: string) => request<Job>(`/api/v1/jobs/${jobId}`),
  config: () => request<AppConfig>("/api/v1/config"),
  aiPlan: (id: string, revision: number) => request<Job>(`/api/v1/projects/${id}/ai-plan`, { method: "POST", body: json({ revision }) }),
};

// Generous: free hosting tiers (e.g. 0.1 vCPU) can take many minutes per compile.
export const ACTIVE_JOB_STATUSES: JobStatus[] = ["queued", "preprocessing", "planning", "compiling", "validating", "exporting"];

// Jobs run on the server, so the page only has to keep asking. Phones pause pages in the
// background and drop connections: network errors are retried, and the page asks again
// right away when it becomes visible.
export async function waitForJob(job: Job, onUpdate?: (j: Job) => void, timeoutMs = 30 * 60_000): Promise<Job> {
  const start = Date.now();
  let current = job;
  let failures = 0;
  while (current.status !== "ready" && current.status !== "failed") {
    if (Date.now() - start > timeoutMs) throw new ApiError(0, "job_timeout");
    const delay = failures ? Math.min(15_000, 1000 * 2 ** failures) : Date.now() - start > 60_000 ? 3000 : 800;
    await sleepOrVisible(delay);
    try {
      current = await api.job(job.jobId);
      failures = 0;
      onUpdate?.(current);
    } catch (e) {
      // 4xx other than timeouts are real answers (e.g. the job is gone); everything else is retried.
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 408 && e.status !== 429) throw e;
      failures++;
    }
  }
  return current;
}

function sleepOrVisible(ms: number): Promise<void> {
  return new Promise(resolve => {
    const done = () => { clearTimeout(t); document.removeEventListener("visibilitychange", onVis); resolve(); };
    const onVis = () => { if (document.visibilityState === "visible") done(); };
    const t = setTimeout(done, ms);
    document.addEventListener("visibilitychange", onVis);
  });
}

// fetch() throws TypeError when the connection drops (e.g. the phone locks); retry those.
export async function withRetry<T>(fn: () => Promise<T>, attempts = 4): Promise<T> {
  for (let i = 0; ; i++) {
    try { return await fn(); } catch (e) {
      const transient = !(e instanceof ApiError) || e.status === 0 || e.status >= 500;
      if (!transient || i >= attempts - 1) throw e;
      await sleepOrVisible(1000 * 2 ** i);
    }
  }
}

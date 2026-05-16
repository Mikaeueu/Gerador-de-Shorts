// ============================================================
// Types do dominio - espelham os Pydantic models do backend
// (src/api/schemas.py). Mantenha em sincronia.
// ============================================================

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface JobParams {
  whisper_model: string;
  language: string | null;
  refine: boolean;
  refine_context: string;
  template: string;
  // null = usa smart default do template (15-60s pra gameplay, 45-90s pra pregação, etc.)
  min_clip_seconds: number | null;
  max_clip_seconds: number | null;
  max_clips: number | null;
  min_score: number | null;
  font_size: number;
  words_per_chunk: number;
  fade_out_seconds: number;
}

export interface Job {
  id: string;
  status: JobStatus;
  source: string;
  source_kind: "url" | "upload" | "local";
  params: JobParams;
  stage: string | null;
  message: string | null;
  percent: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  clips: string[];
  error: string | null;
}

export interface ProgressMessage {
  job_id: string;
  status: JobStatus;
  stage: string;
  message: string;
  percent: number;
  timestamp: string;
}

export interface ClipInfo {
  index: number;
  filename: string;
  url: string;
}

export interface ClipsResponse {
  job_id: string;
  status: JobStatus;
  clips: ClipInfo[];
}

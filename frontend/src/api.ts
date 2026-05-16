// ============================================================
// Cliente HTTP + WebSocket pra API FastAPI.
//
// Em DEV: usa proxy do Vite (/api -> http://127.0.0.1:8000)
// Em PROD: precisa setar VITE_API_BASE_URL ou ajustar.
// ============================================================

import type { Job, JobParams, ClipsResponse } from "./types";

// Em dev, o Vite proxy redireciona /api e /ws.
// Em prod, vamos precisar configurar isso direto.
const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";
const WS_BASE = import.meta.env.VITE_WS_BASE_URL || "/ws";

/**
 * Wrapper minimo do fetch que:
 * - Levanta erro com mensagem descritiva em status >= 400
 * - Parseia JSON automaticamente
 */
async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let errMsg = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      errMsg = data.detail || errMsg;
    } catch {
      // ignora se nao parseou JSON
    }
    throw new Error(errMsg);
  }
  return res.json();
}

// ============================================================
// Endpoints
// ============================================================

export const api = {
  /** Cria job a partir de URL (YouTube, etc.) */
  async createJobFromUrl(source: string, params?: Partial<JobParams>): Promise<Job> {
    return apiFetch<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify({ source, params }),
    });
  },

  /** Cria job a partir de upload de arquivo */
  async createJobFromUpload(file: File, params?: Partial<JobParams>): Promise<Job> {
    const formData = new FormData();
    formData.append("file", file);
    if (params) {
      formData.append("params_json", JSON.stringify(params));
    }
    // Nao usa apiFetch pq fetch com FormData nao deve setar Content-Type
    const res = await fetch(`${API_BASE}/jobs/upload`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  /** Lista jobs (mais recentes primeiro) */
  async listJobs(limit: number = 50): Promise<Job[]> {
    return apiFetch<Job[]>(`/jobs?limit=${limit}`);
  },

  /** Busca job por id */
  async getJob(id: string): Promise<Job> {
    return apiFetch<Job>(`/jobs/${id}`);
  },

  /** Lista clips finais de um job (com URLs de download) */
  async getJobClips(id: string): Promise<ClipsResponse> {
    return apiFetch<ClipsResponse>(`/jobs/${id}/clips`);
  },

  /**
   * Apaga um job e todos os arquivos relacionados (clips, caches).
   * Se o job estiver rodando, sinaliza cancelamento antes de apagar.
   */
  async deleteJob(id: string): Promise<void> {
    const res = await fetch(`${API_BASE}/jobs/${id}`, { method: "DELETE" });
    if (!res.ok && res.status !== 204) {
      throw new Error(`Falha ao deletar job: HTTP ${res.status}`);
    }
  },

  /** Cancela job em execução (mas mantem JSON e arquivos parciais). */
  async cancelJob(id: string): Promise<{ cancelled: boolean }> {
    return apiFetch(`/jobs/${id}/cancel`, { method: "POST" });
  },

  /**
   * URL absoluta pra baixar/preview um clip.
   * Use direto em <video src> ou <a href>.
   */
  clipUrl(jobId: string, clipIndex: number): string {
    return `${API_BASE}/jobs/${jobId}/clips/${clipIndex}`;
  },

  /** URL do WebSocket pra acompanhar progresso de um job */
  wsUrl(jobId: string): string {
    // No dev (proxy), o vite ja sabe lidar com ws:// via proxy.
    // Em prod, derivamos o protocolo do location.
    if (WS_BASE.startsWith("ws")) {
      return `${WS_BASE}/jobs/${jobId}/ws`;
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}${WS_BASE}/jobs/${jobId}/ws`;
  },
};

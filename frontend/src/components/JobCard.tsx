// ============================================================
// Card de um job - 3 estados visuais (queued, running, done/failed).
// Job em RUNNING usa hook useJobProgress pra atualizar em tempo real via WS.
// Job em DONE expande pra mostrar grid de clips (componente filho).
// ============================================================

import { useState } from "react";
import { Check, Clock, Layers, Trash2, Upload as UploadIcon, X, Youtube } from "lucide-react";
import { useJobProgress } from "../useJobProgress";
import { api } from "../api";
import type { Job } from "../types";
import { ClipsGrid } from "./ClipsGrid";

interface JobCardProps {
  job: Job;
  onDeleted: (jobId: string) => void;
}

const statusStyles = {
  running: { bg: "rgba(245, 166, 35, 0.10)", color: "var(--color-status-running)", label: "Processando" },
  done: { bg: "rgba(74, 222, 128, 0.10)", color: "var(--color-status-done)", label: "Pronto" },
  failed: { bg: "rgba(239, 68, 68, 0.10)", color: "var(--color-status-failed)", label: "Erro" },
  queued: { bg: "rgba(148, 163, 184, 0.10)", color: "var(--color-status-queued)", label: "Na fila" },
  cancelled: { bg: "rgba(148, 163, 184, 0.10)", color: "var(--color-status-queued)", label: "Cancelado" },
};

export function JobCard({ job, onDeleted }: JobCardProps) {
  const [deleting, setDeleting] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  // Conecta no WS apenas se job esta running ou queued (pra economizar conexoes)
  const liveJobId = job.status === "running" || job.status === "queued" ? job.id : null;
  const { progress } = useJobProgress(liveJobId);

  const handleDelete = async () => {
    if (deleting) return;
    if (!confirm(`Apagar este job e todos os clips gerados?\n\nIsso não pode ser desfeito.`)) {
      return;
    }
    setDeleting(true);
    try {
      // Se estiver rodando, o backend cancela automaticamente antes de apagar.
      await api.deleteJob(job.id);
      onDeleted(job.id);
    } catch (e) {
      alert(`Falha ao apagar: ${e instanceof Error ? e.message : String(e)}`);
      setDeleting(false);
    }
  };

  const handleCancel = async () => {
    if (cancelling) return;
    setCancelling(true);
    try {
      await api.cancelJob(job.id);
      // Backend muda status pra "cancelled" em ate alguns segundos.
      // O polling de 5s no App.tsx ja vai pegar.
    } catch (e) {
      alert(`Falha ao cancelar: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCancelling(false);
    }
  };

  // Mescla estado do disco com mensagem live (live tem prioridade)
  const currentStage = progress?.stage || job.stage || "";
  const currentMessage = progress?.message || job.message || "";
  const currentPercent = progress?.percent ?? job.percent;
  const currentStatus = progress?.status || job.status;

  const status = statusStyles[currentStatus];

  // Calcula ETA pra jobs em RUNNING via extrapolacao linear:
  //   ETA = (elapsed / percent) * (100 - percent)
  // So mostra se percent > 5 (evita estimativas absurdas no inicio).
  const eta = computeETA(job.started_at, currentPercent, currentStatus);

  // Titulo curto: extrai do source (URL pega ultima parte, path pega filename)
  const title = extractTitle(job.source);

  return (
    <article
      className="rounded-xl border p-5 transition-colors"
      style={{
        backgroundColor: "var(--color-bg-secondary)",
        borderColor: "var(--color-border-subtle)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = "var(--color-bg-tertiary)";
        e.currentTarget.style.borderColor = "var(--color-border-medium)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = "var(--color-bg-secondary)";
        e.currentTarget.style.borderColor = "var(--color-border-subtle)";
      }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div
            className="mb-1 truncate text-sm font-medium"
            style={{ color: "var(--color-text-primary)" }}
          >
            {title}
          </div>
          <JobMeta job={job} />
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          <span
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider"
            style={{ backgroundColor: status.bg, color: status.color }}
          >
            {currentStatus === "running" && <span className="spinner pulse-soft" />}
            {currentStatus === "done" && <Check size={12} strokeWidth={2.5} />}
            {currentStatus === "failed" && <X size={12} strokeWidth={2.5} />}
            {currentStatus === "cancelled" && <X size={12} strokeWidth={2.5} />}
            {status.label}
          </span>

          {/* Cancelar: so aparece em jobs em execucao */}
          {currentStatus === "running" && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); handleCancel(); }}
              disabled={cancelling}
              className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors disabled:opacity-50"
              style={{
                borderColor: "var(--color-border-medium)",
                color: "var(--color-text-secondary)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "var(--color-status-failed)";
                e.currentTarget.style.borderColor = "var(--color-status-failed)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "var(--color-text-secondary)";
                e.currentTarget.style.borderColor = "var(--color-border-medium)";
              }}
              title="Cancelar processamento"
            >
              {cancelling ? <span className="spinner" /> : <X size={12} strokeWidth={2.5} />}
              Cancelar
            </button>
          )}

          {/* Apagar: aparece em qualquer estado */}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); handleDelete(); }}
            disabled={deleting}
            className="inline-flex items-center rounded-md p-1.5 transition-colors disabled:opacity-50"
            style={{ color: "var(--color-text-tertiary)" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--color-status-failed)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--color-text-tertiary)")}
            title="Apagar job e arquivos"
            aria-label="Apagar job"
          >
            {deleting ? <span className="spinner" /> : <Trash2 size={14} />}
          </button>
        </div>
      </div>

      {/* Progress bar - apenas em running */}
      {currentStatus === "running" && (
        <div
          className="mt-3.5 border-t pt-3.5"
          style={{ borderColor: "var(--color-border-subtle)" }}
        >
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="inline-flex items-center gap-2" style={{ color: "var(--color-text-secondary)" }}>
              <Layers size={12} />
              {currentMessage || stageLabel(currentStage)}
            </span>
            <span
              className="inline-flex items-center gap-3"
              style={{ color: "var(--color-text-tertiary)", fontVariantNumeric: "tabular-nums" }}
            >
              {eta ? (
                <span>~ {eta} restantes</span>
              ) : (
                // Sem ETA ainda (percent < 5 ou sem started_at): indica
                // que está processando com os 3 pontinhos piscando.
                <span>
                  Calculando tempo
                  <span className="dots-loading-dot">.</span>
                  <span className="dots-loading-dot">.</span>
                  <span className="dots-loading-dot">.</span>
                </span>
              )}
              <span>{currentPercent}%</span>
            </span>
          </div>
          <div
            className="h-1 overflow-hidden rounded-full"
            style={{ backgroundColor: "var(--color-bg-tertiary)" }}
          >
            <div
              className="h-full rounded-full transition-[width] duration-300 ease-out"
              style={{ width: `${currentPercent}%`, backgroundColor: "var(--color-accent)" }}
            />
          </div>
        </div>
      )}

      {/* Clips grid - apenas em done */}
      {currentStatus === "done" && job.clips.length > 0 && (
        <ClipsGrid jobId={job.id} clipCount={job.clips.length} clipFilenames={job.clips} />
      )}

      {/* Mensagem de erro */}
      {currentStatus === "failed" && job.error && (
        <div
          className="mt-3 rounded-md border p-3 font-mono text-[12px]"
          style={{
            backgroundColor: "rgba(239, 68, 68, 0.05)",
            borderColor: "rgba(239, 68, 68, 0.2)",
            color: "var(--color-status-failed)",
          }}
        >
          {job.message || job.error.split("\n")[0]}
        </div>
      )}
    </article>
  );
}

function JobMeta({ job }: { job: Job }) {
  const isUrl = job.source_kind === "url";
  return (
    <div
      className="flex items-center gap-3 text-xs"
      style={{ color: "var(--color-text-tertiary)" }}
    >
      <span className="inline-flex items-center gap-1">
        <Clock size={12} />
        {formatRelativeTime(job.created_at)}
      </span>
      <span style={{ opacity: 0.5 }}>·</span>
      <span className="inline-flex items-center gap-1">
        {isUrl ? <Youtube size={12} /> : <UploadIcon size={12} />}
        {isUrl ? "YouTube" : "Upload local"}
      </span>
      {job.clips.length > 0 && (
        <>
          <span style={{ opacity: 0.5 }}>·</span>
          <span>{job.clips.length} clips</span>
        </>
      )}
    </div>
  );
}

// ============================================================
// Helpers
// ============================================================

function extractTitle(source: string): string {
  // Se for URL, mostra o URL truncado
  if (/^https?:\/\//.test(source)) {
    try {
      const u = new URL(source);
      return `${u.hostname}${u.pathname}${u.search}`.slice(0, 80);
    } catch {
      return source;
    }
  }
  // Senao e path - pega so o filename
  const parts = source.split(/[\\/]/);
  return parts[parts.length - 1] || source;
}

function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "agora mesmo";
  if (diffMin < 60) return `há ${diffMin} min`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `há ${diffH}h`;
  const diffD = Math.floor(diffH / 24);
  return `há ${diffD}d`;
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    download: "Baixando vídeo",
    transcribe: "Transcrevendo áudio",
    refine: "Refinando transcrição",
    analyze: "Analisando trechos virais",
    crop: "Reenquadrando clips verticais",
    caption: "Queimando legendas",
    done: "Concluído",
    error: "Erro",
    cancelled: "Cancelado",
  };
  return labels[stage] || stage;
}

/**
 * Estima quanto tempo falta pro job terminar, baseado em quanto progrediu.
 *
 * Fórmula simples (extrapolação linear):
 *   elapsed = agora - started_at
 *   ETA = (elapsed / percent) * (100 - percent)
 *
 * Só faz sentido pra jobs em running com percent > 5 (antes disso a
 * estimativa fica volátil demais).
 *
 * Returns:
 *   String tipo "2m 30s", "45s", ou null se não dá pra estimar.
 */
function computeETA(
  startedAt: string | null,
  percent: number,
  status: string,
): string | null {
  if (status !== "running" || !startedAt || percent < 5 || percent >= 100) {
    return null;
  }
  const startMs = new Date(startedAt).getTime();
  const elapsedSec = (Date.now() - startMs) / 1000;
  if (!Number.isFinite(elapsedSec) || elapsedSec <= 0) return null;
  const totalEstimateSec = (elapsedSec / percent) * 100;
  const remainingSec = Math.max(0, totalEstimateSec - elapsedSec);
  return formatDuration(remainingSec);
}

function formatDuration(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const remainingS = s % 60;
  if (m < 60) return remainingS > 0 ? `${m}m ${remainingS}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const remainingM = m % 60;
  return remainingM > 0 ? `${h}h ${remainingM}m` : `${h}h`;
}

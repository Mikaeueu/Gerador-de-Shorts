// ============================================================
// Grid de clips finais (vertical 9:16) com player inline ao clicar.
// ============================================================

import { useState } from "react";
import { Download, Play, X } from "lucide-react";
import { api } from "../api";

interface ClipsGridProps {
  jobId: string;
  clipCount: number;
  clipFilenames: string[];
}

/**
 * Extrai só o nome do clip do path completo.
 * O backend manda "<subpasta_do_video>/<titulo_do_clip>.mp4" — pra UI
 * queremos mostrar só o título, sem o prefixo da pasta.
 */
function clipDisplayName(filename: string): string {
  const parts = filename.split("/");
  return parts[parts.length - 1] || filename;
}

// Cores de fundo aleatórias mas determinísticas pros placeholders.
// Index → gradient pra dar variedade visual antes do video carregar.
const PLACEHOLDER_GRADIENTS = [
  "linear-gradient(135deg, #2A2A35 0%, #16161B 100%)",
  "linear-gradient(135deg, #2D2438 0%, #18121F 100%)",
  "linear-gradient(135deg, #1F2D38 0%, #11171F 100%)",
  "linear-gradient(135deg, #382D24 0%, #1F1812 100%)",
  "linear-gradient(135deg, #243828 0%, #121F14 100%)",
];

export function ClipsGrid({ jobId, clipCount, clipFilenames }: ClipsGridProps) {
  const [expandedClip, setExpandedClip] = useState<number | null>(null);

  return (
    <>
      <div
        className="mt-4 grid gap-3 border-t pt-4"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
          borderColor: "var(--color-border-subtle)",
        }}
      >
        {Array.from({ length: clipCount }, (_, i) => {
          const index = i + 1;
          const filename = clipFilenames[i] || `Clip ${index}`;
          return (
            <button
              key={index}
              type="button"
              onClick={() => setExpandedClip(index)}
              className="group relative aspect-[9/16] cursor-pointer overflow-hidden rounded-md border transition-transform hover:-translate-y-0.5"
              style={{
                background: PLACEHOLDER_GRADIENTS[i % PLACEHOLDER_GRADIENTS.length],
                borderColor: "var(--color-border-subtle)",
              }}
            >
              {/* Play overlay */}
              <div
                className="absolute inset-0 flex items-center justify-center"
                style={{
                  background:
                    "linear-gradient(180deg, transparent 0%, rgba(0,0,0,0.6) 100%)",
                }}
              >
                <div
                  className="flex h-9 w-9 items-center justify-center rounded-full transition-transform group-hover:scale-110"
                  style={{ backgroundColor: "rgba(255,255,255,0.95)", color: "#08080B" }}
                >
                  <Play size={16} fill="currentColor" strokeWidth={0} />
                </div>
              </div>

              {/* Index badge */}
              <div
                className="absolute right-2 top-2 rounded px-1.5 py-0.5 text-[11px] font-semibold text-white backdrop-blur"
                style={{ backgroundColor: "rgba(0,0,0,0.7)" }}
              >
                #{index}
              </div>

              {/* Filename no rodape */}
              <div className="absolute bottom-2 left-2 right-2">
                <div
                  className="line-clamp-2 text-[11px] font-medium leading-tight text-white"
                  style={{ textShadow: "0 1px 2px rgba(0,0,0,0.8)" }}
                >
                  {clipDisplayName(filename).replace(/\.mp4$/, "").slice(-50)}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Modal de player */}
      {expandedClip !== null && (
        <ClipPlayer
          jobId={jobId}
          clipIndex={expandedClip}
          filename={clipDisplayName(clipFilenames[expandedClip - 1] || `Clip ${expandedClip}`)}
          onClose={() => setExpandedClip(null)}
        />
      )}
    </>
  );
}

function ClipPlayer({
  jobId,
  clipIndex,
  filename,
  onClose,
}: {
  jobId: string;
  clipIndex: number;
  filename: string;
  onClose: () => void;
}) {
  const videoUrl = api.clipUrl(jobId, clipIndex);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.85)", backdropFilter: "blur(8px)" }}
      onClick={onClose}
    >
      <div
        className="flex max-h-full flex-col items-center gap-3"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex w-full max-w-md items-center justify-between text-sm">
          <span
            className="truncate"
            style={{ color: "var(--color-text-secondary)" }}
          >
            {filename}
          </span>
          <div className="flex items-center gap-2">
            <a
              href={videoUrl}
              download={filename}
              className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px] transition-colors"
              style={{
                borderColor: "var(--color-border-medium)",
                color: "var(--color-text-secondary)",
              }}
              onClick={(e) => e.stopPropagation()}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "var(--color-text-primary)";
                e.currentTarget.style.backgroundColor = "var(--color-bg-tertiary)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "var(--color-text-secondary)";
                e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              <Download size={12} />
              Baixar
            </a>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1.5 transition-colors"
              style={{ color: "var(--color-text-secondary)" }}
              aria-label="Fechar"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Video player */}
        <video
          src={videoUrl}
          controls
          autoPlay
          className="max-h-[80vh] rounded-lg"
          style={{
            aspectRatio: "9 / 16",
            backgroundColor: "var(--color-bg-secondary)",
          }}
        />
      </div>
    </div>
  );
}

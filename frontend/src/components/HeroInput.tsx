// ============================================================
// Input principal: URL ou upload + botao Gerar.
// Tambem mostra settings collapsibles.
// ============================================================

import { useRef, useState } from "react";
import { ArrowRight, ChevronDown, ChevronUp, Link2, Upload } from "lucide-react";
import { api } from "../api";
import type { Job, JobParams } from "../types";

interface HeroInputProps {
  onJobCreated: (job: Job) => void;
}

export function HeroInput({ onJobCreated }: HeroInputProps) {
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [showSettings, setShowSettings] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Settings - max_clips fica null por default pra usar o smart default do template
  // (cada template tem seus parametros ideais ja calibrados no backend).
  const [params, setParams] = useState<Partial<JobParams>>({
    whisper_model: "small",
    language: "pt",
    max_clips: null,
    template: "evangelical_preaching",
  });

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleUrlSubmit = async () => {
    if (!url.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.createJobFromUrl(url.trim(), params);
      setUrl("");
      onJobCreated(job);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.createJobFromUpload(file, params);
      onJobCreated(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <section className="mb-12">
      <h1
        className="mb-2 text-3xl font-semibold"
        style={{ letterSpacing: "-0.02em", lineHeight: 1.2 }}
      >
        Transforme vídeos longos em Shorts virais
      </h1>
      <p className="mb-8 text-[15px]" style={{ color: "var(--color-text-secondary)" }}>
        Cole um link do YouTube ou faça upload de um vídeo local.
      </p>

      <div
        className="flex items-center gap-1 rounded-xl border p-1.5"
        style={{
          backgroundColor: "var(--color-bg-secondary)",
          borderColor: "var(--color-border-subtle)",
        }}
      >
        <span className="flex items-center pl-3.5 pr-2" style={{ color: "var(--color-text-tertiary)" }}>
          <Link2 size={18} strokeWidth={2} />
        </span>
        <input
          type="text"
          className="h-11 flex-1 bg-transparent px-1 py-3 text-[15px] outline-none placeholder:text-[var(--color-text-tertiary)]"
          placeholder="https://www.youtube.com/watch?v=..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleUrlSubmit()}
          disabled={submitting}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={submitting}
          className="inline-flex h-9 items-center gap-1.5 rounded-md border px-3.5 text-[13px] transition-colors disabled:opacity-50"
          style={{
            borderColor: "var(--color-border-subtle)",
            color: "var(--color-text-secondary)",
            backgroundColor: "transparent",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = "var(--color-bg-tertiary)";
            e.currentTarget.style.color = "var(--color-text-primary)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = "transparent";
            e.currentTarget.style.color = "var(--color-text-secondary)";
          }}
        >
          <Upload size={14} strokeWidth={2} />
          Upload
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="video/*"
          className="hidden"
          onChange={handleFileChange}
        />
        <button
          type="button"
          onClick={handleUrlSubmit}
          disabled={!url.trim() || submitting}
          className="inline-flex h-9 items-center gap-1.5 rounded-md px-4 text-[13px] font-medium text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60"
          style={{ backgroundColor: "var(--color-accent)" }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--color-accent-hover)")}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "var(--color-accent)")}
        >
          {submitting ? <span className="spinner" /> : (
            <>
              Gerar Shorts
              <ArrowRight size={14} strokeWidth={2} />
            </>
          )}
        </button>
      </div>

      {error && (
        <p className="mt-3 text-[13px]" style={{ color: "var(--color-status-failed)" }}>
          Erro: {error}
        </p>
      )}

      <button
        type="button"
        onClick={() => setShowSettings((v) => !v)}
        className="mt-4 inline-flex items-center gap-1.5 py-1 text-[13px] transition-colors"
        style={{ color: "var(--color-text-tertiary)" }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "var(--color-text-secondary)")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "var(--color-text-tertiary)")}
      >
        {showSettings ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        Configurações avançadas
      </button>

      {showSettings && <SettingsGrid params={params} onChange={setParams} />}
    </section>
  );
}

function SettingsGrid({
  params,
  onChange,
}: {
  params: Partial<JobParams>;
  onChange: (p: Partial<JobParams>) => void;
}) {
  return (
    <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
      <SettingSelect
        label="Modelo Whisper"
        value={params.whisper_model || "small"}
        options={[
          { value: "tiny", label: "tiny (rápido)" },
          { value: "base", label: "base" },
          { value: "small", label: "small (recomendado)" },
          { value: "medium", label: "medium" },
        ]}
        onChange={(v) => onChange({ ...params, whisper_model: v })}
      />
      <SettingSelect
        label="Idioma"
        value={params.language || ""}
        options={[
          { value: "", label: "Auto-detect" },
          { value: "pt", label: "Português" },
          { value: "en", label: "English" },
          { value: "es", label: "Español" },
        ]}
        onChange={(v) => onChange({ ...params, language: v || null })}
      />
      <SettingMaxClips
        label="Máx. clips"
        value={params.max_clips ?? null}
        template={params.template || "evangelical_preaching"}
        onChange={(v) => onChange({ ...params, max_clips: v })}
      />
      <SettingSelect
        label="Template viral"
        value={params.template || "evangelical_preaching"}
        options={[
          { value: "evangelical_preaching", label: "Pregação evangélica" },
          { value: "gameplay_humor", label: "Gameplay (humor)" },
          { value: "generic", label: "Genérico" },
        ]}
        onChange={(v) => onChange({ ...params, template: v })}
      />
    </div>
  );
}

function SettingSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void;
}) {
  return (
    <div
      className="rounded-md border px-3.5 py-3"
      style={{
        backgroundColor: "var(--color-bg-secondary)",
        borderColor: "var(--color-border-subtle)",
      }}
    >
      <label
        className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider"
        style={{ color: "var(--color-text-tertiary)" }}
      >
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-transparent text-[13px] font-medium outline-none"
        style={{ color: "var(--color-text-primary)" }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} style={{ backgroundColor: "var(--color-bg-elevated)" }}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// Smart defaults por template - SINCRONIZAR com src/analyzer/prompts.py::TEMPLATE_DEFAULTS
const TEMPLATE_MAX_CLIPS: Record<string, number> = {
  evangelical_preaching: 5,
  gameplay_humor: 8,
  generic: 5,
};

function SettingMaxClips({
  label,
  value,
  template,
  onChange,
}: {
  label: string;
  value: number | null;
  template: string;
  onChange: (v: number | null) => void;
}) {
  // null = usa default do template; placeholder mostra qual valor sera aplicado
  const templateDefault = TEMPLATE_MAX_CLIPS[template] ?? 5;
  return (
    <div
      className="rounded-md border px-3.5 py-3"
      style={{
        backgroundColor: "var(--color-bg-secondary)",
        borderColor: "var(--color-border-subtle)",
      }}
    >
      <label
        className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider"
        style={{ color: "var(--color-text-tertiary)" }}
      >
        {label}
      </label>
      <input
        type="number"
        min={1}
        max={20}
        placeholder={`auto (${templateDefault})`}
        value={value ?? ""}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") {
            onChange(null);  // volta pro default do template
          } else {
            onChange(parseInt(raw, 10) || templateDefault);
          }
        }}
        className="w-full bg-transparent text-[13px] font-medium outline-none placeholder:text-[var(--color-text-tertiary)]"
        style={{ color: "var(--color-text-primary)" }}
      />
    </div>
  );
}

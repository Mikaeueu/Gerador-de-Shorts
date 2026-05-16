// ============================================================
// Lista de jobs com header de section.
// ============================================================

import type { Job } from "../types";
import { JobCard } from "./JobCard";

interface JobsListProps {
  jobs: Job[];
  loading: boolean;
  onJobDeleted: (jobId: string) => void;
}

export function JobsList({ jobs, loading, onJobDeleted }: JobsListProps) {
  return (
    <section>
      <div
        className="mb-4 flex items-center justify-between border-b pb-3"
        style={{ borderColor: "var(--color-border-subtle)" }}
      >
        <h2
          className="text-[13px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--color-text-secondary)" }}
        >
          Jobs recentes
        </h2>
        <span
          className="text-xs"
          style={{ color: "var(--color-text-tertiary)" }}
        >
          {loading ? "Carregando..." : `${jobs.length} ${jobs.length === 1 ? "job" : "jobs"}`}
        </span>
      </div>

      {jobs.length === 0 && !loading ? (
        <div
          className="rounded-lg border border-dashed p-12 text-center"
          style={{
            borderColor: "var(--color-border-subtle)",
            color: "var(--color-text-tertiary)",
          }}
        >
          <p className="text-sm">
            Nenhum job ainda. Cole um link do YouTube acima pra começar.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job} onDeleted={onJobDeleted} />
          ))}
        </div>
      )}
    </section>
  );
}

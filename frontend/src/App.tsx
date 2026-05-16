// ============================================================
// App principal - single-page conforme decidido com o user.
// Layout: Header sticky -> HeroInput -> JobsList.
// Polling de jobs a cada 5s pra refletir mudancas de status.
// ============================================================

import { useCallback, useEffect, useState } from "react";
import { Header } from "./components/Header";
import { HeroInput } from "./components/HeroInput";
import { JobsList } from "./components/JobsList";
import { api } from "./api";
import type { Job } from "./types";

export default function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

  // Carrega jobs do servidor
  const refreshJobs = useCallback(async () => {
    try {
      const list = await api.listJobs();
      setJobs(list);
    } catch (e) {
      console.error("Falha ao listar jobs:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // Carga inicial + polling a cada 5s pra refletir mudanca de status.
  // (WebSocket por job ja faz updates de progresso live, esse polling
  // pega mudancas de queued -> running e running -> done/failed.)
  useEffect(() => {
    refreshJobs();
    const interval = setInterval(refreshJobs, 5000);
    return () => clearInterval(interval);
  }, [refreshJobs]);

  // Quando user cria um job novo, adiciona no topo da lista
  // sem esperar o proximo polling.
  const handleJobCreated = (job: Job) => {
    setJobs((prev) => [job, ...prev]);
  };

  // Quando user apaga um job, remove da lista local imediatamente
  // (sem esperar o polling pra ficar responsivo).
  const handleJobDeleted = (jobId: string) => {
    setJobs((prev) => prev.filter((j) => j.id !== jobId));
  };

  return (
    <>
      <Header />
      <main className="mx-auto max-w-[980px] px-6 pb-20 pt-12">
        <HeroInput onJobCreated={handleJobCreated} />
        <JobsList jobs={jobs} loading={loading} onJobDeleted={handleJobDeleted} />
      </main>
    </>
  );
}

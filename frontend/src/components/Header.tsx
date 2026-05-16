// ============================================================
// Header sticky com logo + indicador de status da API.
// ============================================================

import { useEffect, useState } from "react";

export function Header() {
  const [apiOk, setApiOk] = useState<boolean | null>(null);

  // Healthcheck periodico a cada 30s
  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch("/api/health");
        setApiOk(res.ok);
      } catch {
        setApiOk(false);
      }
    };
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header
      className="sticky top-0 z-10 flex h-14 items-center justify-between border-b px-6 backdrop-blur"
      style={{
        borderColor: "var(--color-border-subtle)",
        backgroundColor: "rgba(8, 8, 11, 0.85)",
      }}
    >
      <div className="flex items-center gap-2.5">
        <div
          className="flex h-6 w-6 items-center justify-center rounded text-white"
          style={{ backgroundColor: "var(--color-accent)", fontWeight: 600, fontSize: 13 }}
        >
          S
        </div>
        <span className="text-sm font-medium">Shorts Generator</span>
      </div>

      <div
        className="inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-xs font-medium"
        style={{
          backgroundColor: apiOk
            ? "rgba(74, 222, 128, 0.10)"
            : "rgba(239, 68, 68, 0.10)",
          color: apiOk ? "var(--color-status-done)" : "var(--color-status-failed)",
        }}
      >
        <span className="status-dot" />
        {apiOk === null ? "Verificando..." : apiOk ? "API conectada" : "API offline"}
      </div>
    </header>
  );
}

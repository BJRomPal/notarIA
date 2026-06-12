"use client";

// Estado de progreso amigable: en lugar de exponer las fases internas del
// pipeline, muestra un único mensaje con efecto shimmer ("Pensando…",
// "Buscando información…"). El usuario no ve el detalle técnico.

import type { Fase } from "@/lib/types";

const LABELS: Record<string, string> = {
  analisis: "Pensando",
  vectorial: "Buscando información",
  remisiones: "Buscando información",
  evaluacion: "Analizando lo encontrado",
  grafo: "Profundizando en las fuentes",
  redaccion: "Redactando la respuesta",
};

export function ThinkingStatus({ fases }: { fases: Fase[] }) {
  const actual = fases.length > 0 ? fases[fases.length - 1] : null;
  const label = (actual && LABELS[actual.id]) || "Pensando";

  return (
    <div className="flex items-center gap-2.5 px-1 py-2">
      <span className="relative flex h-2.5 w-2.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-400 opacity-60" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent-500" />
      </span>
      <span className="shimmer-text text-[15px] font-medium">{label}…</span>
    </div>
  );
}

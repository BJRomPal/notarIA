// Chips con los artículos que fundamentan la respuesta, en formato legible
// ("Art. 10 — Ley 19550"), nunca el id crudo de la base (Art_10_Ley_19550).
import type { Fuente } from "@/lib/types";

/** Convierte cualquier resto de id de base de datos a texto presentable. */
function presentarNorma(norma: string): string {
  return norma.replace(/_/g, " ").trim();
}

export function Sources({ fuentes }: { fuentes: Fuente[] }) {
  if (fuentes.length === 0) return null;
  return (
    <div className="mt-5 border-t border-slate-100 pt-4">
      <p className="mb-2.5 flex items-center gap-1.5 text-xs font-semibold tracking-wider text-slate-400 uppercase">
        <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5">
          <path d="M10.75 16.82A7.462 7.462 0 0 1 15 15.5c.71 0 1.396.098 2.046.282A.75.75 0 0 0 18 15.06v-11a.75.75 0 0 0-.546-.721A9.006 9.006 0 0 0 15 3a8.963 8.963 0 0 0-4.25 1.065V16.82ZM9.25 4.065A8.963 8.963 0 0 0 5 3c-.85 0-1.673.118-2.454.339A.75.75 0 0 0 2 4.06v11a.75.75 0 0 0 .954.721A7.506 7.506 0 0 1 5 15.5c1.579 0 3.042.487 4.25 1.32V4.065Z" />
        </svg>
        Fuentes consultadas
      </p>
      <div className="flex flex-wrap gap-1.5">
        {fuentes.map((f) => (
          <span
            key={f.id}
            className="inline-flex items-baseline gap-1.5 rounded-lg border border-accent-500/25 bg-gradient-to-b from-amber-50/80 to-amber-100/40 px-2.5 py-1 text-xs text-brand-900"
          >
            <span className="font-serif font-bold text-accent-600">Art. {f.numero}</span>
            <span className="text-slate-400">—</span>
            <span className="text-slate-600">{presentarNorma(f.norma)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

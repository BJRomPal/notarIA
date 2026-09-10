"use client";

// Chips con las fuentes que fundamentan la respuesta, en formato legible
// ("Art. 10 — Ley 19550"), nunca el id crudo de la base (Art_10_Ley_19550).
//
// Hay tres clases de fuente porque el agente tiene tres especialistas, y cada uno cita algo
// distinto. Antes del agente solo existían artículos, así que el "Art." iba escrito fijo; con
// eso, un fallo se mostraba como "Art. Fallo_comercial_Fusion_1994 — ?".
//
// CADA CHIP ABRE SU FUENTE. Es la única superficie navegable de una respuesta, y alcanza: esta
// lista la arma el retrieval, no el modelo, así que cubre el 100% de lo que el sistema realmente
// consultó. Las citas que el modelo escribe DENTRO del párrafo («conforme el art. 77 de la Ley
// 19.550») quedan como texto: no hay ninguna marca que las ate a un objeto Fuente, y hacerlas
// navegables pediría que el redactor emita referencias legibles por máquina —con el riesgo de que
// invente el formato o cite un id que no recuperó—.
//
// El componente pasa a "use client" por esto: era el único del proyecto que no lo era.
import { useState } from "react";
import type { Fuente } from "@/lib/types";
import { FuenteModal, type RefFuente } from "./FuenteModal";

/** Convierte cualquier resto de id de base de datos a texto presentable. */
function presentarNorma(norma: string): string {
  return norma.replace(/_/g, " ").trim();
}

/** Lo que va en negrita a la izquierda del chip. Solo los artículos llevan el prefijo. */
function principal(f: Fuente): string {
  return f.tipo === "articulo" || f.tipo === undefined ? `Art. ${f.numero}` : f.numero;
}

export function Sources({ fuentes }: { fuentes: Fuente[] }) {
  // El modal vive acá y no en MessageBubble porque este componente es el que tiene la lista: el
  // que sabe qué se clickeó es el que la muestra.
  const [abierta, setAbierta] = useState<RefFuente | null>(null);

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
          <button
            key={f.id}
            onClick={() => setAbierta({ id: f.id, tipo: f.tipo })}
            title="Ver la fuente"
            className="inline-flex cursor-pointer items-baseline gap-1.5 rounded-lg border border-accent-500/25 bg-gradient-to-b from-amber-50/80 to-amber-100/40 px-2.5 py-1 text-xs text-brand-900 transition hover:border-accent-500/60 hover:from-amber-100 hover:to-amber-100/70"
          >
            <span className="font-serif font-bold text-accent-600">{principal(f)}</span>
            {/* Un instituto jurídico no tiene norma que citar al lado: se muestra solo. */}
            {f.norma && (
              <>
                <span className="text-slate-400">—</span>
                <span className="text-slate-600">{presentarNorma(f.norma)}</span>
              </>
            )}
          </button>
        ))}
      </div>

      <FuenteModal fuente={abierta} onCerrar={() => setAbierta(null)} />
    </div>
  );
}

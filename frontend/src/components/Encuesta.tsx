"use client";

// La encuesta de la beta: una tarjeta debajo de la respuesta, no un modal. No bloquea el chat:
// el escribano puede seguir preguntando y contestarla después, o descartarla.
//
// El estado de la encuesta vive en el MENSAJE (`message.encuesta`) y no acá: si viviera en el
// componente, al cambiar de conversación y volver la tarjeta reaparecería sin contestar, y un
// segundo envío daría 409 porque la nota ya está guardada.

import { useEffect, useRef, useState } from "react";
import { guardarEvaluacion } from "@/lib/api";
import { DIMENSIONES, RUBRICA, type Dimension } from "@/lib/encuesta";
import type { EstadoEncuesta } from "@/lib/types";

interface EncuestaProps {
  turnoId: string;
  estado: EstadoEncuesta;
  onCambio: (estado: EstadoEncuesta) => void;
}

export function Encuesta({ turnoId, estado, onCambio }: EncuestaProps) {
  const [notas, setNotas] = useState<Partial<Record<Dimension, number>>>({});
  const [comentario, setComentario] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const avisada = useRef(false);

  // Registrar que apareció, aunque nadie la conteste: sin las mostradas no se puede medir
  // cuántos no respondieron. El backend ignora una `mostrada` repetida, así que el doble montaje
  // de React en desarrollo no ensucia nada; el ref evita igual el pedido de más.
  useEffect(() => {
    if (estado !== "pendiente" || avisada.current) return;
    avisada.current = true;
    guardarEvaluacion(turnoId, { estado: "mostrada", rubrica: RUBRICA }).catch(() => {
      // Si no se pudo registrar que apareció, la encuesta se muestra igual: la nota importa más.
    });
  }, [estado, turnoId]);

  if (estado === "descartada") return null;
  if (estado === "respondida") {
    return <p className="fade-up mt-3 text-xs text-slate-400">Gracias por evaluar esta respuesta.</p>;
  }

  const completas = DIMENSIONES.every((d) => notas[d.clave] !== undefined);

  const enviar = async () => {
    setEnviando(true);
    setError(null);
    try {
      await guardarEvaluacion(turnoId, {
        estado: "respondida",
        rubrica: RUBRICA,
        ...notas,
        comentario: comentario.trim() || undefined,
      });
      onCambio("respondida");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar la evaluación.");
    } finally {
      setEnviando(false);
    }
  };

  const descartar = () => {
    // Se cierra aunque el registro falle: insistir con una encuesta que el escribano ya
    // descartó es peor que perder el dato de que la descartó.
    guardarEvaluacion(turnoId, { estado: "descartada", rubrica: RUBRICA }).catch(() => {});
    onCambio("descartada");
  };

  return (
    <div className="fade-up mt-3 rounded-2xl border border-accent-500/30 bg-amber-50/50 px-5 py-4">
      <p className="font-serif text-[15px] font-semibold text-brand-900">¿Cómo estuvo esta respuesta?</p>
      <p className="mt-0.5 text-xs text-slate-500">
        Cuatro notas, del 1 (muy mala) al 5 (excelente). Nos ayuda a mejorar NotarIA.
      </p>

      <div className="mt-4 space-y-3.5">
        {DIMENSIONES.map((d) => (
          <div key={d.clave} className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-brand-900">{d.nombre}</p>
              <p className="text-xs text-slate-500">
                {d.pregunta} <span className="text-slate-400">(1: {d.bajo} · 5: {d.alto})</span>
              </p>
            </div>
            <div role="radiogroup" aria-label={d.nombre} className="flex shrink-0 gap-1.5">
              {[1, 2, 3, 4, 5].map((n) => {
                const elegida = notas[d.clave] === n;
                return (
                  <button
                    key={n}
                    role="radio"
                    aria-checked={elegida}
                    onClick={() => setNotas((prev) => ({ ...prev, [d.clave]: n }))}
                    className={`h-8 w-8 rounded-lg text-sm font-semibold transition ${
                      elegida
                        ? "bg-brand-800 text-white shadow-sm"
                        : "border border-slate-300 bg-white text-slate-600 hover:border-accent-500 hover:text-brand-900"
                    }`}
                  >
                    {n}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <textarea
        value={comentario}
        onChange={(e) => setComentario(e.target.value)}
        maxLength={4000}
        rows={2}
        placeholder="¿Qué está mal o qué faltó? (opcional)"
        className="mt-4 w-full resize-y rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-brand-900 outline-none transition focus:border-accent-500 focus:ring-2 focus:ring-accent-500/20"
      />

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      <div className="mt-3 flex items-center justify-end gap-2">
        <button
          onClick={descartar}
          disabled={enviando}
          className="rounded-xl px-3.5 py-2 text-sm font-medium text-slate-500 transition hover:bg-slate-100 disabled:opacity-50"
        >
          Ahora no
        </button>
        <button
          onClick={() => void enviar()}
          disabled={!completas || enviando}
          className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-brand-950 shadow-md shadow-accent-600/20 transition hover:from-accent-300 hover:to-accent-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {enviando ? "Enviando…" : "Enviar"}
        </button>
      </div>
    </div>
  );
}

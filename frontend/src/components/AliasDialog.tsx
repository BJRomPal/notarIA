"use client";

// Cómo quiere el usuario que el agente lo llame.
//
// El MISMO componente sirve para las dos situaciones, y solo cambia el texto: la bienvenida (la
// primera vez, cuando `usuarios.alias` está en NULL) y la edición posterior desde el menú. Son el
// mismo formulario con el mismo campo; separarlos en dos componentes sería duplicar para cambiar
// dos frases.
//
// POR QUÉ SE PREGUNTA EN VEZ DE ADIVINAR. El JWT de IAP trae `sub` y `email`, y NO trae
// `given_name`: no hay nombre de pila que leer. El backend propone uno derivado del email
// (mariano.miro@… → «Mariano») y acá se muestra cargado y editable, porque con una casilla tipo
// estudio@ la sugerencia es mala y el usuario tiene que poder corregirla antes de que el agente
// empiece a llamarlo «Estudio».

import { useEffect, useState } from "react";
import { guardarAlias } from "@/lib/api";
import { Modal } from "./Modal";

interface AliasDialogProps {
  abierto: boolean;
  /** `true` la primera vez: cambia los textos y no ofrece cancelar sin elegir. */
  bienvenida: boolean;
  /** Valor inicial del campo: el alias actual, o la sugerencia del backend. */
  sugerido: string;
  onCerrar: () => void;
  onGuardado: (alias: string) => void;
}

export function AliasDialog({
  abierto,
  bienvenida,
  sugerido,
  onCerrar,
  onGuardado,
}: AliasDialogProps) {
  const [valor, setValor] = useState(sugerido);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // El sugerido llega después del primer render (sale de un fetch), así que el campo se
  // sincroniza cuando el modal se abre y no solo al montarse.
  useEffect(() => {
    if (abierto) {
      setValor(sugerido);
      setError(null);
    }
  }, [abierto, sugerido]);

  const guardar = async () => {
    const limpio = valor.trim();
    if (!limpio) {
      setError("Escribí un nombre.");
      return;
    }
    setGuardando(true);
    setError(null);
    try {
      const { alias } = await guardarAlias(limpio);
      onGuardado(alias);
      onCerrar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar.");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <Modal
      abierto={abierto}
      onCerrar={onCerrar}
      titulo={bienvenida ? "¿Cómo querés que te llame?" : "Cambiar tu nombre"}
      bajada={
        bienvenida
          ? "NotarIA va a usar este nombre al responderte. Lo podés cambiar cuando quieras desde tu menú."
          : "Así te va a tratar el asistente en sus respuestas."
      }
      ancho="max-w-md"
    >
      <label className="block text-xs font-semibold tracking-wider text-slate-500 uppercase">
        Tu nombre
      </label>
      <input
        autoFocus
        value={valor}
        maxLength={40}
        onChange={(e) => setValor(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void guardar();
        }}
        placeholder="Mariano"
        className="mt-2 w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm text-brand-900 outline-none transition focus:border-accent-500 focus:ring-2 focus:ring-accent-500/20"
      />

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      <div className="mt-5 flex items-center justify-end gap-2">
        {/* En la bienvenida se puede saltear: obligar a completar un campo antes de la primera
            consulta convierte una cortesía en un trámite. Si se saltea, el backend sigue con
            alias NULL y el diálogo vuelve a aparecer en la próxima visita. */}
        <button
          onClick={onCerrar}
          disabled={guardando}
          className="rounded-xl px-3.5 py-2 text-sm font-medium text-slate-500 transition hover:bg-slate-100 disabled:opacity-50"
        >
          {bienvenida ? "Más tarde" : "Cancelar"}
        </button>
        <button
          onClick={() => void guardar()}
          disabled={guardando}
          className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-brand-950 shadow-md shadow-accent-600/20 transition hover:from-accent-300 hover:to-accent-400 disabled:opacity-60"
        >
          {guardando ? "Guardando…" : "Guardar"}
        </button>
      </div>
    </Modal>
  );
}

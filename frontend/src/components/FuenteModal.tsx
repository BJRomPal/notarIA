"use client";

// El contenido de una fuente citada. Se abre desde los chips de "Fuentes consultadas" y desde el
// inventario, con el mismo componente en los dos lados.
//
// PARA QUÉ SIRVE, QUE ES LO QUE DEFINE EL DISEÑO. Es el control de calidad del usuario: la forma
// de verificar que la respuesta dice lo que la norma dice. Por eso el texto del artículo se
// muestra tal cual está en el grafo —sin resumir, sin reformatear— y por eso el estado de vigencia
// va arriba y destacado: leer un artículo derogado creyéndolo vigente es el peor error posible.

import { useEffect, useState } from "react";
import { verFuente, verTextoFallo } from "@/lib/api";
import type { DetalleFuente, Fuente } from "@/lib/types";
import { Modal } from "./Modal";

/** Lo mínimo para pedir una fuente: qué es y cuál. */
export interface RefFuente {
  id: string;
  tipo: Fuente["tipo"];
}

function Etiqueta({ children, tono }: { children: React.ReactNode; tono: "gris" | "rojo" | "ambar" }) {
  const estilos = {
    gris: "border-slate-200 bg-slate-50 text-slate-600",
    rojo: "border-red-200 bg-red-50 text-red-700",
    ambar: "border-accent-500/30 bg-amber-50 text-accent-600",
  };
  return (
    <span className={`rounded-md border px-2 py-0.5 text-[11px] font-medium ${estilos[tono]}`}>
      {children}
    </span>
  );
}

function ArticuloContenido({ d }: { d: Extract<DetalleFuente, { tipo: "articulo" }> }) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5">
        {d.vigente ? (
          <Etiqueta tono="gris">Vigente</Etiqueta>
        ) : (
          <Etiqueta tono="rojo">Derogado — no está vigente</Etiqueta>
        )}
        {d.nota_vigencia && <Etiqueta tono="ambar">{d.nota_vigencia}</Etiqueta>}
      </div>
      {d.ubicacion && <p className="mt-3 text-xs text-slate-500">{d.ubicacion}</p>}
      {/* El texto del artículo trae sus propios saltos de línea y hay que respetarlos: los
          incisos numerados dependen de ellos para leerse. */}
      <p className="mt-3 text-sm leading-relaxed whitespace-pre-wrap text-slate-700">{d.texto}</p>
    </>
  );
}

function FalloContenido({
  d,
  id,
}: {
  d: Extract<DetalleFuente, { tipo: "fallo" }>;
  id: string;
}) {
  const [texto, setTexto] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);

  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5">
        {d.fecha && <Etiqueta tono="gris">{d.fecha}</Etiqueta>}
        {d.rama && <Etiqueta tono="gris">{d.rama}</Etiqueta>}
        {d.expediente && <Etiqueta tono="gris">Expte. {d.expediente}</Etiqueta>}
      </div>

      <p className="mt-4 text-xs font-semibold tracking-wider text-slate-400 uppercase">
        Doctrina del fallo
      </p>
      {/* Este resumen es EXACTAMENTE lo que leyó el modelo para responder: el embedding de un
          fallo se calcula sobre el resumen, no sobre el texto. Mostrarlo es mostrar la fuente
          real de la afirmación, no una versión abreviada de otra cosa. */}
      <p className="mt-1.5 text-sm leading-relaxed whitespace-pre-wrap text-slate-700">{d.resumen}</p>

      {texto === null ? (
        <button
          disabled={cargando}
          onClick={() => {
            setCargando(true);
            verTextoFallo(id)
              .then((r) => setTexto(r.texto))
              .catch((e) => setTexto(`No se pudo traer el texto: ${e.message}`))
              .finally(() => setCargando(false));
          }}
          className="mt-5 rounded-xl border border-slate-300 px-3.5 py-2 text-xs font-medium text-slate-600 transition hover:border-accent-500/50 hover:text-brand-900 disabled:opacity-60"
        >
          {cargando
            ? "Trayendo el texto…"
            : `Ver el texto completo (${Math.max(1, Math.round(d.largo_texto / 1000))} mil caracteres)`}
        </button>
      ) : (
        <>
          <p className="mt-6 text-xs font-semibold tracking-wider text-slate-400 uppercase">
            Texto completo
          </p>
          <p className="mt-1.5 text-[13px] leading-relaxed whitespace-pre-wrap text-slate-600">
            {texto}
          </p>
        </>
      )}
    </>
  );
}

/** Título y bajada del modal, que cambian según la clase de fuente. */
function encabezado(d: DetalleFuente | null): { titulo: string; bajada: string } {
  if (!d) return { titulo: "Fuente", bajada: "" };
  if (d.tipo === "articulo") return { titulo: `Artículo ${d.numero}`, bajada: d.norma };
  if (d.tipo === "entidad") return { titulo: d.nombre, bajada: "Instituto jurídico" };
  return { titulo: d.tribunal || "Jurisprudencia", bajada: d.caratula || "" };
}

export function FuenteModal({ fuente, onCerrar }: { fuente: RefFuente | null; onCerrar: () => void }) {
  const [detalle, setDetalle] = useState<DetalleFuente | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fuente) return;
    let vigente = true;
    setDetalle(null);
    setError(null);
    // `tipo` es opcional en Fuente por compatibilidad con lo que había antes del agente, cuando
    // solo existían artículos. Ese sigue siendo el valor por defecto.
    verFuente(fuente.tipo ?? "articulo", fuente.id)
      .then((d) => vigente && setDetalle(d))
      .catch((e) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
  }, [fuente]);

  const { titulo, bajada } = encabezado(detalle);

  return (
    <Modal
      abierto={fuente !== null}
      onCerrar={onCerrar}
      titulo={titulo}
      bajada={bajada}
      ancho="max-w-2xl"
    >
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!detalle && !error && <p className="shimmer-text text-sm font-medium">Buscando la fuente…</p>}

      {detalle?.tipo === "articulo" && <ArticuloContenido d={detalle} />}
      {detalle?.tipo === "entidad" && (
        // El resumen viene en markdown (lo escribió Qwen, con encabezados ##). No se renderiza
        // como markdown a propósito: sería traer react-markdown a un modal por tres títulos. Lo
        // único que se limpia son los ## de encabezado, que sí molestan al leer.
        <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-700">
          {detalle.resumen.replace(/^#{1,6}\s*/gm, "")}
        </p>
      )}
      {detalle?.tipo === "fallo" && fuente && <FalloContenido d={detalle} id={fuente.id} />}
    </Modal>
  );
}

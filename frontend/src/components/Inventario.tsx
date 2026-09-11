"use client";

// QUÉ HAY CARGADO EN LA BASE DE CONOCIMIENTO.
//
// PARA QUÉ SIRVE, QUE ES LO QUE DEFINE TODO EL DISEÑO. No es una biblioteca para pasear: es para
// contestar «¿está cargada tal norma?» antes de confiar en una respuesta. Eso es una consulta
// puntual, no una navegación. De ahí que el buscador vaya arriba y enfocado al abrir, y que el
// listado sea lo secundario — con 137 de 197 normas siendo registrales, una lista sin buscador es
// una pared de DTR.
//
// DOS PESTAÑAS Y NO UN CATÁLOGO ÚNICO, porque `rama` no es el mismo dato de los dos lados: en las
// normas es una LISTA (`tributario`, `comercial`) y en los fallos un string en otro género
// (`tributaria`), con `laboral` que existe en fallos y no en normas. Unificarlos pediría
// normalizar el grafo, que no se toca desde acá.

import { useEffect, useMemo, useRef, useState } from "react";
import { listarFallos, listarNormas } from "@/lib/api";
import type { FalloCatalogo, NormaCatalogo } from "@/lib/types";
import { FuenteModal, type RefFuente } from "./FuenteModal";
import { Modal } from "./Modal";

/** Quita puntos, espacios y acentos para comparar. «19.550» y «19550» tienen que coincidir.
 *
 * Es el detalle que hace o rompe el buscador: `Norma.numero` guarda «19.550» en unas normas y
 * «19550» en otras, según quién las cargó, y el usuario escribe cualquiera de las dos.
 */
function normalizar(s: string): string {
  return (s || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[.\s/-]/g, "");
}

function Chip({
  activo,
  onClick,
  children,
}: {
  activo: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg border px-2.5 py-1 text-xs transition ${
        activo
          ? "border-accent-500/60 bg-amber-50 font-semibold text-accent-600"
          : "border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-700"
      }`}
    >
      {children}
    </button>
  );
}

// ==============================================================================================
// NORMAS
// ==============================================================================================

// El orden y los nombres de las secciones siguen a `inventario.md`, que es el documento que el
// escribano ya conoce: primero los códigos y las leyes, al final las disposiciones registrales.
const ORDEN_TIPOS = [
  "Codigo",
  "Ley",
  "Decreto",
  "ResolucionGeneral",
  "Resolución",
  "DisposicionTecnicoRegistral",
  "InstruccionDeTrabajo",
];

const TITULO_TIPO: Record<string, string> = {
  Codigo: "Códigos",
  Ley: "Leyes",
  Decreto: "Decretos",
  ResolucionGeneral: "Resoluciones generales",
  "Resolución": "Resoluciones",
  DisposicionTecnicoRegistral: "Disposiciones Técnico Registrales",
  InstruccionDeTrabajo: "Instrucciones de trabajo",
};

/** «Ciudad Autónoma de Buenos Aires» es demasiado largo para una columna; y viene con dos grafías. */
function origen(jurisdiccion: string | null): string {
  const j = (jurisdiccion || "").toLowerCase();
  if (j.includes("buenos aires")) return "CABA";
  if (j.includes("nacional")) return "Nacional";
  return jurisdiccion || "";
}

/** Una norma del listado: qué es, de qué trata y de dónde sale. Nada más.
 *
 * NO se despliega ni lleva a ningún lado. Antes mostraba la cantidad de artículos y dejaba abrir
 * cada uno: era peso sin uso —nadie lee el CCyCN de a un artículo desde un índice— y convertía un
 * listado de consulta rápida en un explorador. Los artículos se leen donde importan: en las citas
 * de cada respuesta, que sí se abren.
 */
function FilaNorma({ norma }: { norma: NormaCatalogo }) {
  return (
    <div className="flex items-baseline gap-3 border-b border-slate-100 py-2 last:border-0">
      <span className="shrink-0 font-serif text-sm font-bold text-brand-900">{norma.nombre}</span>
      <span className="min-w-0 flex-1 text-xs leading-relaxed text-slate-600">
        {norma.titulo || <span className="text-slate-400">Sin descripción cargada</span>}
      </span>
      <span className="shrink-0 text-[11px] text-slate-400">{origen(norma.jurisdiccion)}</span>
    </div>
  );
}

function PanelNormas() {
  const [normas, setNormas] = useState<NormaCatalogo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const [rama, setRama] = useState<string | null>(null);
  const campo = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listarNormas()
      .then(setNormas)
      .catch((e) => setError(e.message));
    campo.current?.focus();
  }, []);

  const ramas = useMemo(() => {
    const cuenta = new Map<string, number>();
    for (const n of normas ?? []) for (const r of n.rama) cuenta.set(r, (cuenta.get(r) ?? 0) + 1);
    return [...cuenta.entries()].sort((a, b) => b[1] - a[1]);
  }, [normas]);

  const filtradas = useMemo(() => {
    const q = normalizar(busca);
    return (normas ?? []).filter((n) => {
      if (rama && !n.rama.includes(rama)) return false;
      if (!q) return true;
      // Se busca contra el nombre canónico, el título y el número suelto: el usuario puede
      // escribir «19550», «19.550», «Ley 19550» o «sociedades» y tiene que encontrar lo mismo.
      return (
        normalizar(n.nombre).includes(q) ||
        normalizar(n.titulo ?? "").includes(q) ||
        normalizar(n.numero ?? "").includes(q)
      );
    });
  }, [normas, busca, rama]);

  // Agrupadas por tipo, que es como las secciones de `inventario.md`. Se agrupa DESPUÉS de
  // filtrar, así una sección vacía simplemente no aparece.
  const porTipo = useMemo(() => {
    const grupos = new Map<string, NormaCatalogo[]>();
    for (const n of filtradas) {
      const t = n.tipo || "Otras";
      if (!grupos.has(t)) grupos.set(t, []);
      grupos.get(t)!.push(n);
    }
    return [...grupos.entries()].sort(
      (a, b) => ORDEN_TIPOS.indexOf(a[0]) - ORDEN_TIPOS.indexOf(b[0]),
    );
  }, [filtradas]);

  return (
    <>
      <input
        ref={campo}
        autoFocus
        value={busca}
        onChange={(e) => setBusca(e.target.value)}
        placeholder="Buscar por número o nombre: 19550, Ley 17.801, DTR 6/2019, hipoteca…"
        className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm text-brand-900 outline-none transition focus:border-accent-500 focus:ring-2 focus:ring-accent-500/20"
      />

      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <Chip activo={rama === null} onClick={() => setRama(null)}>
          Todas
        </Chip>
        {ramas.map(([r, n]) => (
          <Chip key={r} activo={rama === r} onClick={() => setRama(rama === r ? null : r)}>
            {r} ({n})
          </Chip>
        ))}
      </div>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      {!normas && !error && <p className="mt-4 text-sm text-slate-500">Cargando el inventario…</p>}

      {normas && (
        <>
          <p className="mt-4 text-[11px] tracking-wider text-slate-400 uppercase">
            {filtradas.length} de {normas.length} normas
          </p>

          {porTipo.map(([tipo, lista]) => (
            <section key={tipo} className="mt-4">
              <h3 className="mb-1 font-serif text-xs font-bold tracking-wide text-accent-600 uppercase">
                {TITULO_TIPO[tipo] ?? tipo}
                <span className="ml-1.5 font-sans font-normal text-slate-400">({lista.length})</span>
              </h3>
              {lista.map((n) => (
                <FilaNorma key={n.id} norma={n} />
              ))}
            </section>
          ))}

          {filtradas.length === 0 && (
            <p className="py-6 text-center text-sm text-slate-500">
              No hay ninguna norma que coincida. Si esperabas encontrarla, no está cargada.
            </p>
          )}
        </>
      )}
    </>
  );
}

// ==============================================================================================
// FALLOS
// ==============================================================================================

function PanelFallos({ onAbrir }: { onAbrir: (ref: RefFuente) => void }) {
  const [fallos, setFallos] = useState<FalloCatalogo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const [rama, setRama] = useState<string | null>(null);

  useEffect(() => {
    listarFallos()
      .then(setFallos)
      .catch((e) => setError(e.message));
  }, []);

  const ramas = useMemo(() => {
    const cuenta = new Map<string, number>();
    for (const f of fallos ?? []) if (f.rama) cuenta.set(f.rama, (cuenta.get(f.rama) ?? 0) + 1);
    return [...cuenta.entries()].sort((a, b) => b[1] - a[1]);
  }, [fallos]);

  const filtrados = useMemo(() => {
    const q = normalizar(busca);
    return (fallos ?? []).filter((f) => {
      if (rama && f.rama !== rama) return false;
      if (!q) return true;
      return (
        normalizar(f.caratula).includes(q) ||
        normalizar(f.tribunal).includes(q) ||
        normalizar(f.fecha).includes(q)
      );
    });
  }, [fallos, busca, rama]);

  return (
    <>
      <input
        value={busca}
        onChange={(e) => setBusca(e.target.value)}
        placeholder="Buscar por carátula, tribunal o fecha…"
        className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm text-brand-900 outline-none transition focus:border-accent-500 focus:ring-2 focus:ring-accent-500/20"
      />

      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <Chip activo={rama === null} onClick={() => setRama(null)}>
          Todas
        </Chip>
        {ramas.map(([r, n]) => (
          <Chip key={r} activo={rama === r} onClick={() => setRama(rama === r ? null : r)}>
            {r} ({n})
          </Chip>
        ))}
      </div>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      {!fallos && !error && <p className="mt-4 text-sm text-slate-500">Cargando los fallos…</p>}

      {fallos && (
        <>
          <p className="mt-4 text-[11px] tracking-wider text-slate-400 uppercase">
            {filtrados.length} de {fallos.length} fallos y dictámenes
          </p>
          <div className="mt-1">
            {filtrados.map((f) => (
              <button
                key={f.id}
                onClick={() => onAbrir({ id: f.id, tipo: "fallo" })}
                className="flex w-full items-start gap-3 border-b border-slate-100 py-2.5 text-left transition last:border-0 hover:bg-slate-50"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-brand-900">
                    {f.caratula || "(sin carátula)"}
                  </span>
                  <span className="block truncate text-xs text-slate-500">{f.tribunal}</span>
                </span>
                <span className="shrink-0 text-[11px] text-slate-400">{f.fecha}</span>
              </button>
            ))}
            {filtrados.length === 0 && (
              <p className="py-6 text-center text-sm text-slate-500">Ningún fallo coincide.</p>
            )}
          </div>
        </>
      )}
    </>
  );
}

// ==============================================================================================

export function Inventario({ abierto, onCerrar }: { abierto: boolean; onCerrar: () => void }) {
  const [pestania, setPestania] = useState<"normas" | "fallos">("normas");
  const [fuente, setFuente] = useState<RefFuente | null>(null);

  return (
    <>
      <Modal
        abierto={abierto}
        onCerrar={onCerrar}
        titulo="Qué hay en la base"
        bajada="Buscá una norma para saber si está cargada antes de confiar en una respuesta."
        ancho="max-w-3xl"
      >
        <div className="mb-4 flex gap-1 border-b border-slate-200">
          {(["normas", "fallos"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPestania(p)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm capitalize transition ${
                pestania === p
                  ? "border-accent-500 font-semibold text-brand-900"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              {p}
            </button>
          ))}
        </div>

        {/* Cada panel se monta al elegir su pestaña, así el inventario de fallos no se descarga si
            nadie lo mira. La contra es que cambiar de pestaña y volver rearma el estado; es un
            fetch de 292 filas, y no vale un caché para eso. */}
        {pestania === "normas" ? <PanelNormas /> : <PanelFallos onAbrir={setFuente} />}
      </Modal>

      {/* Fuera del <Modal> del inventario: son dos <dialog> hermanos y el navegador los apila en su
          capa superior por orden de apertura, así que el detalle queda arriba sin pelear z-index. */}
      <FuenteModal fuente={fuente} onCerrar={() => setFuente(null)} />
    </>
  );
}

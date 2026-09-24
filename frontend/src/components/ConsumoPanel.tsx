"use client";

// Lo que el usuario consumió, en tokens y —en chico— en dólares.
//
// POR QUÉ LOS TOKENS ARRIBA Y EL COSTO ABAJO. A un escribano el gasto en dólares por consulta no
// le dice nada útil y puede inquietarlo sin motivo: son fracciones de centavo. Los tokens son la
// unidad de uso y es lo que se pidió ver. El costo igual está, porque es el número que sirve si
// algún día hay que discutir un plan, pero no es el titular.
//
// Los tokens de pensamiento se muestran aparte y no sumados a la salida, aunque Google los
// facture juntos: es la única forma de ver cuánto se está gastando en razonamiento invisible, que
// es justo la palanca que el proyecto ya usó para abaratar la ruta determinista.

import { useEffect, useState } from "react";
import { verConsumo } from "@/lib/api";
import type { ResumenConsumo } from "@/lib/types";
import { Modal } from "./Modal";

const numero = new Intl.NumberFormat("es-AR");

function Tarjeta({ etiqueta, valor }: { etiqueta: string; valor: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-2.5">
      <p className="text-[10px] font-semibold tracking-wider text-slate-400 uppercase">{etiqueta}</p>
      <p className="mt-0.5 font-serif text-lg font-bold text-brand-900">{valor}</p>
    </div>
  );
}

export function ConsumoPanel({ abierto, onCerrar }: { abierto: boolean; onCerrar: () => void }) {
  const [datos, setDatos] = useState<ResumenConsumo | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Se pide al abrir y no al montar: el panel vive montado todo el tiempo junto al menú, y pedir
  // el consumo en cada carga de la página sería una consulta que nadie miró.
  useEffect(() => {
    if (!abierto) return;
    let vigente = true;
    setError(null);
    verConsumo()
      .then((d) => vigente && setDatos(d))
      .catch((e) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
  }, [abierto]);

  const total = datos ? datos.tokens_entrada + datos.tokens_salida : 0;

  return (
    <Modal
      abierto={abierto}
      onCerrar={onCerrar}
      titulo="Mis consumos"
      bajada="Uso acumulado de tus consultas al asistente."
      ancho="max-w-2xl"
    >
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!datos && !error && <p className="text-sm text-slate-500">Cargando…</p>}

      {datos && (
        <>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <Tarjeta etiqueta="Tokens totales" valor={numero.format(total)} />
            <Tarjeta etiqueta="Entrada" valor={numero.format(datos.tokens_entrada)} />
            <Tarjeta etiqueta="Salida" valor={numero.format(datos.tokens_salida)} />
            <Tarjeta etiqueta="Pensamiento" valor={numero.format(datos.tokens_pensamiento)} />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-slate-500">
            <span>
              <strong className="font-semibold text-slate-700">{numero.format(datos.conversaciones)}</strong>{" "}
              consultas
            </span>
            <span>
              <strong className="font-semibold text-slate-700">{numero.format(datos.llamadas)}</strong>{" "}
              llamadas al modelo
            </span>
            <span>Costo acumulado US$ {datos.costo_usd.toFixed(4)}</span>
          </div>

          {datos.por_conversacion.length > 0 && (
            <>
              <p className="mt-6 mb-2 text-xs font-semibold tracking-wider text-slate-400 uppercase">
                Por consulta
              </p>
              {/* La tabla es lo único que puede ser más ancho que el modal en un celular, así que
                  va en su propio contenedor con scroll horizontal. */}
              <div className="scroll-slim -mx-1 overflow-x-auto px-1">
                <table className="w-full min-w-[28rem] text-left text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 text-[10px] tracking-wider text-slate-400 uppercase">
                      <th className="py-2 pr-3 font-semibold">Consulta</th>
                      <th className="py-2 pr-3 text-right font-semibold">Entrada</th>
                      <th className="py-2 pr-3 text-right font-semibold">Salida</th>
                      <th className="py-2 text-right font-semibold">US$</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datos.por_conversacion.map((c) => (
                      <tr key={c.id} className="border-b border-slate-100 last:border-0">
                        <td className="max-w-[18rem] truncate py-2 pr-3 text-slate-700" title={c.titulo}>
                          {c.titulo}
                        </td>
                        <td className="py-2 pr-3 text-right text-slate-500">
                          {numero.format(c.tokens_entrada)}
                        </td>
                        <td className="py-2 pr-3 text-right text-slate-500">
                          {numero.format(c.tokens_salida)}
                        </td>
                        <td className="py-2 text-right text-slate-500">{c.costo_usd.toFixed(5)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </Modal>
  );
}

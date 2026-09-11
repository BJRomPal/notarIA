"use client";

import type { Conversation, Usuario } from "@/lib/types";
import { Logo, LogoMark } from "./Logo";
import { UserMenu } from "./UserMenu";

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  apiOk: boolean | null;
  base: boolean | null;
  usuario: Usuario | null;
  /** Por qué no se pudo leer el historial, o null si salió bien. */
  error: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onEditarAlias: () => void;
  onVerConsumos: () => void;
  onVerInventario: () => void;
  onVerGuia: () => void;
}

export function Sidebar({
  conversations,
  activeId,
  apiOk,
  base,
  usuario,
  error,
  onSelect,
  onNew,
  onDelete,
  onEditarAlias,
  onVerConsumos,
  onVerInventario,
  onVerGuia,
}: SidebarProps) {
  return (
    <aside className="flex h-full w-72 shrink-0 flex-col bg-gradient-to-b from-brand-950 via-brand-950 to-[#0a1220] text-slate-200 max-md:hidden">
      <div className="flex items-center gap-2.5 px-5 pt-5 pb-4">
        <LogoMark className="h-9 w-9" />
        <Logo size="text-[22px]" tone="dark" />
      </div>

      <div className="px-3">
        <button
          onClick={onNew}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2.5 text-sm font-semibold text-brand-950 shadow-md shadow-accent-600/20 transition hover:from-accent-300 hover:to-accent-400 active:scale-[0.99]"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
            <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
          </svg>
          Nueva consulta
        </button>
      </div>

      {conversations.length > 0 && (
        <p className="mt-5 mb-1 px-6 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
          Consultas
        </p>
      )}

      <nav className="scroll-slim flex-1 space-y-0.5 overflow-y-auto px-3 pb-4">
        {/* EL ERROR VA ANTES QUE LA LISTA VACÍA, Y NUNCA LOS DOS. Si la lectura del
            historial falla, «Sin consultas todavía» sería mentira: la peor forma de fallar con
            las conversaciones de alguien es hacerle creer que no tiene ninguna. El backend ya
            distingue los dos casos —503 si no hay base, 200 con lista vacía si no hay nada— y
            este cartel es el otro extremo de esa decisión (ver api/rutas/cuenta.py). */}
        {error ? (
          <div className="mt-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2.5">
            <p className="text-xs font-semibold text-red-300">
              No se pudieron cargar tus consultas.
            </p>
            {/* El motivo que dio el servidor, no uno inventado acá: sin base dice una cosa y
                con la base caída dice otra, y esa diferencia es la que permite arreglarlo. */}
            <p className="mt-1 text-[11px] leading-relaxed text-red-300/70">{error}</p>
            <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">
              Probá recargar la página. Podés seguir consultando mientras tanto.
            </p>
          </div>
        ) : (
          conversations.length === 0 && (
            <p className="px-3 pt-4 text-xs leading-relaxed text-slate-500">
              Sin consultas todavía.
              <br />
              Empezá una nueva.
            </p>
          )
        )}
        {conversations.map((c) => (
          <div
            key={c.id}
            className={`group flex items-center rounded-lg text-sm transition ${
              c.id === activeId
                ? "border-l-2 border-accent-400 bg-brand-800/80 text-white"
                : "border-l-2 border-transparent text-slate-300 hover:bg-brand-900/70"
            }`}
          >
            <button
              onClick={() => onSelect(c.id)}
              className="min-w-0 flex-1 truncate px-3 py-2.5 text-left"
              title={c.titulo}
            >
              {c.titulo}
            </button>
            <button
              onClick={() => onDelete(c.id)}
              className="mr-2 hidden rounded p-1 text-slate-500 hover:text-red-400 group-hover:block"
              title="Eliminar conversación"
              aria-label="Eliminar conversación"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                <path
                  fillRule="evenodd"
                  d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482 41.03 41.03 0 0 0-2.365-.298V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4Z"
                  clipRule="evenodd"
                />
              </svg>
            </button>
          </div>
        ))}
      </nav>

      <UserMenu
        alias={usuario?.alias ?? null}
        email={usuario?.email ?? ""}
        apiOk={apiOk}
        base={base}
        onEditarAlias={onEditarAlias}
        onVerConsumos={onVerConsumos}
        onVerInventario={onVerInventario}
        onVerGuia={onVerGuia}
      />
    </aside>
  );
}

"use client";

import type { Conversation } from "@/lib/types";
import { Logo, LogoMark } from "./Logo";

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  apiOk: boolean | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function Sidebar({ conversations, activeId, apiOk, onSelect, onNew, onDelete }: SidebarProps) {
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
        {conversations.length === 0 && (
          <p className="px-3 pt-4 text-xs leading-relaxed text-slate-500">
            Sin consultas todavía.
            <br />
            Empezá una nueva.
          </p>
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

      <footer className="border-t border-brand-800/60 px-5 py-3.5 text-xs text-slate-500">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              apiOk === null
                ? "bg-slate-500"
                : apiOk
                  ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.7)]"
                  : "bg-red-400"
            }`}
          />
          {apiOk === null ? "Verificando conexión…" : apiOk ? "En línea" : "Sin conexión"}
        </div>
        <p className="mt-1.5 text-slate-600">Derecho argentino</p>
      </footer>
    </aside>
  );
}

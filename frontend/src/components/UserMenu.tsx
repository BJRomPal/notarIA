"use client";

// El menú del usuario, en el pie del panel lateral.
//
// Ocupa el lugar donde ya estaba el punto de estado de la conexión, y se lo queda adentro: el
// estado del servicio es información de la sesión, igual que el nombre, y tenerlos en dos lugares
// distintos del mismo rincón era desprolijo.
//
// Abre hacia ARRIBA porque está abajo. Es un detalle obvio y se aclara porque la clase que lo
// hace (`bottom-full`) es lo único que diferencia este desplegable de cualquier otro.

import { useEffect, useRef, useState } from "react";

interface UserMenuProps {
  /** El alias elegido, o null si todavía no eligió ninguno. */
  alias: string | null;
  email: string;
  apiOk: boolean | null;
  /** Sin Postgres no hay consumos que mostrar: la opción no aparece. */
  base: boolean | null;
  onEditarAlias: () => void;
  onVerConsumos: () => void;
}

function Opcion({
  onClick,
  children,
  icono,
}: {
  onClick: () => void;
  children: React.ReactNode;
  icono: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-slate-300 transition hover:bg-brand-800/70 hover:text-white"
    >
      <span className="text-slate-500">{icono}</span>
      {children}
    </button>
  );
}

export function UserMenu({
  alias,
  email,
  apiOk,
  base,
  onEditarAlias,
  onVerConsumos,
}: UserMenuProps) {
  const [abierto, setAbierto] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Cerrar al clickear afuera y con Escape. Es un desplegable y no un modal, así que no puede
  // apoyarse en <dialog>: tiene que convivir con el resto de la pantalla, no taparla.
  useEffect(() => {
    if (!abierto) return;
    const afuera = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setAbierto(false);
    };
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setAbierto(false);
    document.addEventListener("pointerdown", afuera);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", afuera);
      document.removeEventListener("keydown", escape);
    };
  }, [abierto]);

  const nombre = alias || "Sin nombre";

  return (
    <div ref={ref} className="relative border-t border-brand-800/60">
      {abierto && (
        <div className="absolute bottom-full left-2 right-2 mb-2 overflow-hidden rounded-xl border border-brand-800 bg-brand-900 py-1 shadow-2xl shadow-black/40">
          <Opcion
            onClick={() => {
              setAbierto(false);
              onEditarAlias();
            }}
            icono={
              <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                <path d="M2.695 14.763l-1.262 3.154a.5.5 0 0 0 .65.65l3.155-1.262a4 4 0 0 0 1.343-.885L17.5 5.5a2.121 2.121 0 0 0-3-3L3.58 13.42a4 4 0 0 0-.885 1.343Z" />
              </svg>
            }
          >
            {alias ? "Cambiar mi nombre" : "Elegir mi nombre"}
          </Opcion>

          {base && (
            <Opcion
              onClick={() => {
                setAbierto(false);
                onVerConsumos();
              }}
              icono={
                <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                  <path d="M15.5 2A1.5 1.5 0 0 0 14 3.5v13a1.5 1.5 0 0 0 3 0v-13A1.5 1.5 0 0 0 15.5 2ZM9.5 6A1.5 1.5 0 0 0 8 7.5v9a1.5 1.5 0 0 0 3 0v-9A1.5 1.5 0 0 0 9.5 6ZM3.5 10A1.5 1.5 0 0 0 2 11.5v5a1.5 1.5 0 0 0 3 0v-5A1.5 1.5 0 0 0 3.5 10Z" />
                </svg>
              }
            >
              Mis consumos
            </Opcion>
          )}
        </div>
      )}

      <button
        onClick={() => setAbierto((v) => !v)}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-left transition hover:bg-brand-900/70"
      >
        {/* La inicial como avatar: no hay foto de perfil porque IAP no la manda, y una inicial
            dice lo mismo sin pedirle nada a nadie. */}
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent-400 to-accent-600 font-serif text-xs font-bold text-brand-950">
          {(alias || email || "?").trim().charAt(0).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-semibold text-slate-200">{nombre}</span>
          <span className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <span
              className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${
                apiOk === null
                  ? "bg-slate-500"
                  : apiOk
                    ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.7)]"
                    : "bg-red-400"
              }`}
            />
            {apiOk === null ? "Verificando…" : apiOk ? "En línea" : "Sin conexión"}
          </span>
        </span>
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          className={`h-4 w-4 shrink-0 text-slate-500 transition ${abierto ? "rotate-180" : ""}`}
        >
          <path
            fillRule="evenodd"
            d="M14.77 12.79a.75.75 0 0 1-1.06-.02L10 8.832 6.29 12.77a.75.75 0 1 1-1.08-1.04l4.25-4.5a.75.75 0 0 1 1.08 0l4.25 4.5a.75.75 0 0 1-.02 1.06Z"
            clipRule="evenodd"
          />
        </svg>
      </button>
    </div>
  );
}

"use client";

// La ventana modal del proyecto. La usan el alias, los consumos, el inventario, la guía y el
// detalle de una fuente.
//
// POR QUÉ `<dialog>` NATIVO Y NO UN DIV CON POSICIÓN FIJA
// -------------------------------------------------------
// `showModal()` trae gratis cuatro cosas que a mano son código y se hacen mal: cerrar con Escape,
// atrapar el foco adentro (tabular no se escapa al contenido de atrás), el fondo como pseudo
// elemento `::backdrop`, y la capa superior del navegador — que evita la guerra de `z-index`
// cuando un modal abre otro, que es justo lo que pasa acá: desde el inventario se abre el detalle
// de un artículo. Hecho con un div harían falta unos 120 renglones de useEffect para quedar peor.
//
// Lo único que el elemento no da servido es cerrar al clickear el fondo, porque el `::backdrop`
// no es un nodo al que se le pueda poner un onClick. Se resuelve mirando si el click cayó en el
// propio <dialog> y no en su contenido: el área del dialog que el usuario puede ver ES el fondo,
// porque la tarjeta de adentro ocupa su propio div.

import { useEffect, useRef } from "react";

interface ModalProps {
  abierto: boolean;
  onCerrar: () => void;
  titulo: string;
  /** Texto chico bajo el título. */
  bajada?: string;
  children: React.ReactNode;
  /** Ancho máximo de la tarjeta. Los paneles con tablas necesitan más que un diálogo de un campo. */
  ancho?: string;
}

export function Modal({ abierto, onCerrar, titulo, bajada, children, ancho = "max-w-lg" }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // `open` como atributo NO alcanza: muestra el dialog pero sin modalidad —sin foco atrapado,
    // sin backdrop y sin capa superior—. La modalidad solo la da llamar a showModal().
    if (abierto && !dialog.open) dialog.showModal();
    if (!abierto && dialog.open) dialog.close();
  }, [abierto]);

  return (
    <dialog
      ref={ref}
      // El evento `close` lo dispara también Escape, que cierra el dialog sin pasar por onCerrar.
      // Sin esto, el estado de React quedaría en "abierto" y el modal no volvería a abrirse.
      onClose={onCerrar}
      onClick={(e) => {
        if (e.target === ref.current) onCerrar();
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-none bg-transparent p-0 backdrop:bg-brand-950/60 backdrop:backdrop-blur-sm"
    >
      <div
        className={`fade-up mx-auto flex max-h-[85dvh] w-full ${ancho} flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl`}
      >
        <header className="flex items-start gap-3 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="font-serif text-lg font-bold text-brand-900">{titulo}</h2>
            {bajada && <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{bajada}</p>}
          </div>
          <button
            onClick={onCerrar}
            className="-mr-1 rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            aria-label="Cerrar"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </header>

        <div className="scroll-slim overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </dialog>
  );
}

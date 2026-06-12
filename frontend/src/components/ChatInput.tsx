"use client";

import { useEffect, useRef, useState } from "react";

interface ChatInputProps {
  streaming: boolean;
  onSend: (texto: string) => void;
  onStop: () => void;
}

export function ChatInput({ streaming, onSend, onStop }: ChatInputProps) {
  const [texto, setTexto] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // Autosize del textarea hasta 8 líneas aprox.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [texto]);

  const submit = () => {
    const t = texto.trim();
    if (!t || streaming) return;
    setTexto("");
    onSend(t);
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      <div className="flex items-end gap-2 rounded-3xl border border-slate-300/80 bg-white p-2 shadow-lg shadow-slate-300/40 transition focus-within:border-accent-500/50 focus-within:ring-4 focus-within:ring-accent-400/15">
        <textarea
          ref={ref}
          rows={1}
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Escribí tu consulta legal… (Enter para enviar, Shift+Enter para nueva línea)"
          className="scroll-slim max-h-[200px] flex-1 resize-none bg-transparent px-2 py-2 text-[15px] outline-none placeholder:text-slate-400"
        />
        {streaming ? (
          <button
            onClick={onStop}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-slate-200 text-slate-700 transition hover:bg-slate-300 active:scale-95"
            title="Detener"
            aria-label="Detener generación"
          >
            <span className="block h-3.5 w-3.5 rounded-sm bg-slate-700" />
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={!texto.trim()}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-700 to-brand-900 text-white shadow-md transition hover:from-brand-600 hover:to-brand-800 active:scale-95 disabled:opacity-40 disabled:shadow-none"
            title="Enviar"
            aria-label="Enviar consulta"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
              <path d="M3.105 2.288a.75.75 0 0 0-.826.95l1.414 4.926A1.5 1.5 0 0 0 5.135 9.25h6.115a.75.75 0 0 1 0 1.5H5.135a1.5 1.5 0 0 0-1.442 1.086l-1.414 4.926a.75.75 0 0 0 .826.95 28.897 28.897 0 0 0 15.293-7.155.75.75 0 0 0 0-1.114A28.897 28.897 0 0 0 3.105 2.288Z" />
            </svg>
          </button>
        )}
      </div>
      <p className="mt-2 text-center text-xs text-slate-400">
        NotarIA responde según la legislación cargada en su base de conocimiento. Verificá siempre las citas con el texto oficial.
      </p>
    </div>
  );
}

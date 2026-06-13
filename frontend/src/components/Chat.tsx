"use client";

import { useEffect, useRef } from "react";
import type { Conversation } from "@/lib/types";
import { ChatInput } from "./ChatInput";
import { Logo, LogoMark } from "./Logo";
import { MessageBubble } from "./MessageBubble";

const EJEMPLOS: { icono: React.ReactNode; texto: string }[] = [
  {
    icono: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
        <path d="M10 1a.75.75 0 0 1 .75.75v1.5h4.5a.75.75 0 0 1 0 1.5h-.531l2.243 6.279a.75.75 0 0 1-.256.84A4.483 4.483 0 0 1 14 12.75a4.483 4.483 0 0 1-2.706-.881.75.75 0 0 1-.256-.84L13.281 4.75H10.75v10.547c1.673.165 3.25.59 3.25 1.453 0 .966-1.79 1.25-4 1.25s-4-.284-4-1.25c0-.863 1.577-1.288 3.25-1.453V4.75H6.719l2.243 6.279a.75.75 0 0 1-.256.84A4.483 4.483 0 0 1 6 12.75a4.483 4.483 0 0 1-2.706-.881.75.75 0 0 1-.256-.84L5.281 4.75H4.75a.75.75 0 0 1 0-1.5h4.5v-1.5A.75.75 0 0 1 10 1Z" />
      </svg>
    ),
    texto: "¿Cuál es el capital mínimo para constituir una sociedad anónima?",
  },
  {
    icono: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
        <path
          fillRule="evenodd"
          d="M4.5 2A1.5 1.5 0 0 0 3 3.5v13A1.5 1.5 0 0 0 4.5 18h11a1.5 1.5 0 0 0 1.5-1.5V7.621a1.5 1.5 0 0 0-.44-1.06l-4.12-4.122A1.5 1.5 0 0 0 11.378 2H4.5Zm2.25 8.5a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5h-6.5Zm0 3a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5h-6.5Z"
          clipRule="evenodd"
        />
      </svg>
    ),
    texto: "¿Qué requisitos debe cumplir el instrumento constitutivo de una SAS?",
  },
  {
    icono: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
        <path
          fillRule="evenodd"
          d="M1 4a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V4Zm12 4a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM4 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2Zm13-1a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM1.75 14.5a.75.75 0 0 0 0 1.5c4.417 0 8.693.603 12.749 1.73 1.111.309 2.251-.512 2.251-1.696v-.784a.75.75 0 0 0-1.5 0v.784a.272.272 0 0 1-.35.25A49.043 49.043 0 0 0 1.75 14.5Z"
          clipRule="evenodd"
        />
      </svg>
    ),
    texto: "¿Puede una SAS emitir debentures?",
  },
  {
    icono: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
        <path
          fillRule="evenodd"
          d="M9.965 11.026a5 5 0 1 1 1.06-1.06l2.755 2.754a.75.75 0 1 1-1.06 1.06l-2.755-2.754ZM10.5 7a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Z"
          clipRule="evenodd"
        />
      </svg>
    ),
    texto: "¿Qué facultades de fiscalización tiene la IGJ sobre las sociedades por acciones?",
  },
];

interface ChatProps {
  conversation: Conversation | null;
  streaming: boolean;
  onSend: (texto: string) => void;
  onStop: () => void;
}

function Welcome({ onSend }: { onSend: (texto: string) => void }) {
  return (
    <div className="relative flex h-full flex-col items-center justify-center overflow-hidden px-4">
      {/* Halos decorativos */}
      <div className="pointer-events-none absolute -top-32 left-1/2 h-96 w-[42rem] -translate-x-1/2 rounded-full bg-brand-200/40 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 left-1/4 h-80 w-80 rounded-full bg-amber-200/30 blur-3xl" />

      <div className="relative flex flex-col items-center">
        <LogoMark className="h-24 w-24 drop-shadow-lg" />
        <div className="mt-5">
          <Logo size="text-5xl" tone="light" />
        </div>
        <p className="mt-2 font-serif text-sm tracking-[0.25em] text-accent-600 uppercase">
          Asistente legal notarial
        </p>
        <p className="mt-5 max-w-md text-center text-[15px] leading-relaxed text-slate-500">
          Consultá sobre derecho argentino. Cada respuesta se construye sobre la
          legislación vigente y cita los artículos en los que se funda.
        </p>

        <div className="mt-10 grid w-full max-w-2xl grid-cols-1 gap-2.5 sm:grid-cols-2">
          {EJEMPLOS.map((e) => (
            <button
              key={e.texto}
              onClick={() => onSend(e.texto)}
              className="group flex items-start gap-3 rounded-2xl border border-slate-200 bg-white/80 px-4 py-3.5 text-left text-sm text-slate-600 shadow-sm backdrop-blur transition hover:-translate-y-0.5 hover:border-accent-500/40 hover:shadow-md"
            >
              <span className="mt-0.5 text-accent-500 transition group-hover:scale-110">{e.icono}</span>
              <span>{e.texto}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function Chat({ conversation, streaming, onSend, onStop }: ChatProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  const messages = conversation?.messages ?? [];
  const lastAssistant = messages.length > 0 ? messages[messages.length - 1] : null;
  const contentLen = lastAssistant?.role === "assistant" ? lastAssistant.content.length : 0;

  // Auto-scroll mientras llegan tokens, solo si el usuario está apoyado al fondo.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages.length, contentLen, streaming]);

  return (
    <main className="flex h-full min-w-0 flex-1 flex-col bg-gradient-to-b from-slate-50 to-slate-100/80">
      <header className="flex items-center justify-center gap-2 border-b border-slate-200 bg-white px-4 py-3 md:hidden">
        <LogoMark className="h-7 w-7" />
        <Logo size="text-xl" tone="light" />
      </header>

      {messages.length === 0 ? (
        <Welcome onSend={onSend} />
      ) : (
        <div
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
          className="scroll-slim flex-1 overflow-y-auto"
        >
          <div className="mx-auto w-full max-w-3xl space-y-7 px-4 py-8">
            {messages.map((m, i) => (
              <MessageBubble key={i} message={m} />
            ))}
          </div>
        </div>
      )}

      <ChatInput streaming={streaming} onSend={onSend} onStop={onStop} />
    </main>
  );
}

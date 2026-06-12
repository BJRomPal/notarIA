"use client";

// Hook que maneja el envío de una consulta y el consumo del stream SSE.
// El estado de los mensajes vive en la conversación (page.tsx); este hook
// recibe un callback para actualizar el último mensaje del asistente a medida
// que llegan eventos.

import { useCallback, useRef, useState } from "react";
import type { AssistantMessage, SSEEvent } from "./types";

interface UseNotariaChatOptions {
  /** Aplica una transformación al mensaje del asistente en curso. */
  onAssistantUpdate: (
    update: (msg: AssistantMessage) => AssistantMessage,
  ) => void;
}

export function emptyAssistantMessage(): AssistantMessage {
  return { role: "assistant", content: "", fases: [], fuentes: [], done: false };
}

function applyEvent(msg: AssistantMessage, ev: SSEEvent): AssistantMessage {
  switch (ev.type) {
    case "fase":
      return { ...msg, fases: [...msg.fases, { id: ev.fase, label: ev.label, items: [] }] };
    case "item": {
      if (msg.fases.length === 0) return msg;
      const fases = msg.fases.slice();
      const last = fases[fases.length - 1];
      fases[fases.length - 1] = { ...last, items: [...last.items, ev.texto] };
      return { ...msg, fases };
    }
    case "fuentes":
      return { ...msg, fuentes: ev.articulos };
    case "token":
      return { ...msg, content: msg.content + ev.texto };
    case "fin":
      return { ...msg, done: true, segundos: ev.segundos };
    case "error":
      return { ...msg, done: true, error: ev.mensaje };
    default:
      return msg;
  }
}

export function useNotariaChat({ onAssistantUpdate }: UseNotariaChatOptions) {
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const send = useCallback(
    async (pregunta: string) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setStreaming(true);

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pregunta }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          throw new Error(`El servidor respondió ${res.status}. ¿Está corriendo la API de NotarIA?`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // Los eventos SSE vienen separados por línea en blanco.
          const partes = buffer.split("\n\n");
          buffer = partes.pop() ?? "";
          for (const parte of partes) {
            const linea = parte.trim();
            if (!linea.startsWith("data:")) continue;
            try {
              const ev = JSON.parse(linea.slice(5).trim()) as SSEEvent;
              onAssistantUpdate((msg) => applyEvent(msg, ev));
            } catch {
              // Evento malformado: se ignora y se sigue leyendo el stream.
            }
          }
        }

        // Si el stream terminó sin evento "fin" (corte del servidor), cerrar el mensaje.
        onAssistantUpdate((msg) => (msg.done ? msg : { ...msg, done: true }));
      } catch (e) {
        const aborted = e instanceof DOMException && e.name === "AbortError";
        onAssistantUpdate((msg) => ({
          ...msg,
          done: true,
          error: aborted
            ? undefined
            : e instanceof Error
              ? e.message
              : "Error de conexión con la API.",
        }));
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [onAssistantUpdate],
  );

  return { send, stop, streaming };
}

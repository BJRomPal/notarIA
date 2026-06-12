"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Chat } from "@/components/Chat";
import { Sidebar } from "@/components/Sidebar";
import { loadConversations, saveConversations } from "@/lib/storage";
import type { AssistantMessage, Conversation } from "@/lib/types";
import { emptyAssistantMessage, useNotariaChat } from "@/lib/useNotariaChat";

export default function Home() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [apiOk, setApiOk] = useState<boolean | null>(null);

  // Id de la conversación que está recibiendo el stream en este momento.
  const streamConvIdRef = useRef<string | null>(null);

  // Carga inicial desde localStorage (en efecto, para no romper el SSR).
  useEffect(() => {
    const convs = loadConversations();
    setConversations(convs);
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (loaded) saveConversations(conversations);
  }, [conversations, loaded]);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((d) => setApiOk(Boolean(d.ok)))
      .catch(() => setApiOk(false));
  }, []);

  const updateAssistant = useCallback(
    (update: (msg: AssistantMessage) => AssistantMessage) => {
      const convId = streamConvIdRef.current;
      if (!convId) return;
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== convId) return c;
          const msgs = c.messages.slice();
          const last = msgs[msgs.length - 1];
          if (!last || last.role !== "assistant") return c;
          msgs[msgs.length - 1] = update(last);
          return { ...c, messages: msgs };
        }),
      );
    },
    [],
  );

  const { send, stop, streaming } = useNotariaChat({ onAssistantUpdate: updateAssistant });

  const handleSend = useCallback(
    (texto: string) => {
      if (streaming) return;

      // El id se decide acá afuera: los updaters de setState corren diferidos
      // y mutarlo adentro dejaría a setActiveId/streamConvIdRef con el valor viejo.
      const existe = activeId !== null && conversations.some((c) => c.id === activeId);
      const convId = existe ? (activeId as string) : crypto.randomUUID();

      setConversations((prev) => {
        let lista = prev;
        if (!existe) {
          const nueva: Conversation = {
            id: convId,
            titulo: texto.length > 60 ? `${texto.slice(0, 60)}…` : texto,
            creada: Date.now(),
            messages: [],
          };
          lista = [nueva, ...prev];
        }
        return lista.map((c) =>
          c.id === convId
            ? { ...c, messages: [...c.messages, { role: "user" as const, content: texto }, emptyAssistantMessage()] }
            : c,
        );
      });

      setActiveId(convId);
      streamConvIdRef.current = convId;
      void send(texto);
    },
    [activeId, conversations, send, streaming],
  );

  const handleDelete = useCallback(
    (id: string) => {
      if (streamConvIdRef.current === id) stop();
      setConversations((prev) => prev.filter((c) => c.id !== id));
      setActiveId((curr) => (curr === id ? null : curr));
    },
    [stop],
  );

  const active = conversations.find((c) => c.id === activeId) ?? null;

  return (
    <div className="flex h-dvh">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        apiOk={apiOk}
        onSelect={(id) => setActiveId(id)}
        onNew={() => setActiveId(null)}
        onDelete={handleDelete}
      />
      <Chat conversation={active} streaming={streaming} onSend={handleSend} onStop={stop} />
    </div>
  );
}

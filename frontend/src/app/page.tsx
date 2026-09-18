"use client";

// La pantalla. Se quedó con una sola responsabilidad: el turno en curso —mandar la pregunta y
// volcar el stream en el último mensaje—. La lista de conversaciones se fue a useConversations
// y el alias y los consumos a sus propios componentes.

import { useCallback, useEffect, useRef, useState } from "react";
import { AliasDialog } from "@/components/AliasDialog";
import { Chat } from "@/components/Chat";
import { ConsumoPanel } from "@/components/ConsumoPanel";
import { GuiaPrompts } from "@/components/GuiaPrompts";
import { Inventario } from "@/components/Inventario";
import { Sidebar } from "@/components/Sidebar";
import { verSalud, verUsuario } from "@/lib/api";
import type { AssistantMessage, Conversation, Usuario } from "@/lib/types";
import { useConversations } from "@/lib/useConversations";
import { emptyAssistantMessage, useNotariaChat } from "@/lib/useNotariaChat";
import { randomUUID } from "@/lib/uuid";

export default function Home() {
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [base, setBase] = useState<boolean | null>(null);
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [panelAlias, setPanelAlias] = useState(false);
  const [panelConsumos, setPanelConsumos] = useState(false);
  const [panelInventario, setPanelInventario] = useState(false);
  const [panelGuia, setPanelGuia] = useState(false);

  // Id de la conversación que está recibiendo el stream en este momento.
  const streamConvIdRef = useRef<string | null>(null);

  // `stop` en un ref para cortar la dependencia circular entre los dos hooks: useConversations
  // necesita poder frenar el stream al borrar, y useNotariaChat necesita el setter de la lista
  // para volcar los tokens. Uno de los dos tiene que ir primero, y el ref es lo que lo permite
  // sin inventar un estado intermedio.
  const stopRef = useRef<() => void>(() => {});

  // El estado del servicio va primero porque de `base` depende de dónde sale el historial.
  // El proxy devuelve la respuesta de FastAPI tal cual; si la API no responde, contesta 502 con
  // un {error} y `status` no viene, así que la misma comparación cubre los dos casos.
  useEffect(() => {
    verSalud()
      .then((d) => {
        setApiOk(d.status === "ok");
        setBase(Boolean(d.base));
      })
      .catch(() => {
        setApiOk(false);
        setBase(false);
      });
  }, []);

  // El usuario solo existe si hay base. Sin Postgres no hay fila donde guardar un alias, así que
  // tampoco se ofrece elegirlo.
  useEffect(() => {
    if (!base) return;
    verUsuario()
      .then((u) => {
        setUsuario(u);
        // La bienvenida se abre sola una sola vez: `necesita_alias` es `alias IS NULL`, y quien
        // aprieta "Más tarde" lo sigue teniendo en NULL, así que vuelve a aparecer en la próxima
        // visita. Quien elige un alias y después lo borra, no.
        if (u.necesita_alias) setPanelAlias(true);
      })
      .catch(() => setUsuario(null));
  }, [base]);

  const {
    conversations,
    setConversations,
    activeId,
    active,
    error: errorConversaciones,
    seleccionar,
    borrar,
    nueva,
    setActiveId,
  } = useConversations({
    base,
    // Si se borra la conversación que está respondiendo, primero se corta el stream: sin esto
    // los tokens seguirían llegando y `updateAssistant` los escribiría en una conversación que
    // ya no está en la lista.
    onBorrarActiva: (id) => {
      if (streamConvIdRef.current === id) stopRef.current();
    },
  });

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
    [setConversations],
  );

  const { send, stop, streaming } = useNotariaChat({ onAssistantUpdate: updateAssistant });

  useEffect(() => {
    stopRef.current = stop;
  }, [stop]);

  const handleSend = useCallback(
    (texto: string) => {
      if (streaming) return;

      // El id se decide acá afuera: los updaters de setState corren diferidos
      // y mutarlo adentro dejaría a setActiveId/streamConvIdRef con el valor viejo.
      const existe = activeId !== null && conversations.some((c) => c.id === activeId);
      const convId = existe ? (activeId as string) : randomUUID();

      setConversations((prev) => {
        let lista = prev;
        if (!existe) {
          const conv: Conversation = {
            id: convId,
            titulo: texto.length > 60 ? `${texto.slice(0, 60)}…` : texto,
            creada: Date.now(),
            messages: [],
            // Nace cargada: sus mensajes son los de este turno, no hay nada que ir a buscar.
            cargada: true,
          };
          lista = [conv, ...prev];
        }
        return lista.map((c) =>
          c.id === convId
            ? { ...c, messages: [...c.messages, { role: "user" as const, content: texto }, emptyAssistantMessage()] }
            : c,
        );
      });

      setActiveId(convId);
      streamConvIdRef.current = convId;
      void send(texto, convId);
    },
    [activeId, conversations, send, setActiveId, setConversations, streaming],
  );

  return (
    <div className="flex h-dvh">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        apiOk={apiOk}
        base={base}
        usuario={usuario}
        error={errorConversaciones}
        onSelect={seleccionar}
        onNew={nueva}
        onDelete={borrar}
        onEditarAlias={() => setPanelAlias(true)}
        onVerConsumos={() => setPanelConsumos(true)}
        onVerInventario={() => setPanelInventario(true)}
        onVerGuia={() => setPanelGuia(true)}
      />
      <Chat
        conversation={active}
        streaming={streaming}
        onSend={handleSend}
        onStop={stop}
        onVerGuia={() => setPanelGuia(true)}
      />

      <AliasDialog
        abierto={panelAlias}
        bienvenida={usuario?.necesita_alias ?? false}
        sugerido={usuario?.alias ?? usuario?.alias_sugerido ?? ""}
        onCerrar={() => setPanelAlias(false)}
        onGuardado={(alias) => setUsuario((u) => (u ? { ...u, alias, necesita_alias: false } : u))}
      />
      <ConsumoPanel abierto={panelConsumos} onCerrar={() => setPanelConsumos(false)} />
      <Inventario abierto={panelInventario} onCerrar={() => setPanelInventario(false)} />
      <GuiaPrompts
        abierto={panelGuia}
        onCerrar={() => setPanelGuia(false)}
        onVerInventario={() => setPanelInventario(true)}
      />
    </div>
  );
}

"use client";

// LA LISTA DE CONVERSACIONES, con sus dos orígenes posibles.
//
// Antes vivía suelta en `page.tsx`, que eran 115 líneas con cuatro estados. Se extrajo acá porque
// ahora el historial puede venir de Postgres y eso suma carga diferida, borrado contra el
// servidor y un modo de respaldo — tres cosas que no tienen nada que ver con el streaming, que
// es lo único que quedó en `page.tsx`.
//
// POR QUÉ DOS ORÍGENES Y NO UNO
// -----------------------------
// Con Postgres el historial sigue al usuario entre dispositivos, que es lo que se espera de algo
// que tiene login. Pero el proyecto sostiene a propósito que todo funcione SIN `POSTGRES_URL`
// —`api/consumo.py` es un no-op silencioso y el checkpointer cae a memoria—, y romper eso dejaría
// el chat sin panel lateral cuando alguien levanta el backend a secas. Así que `base` decide, y
// es una sola rama: con base, el servidor manda y no se escribe nada en localStorage; sin base,
// queda exactamente el comportamiento anterior.
//
// Lo que ya está guardado en el localStorage de un navegador NO se migra. Es data de una sola
// máquina y de la etapa de desarrollo; un importador de un solo uso sería código que después
// estorba. Queda ahí, sin aparecer en la lista del servidor.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  aMensajesDeChat,
  borrarConversacion,
  listarConversaciones,
  verConversacion,
} from "./api";
import { loadConversations, saveConversations } from "./storage";
import type { Conversation } from "./types";

interface Opciones {
  /** `null` mientras no se sabe si hay Postgres: hasta entonces no se carga nada. */
  base: boolean | null;
  /** Para cortar el stream si se borra la conversación que está respondiendo. */
  onBorrarActiva: (id: string) => void;
}

export function useConversations({ base, onBorrarActiva }: Opciones) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [listo, setListo] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Conversaciones cuyos mensajes ya se están pidiendo, para no pedirlos dos veces si el usuario
  // hace clic dos veces seguidas en la misma.
  const pidiendo = useRef<Set<string>>(new Set());

  // CARGA INICIAL. Espera a saber si hay base: con `base === null` todavía no se contestó el
  // health y cargar de localStorage acá dejaría la lista equivocada por un instante.
  useEffect(() => {
    if (base === null) return;

    if (!base) {
      setConversations(loadConversations());
      setListo(true);
      return;
    }

    let vigente = true;
    listarConversaciones()
      .then((lista) => {
        if (!vigente) return;
        setConversations(
          lista.map((c) => ({
            id: c.id,
            titulo: c.titulo,
            creada: new Date(c.actualizada_en).getTime(),
            messages: [],
            cargada: false,
          })),
        );
      })
      .catch((e) => vigente && setError(e.message))
      .finally(() => vigente && setListo(true));
    return () => {
      vigente = false;
    };
  }, [base]);

  // PERSISTENCIA LOCAL, solo en el modo sin base. Con Postgres escribir acá además sería tener
  // dos fuentes de verdad para lo mismo, que es la forma más rápida de que se contradigan.
  useEffect(() => {
    if (listo && base === false) saveConversations(conversations);
  }, [conversations, listo, base]);

  /** Abre una conversación, trayendo sus mensajes la primera vez. */
  const seleccionar = useCallback(
    (id: string) => {
      setActiveId(id);
      if (!base) return;

      const conv = conversations.find((c) => c.id === id);
      if (!conv || conv.cargada || pidiendo.current.has(id)) return;

      pidiendo.current.add(id);
      verConversacion(id)
        .then((datos) => {
          setConversations((prev) =>
            prev.map((c) =>
              c.id === id
                ? { ...c, titulo: datos.titulo, messages: aMensajesDeChat(datos.mensajes), cargada: true }
                : c,
            ),
          );
        })
        .catch((e) => setError(e.message))
        .finally(() => pidiendo.current.delete(id));
    },
    [base, conversations],
  );

  /** Borra una conversación del servidor y de la lista. */
  const borrar = useCallback(
    (id: string) => {
      onBorrarActiva(id);

      // Se quita de la lista en el acto y se repone si el servidor rechaza: lo contrario —esperar
      // la respuesta— deja el ítem clickeable medio segundo después de que el usuario lo borró.
      const respaldo = conversations;
      setConversations((prev) => prev.filter((c) => c.id !== id));
      setActiveId((curr) => (curr === id ? null : curr));

      if (!base) return;
      borrarConversacion(id).catch((e) => {
        setError(e.message);
        setConversations(respaldo);
      });
    },
    [base, conversations, onBorrarActiva],
  );

  const active = conversations.find((c) => c.id === activeId) ?? null;

  return {
    conversations,
    setConversations,
    activeId,
    active,
    listo,
    error,
    limpiarError: () => setError(null),
    seleccionar,
    borrar,
    nueva: () => setActiveId(null),
    setActiveId,
  };
}

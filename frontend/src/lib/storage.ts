// Persistencia simple de conversaciones en localStorage.
// Se guarda la lista completa bajo una sola clave; suficiente para uso personal.

import type { Conversation } from "./types";

const KEY = "notaria-conversations";

export function loadConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const data = JSON.parse(raw);
    if (!Array.isArray(data)) return [];
    // `cargada: true` por defecto: una conversación guardada en el navegador YA tiene sus
    // mensajes acá, no hay nada que ir a buscar. Lo que se guardó antes de que ese campo
    // existiera llegaría como undefined, y el chat la mostraría cargando para siempre.
    return data.map((c) => ({ ...c, cargada: c.cargada ?? true }));
  } catch {
    return [];
  }
}

export function saveConversations(conversations: Conversation[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(conversations));
  } catch {
    // localStorage lleno o no disponible: se pierde la persistencia, no la sesión.
  }
}

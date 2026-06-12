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
    return Array.isArray(data) ? data : [];
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

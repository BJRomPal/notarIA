// Tipos compartidos entre el hook de chat, la UI y el parser de eventos SSE.

/** Evento que emite el backend por SSE (ver api/agente/streaming.py). */
export type SSEEvent =
  | { type: "fase"; fase: string; label: string }
  | { type: "item"; texto: string }
  | { type: "fuentes"; articulos: Fuente[] }
  | { type: "token"; texto: string }
  | { type: "fin"; articulos: number; segundos: number }
  | { type: "error"; mensaje: string };

/** Una cita que se muestra debajo de la respuesta.
 *
 * Los tres tipos se pintan distinto porque son cosas distintas, y escribir "Art." delante
 * de todos era correcto cuando solo había artículos:
 *   articulo -> "Art. 77 — Ley 19.550"
 *   fallo    -> "CNCom. Sala C — 15/04/2025"
 *   entidad  -> "Sociedad Anonima"           (un instituto jurídico, sin norma)
 *
 * `tipo` es opcional para no romper si el backend no lo manda: se asume "articulo", que es
 * lo que había antes del agente.
 */
export interface Fuente {
  id: string;
  numero: string;
  norma: string;
  tipo?: "articulo" | "fallo" | "entidad";
}

/** Una fase del pipeline con sus detalles, tal como se muestra en la timeline. */
export interface Fase {
  id: string;
  label: string;
  items: string[];
}

export interface UserMessage {
  role: "user";
  content: string;
}

export interface AssistantMessage {
  role: "assistant";
  content: string;
  fases: Fase[];
  fuentes: Fuente[];
  error?: string;
  segundos?: number;
  done: boolean;
}

export type ChatMessage = UserMessage | AssistantMessage;

export interface Conversation {
  id: string;
  titulo: string;
  creada: number;
  messages: ChatMessage[];
}

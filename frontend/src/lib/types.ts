// Tipos compartidos entre el hook de chat, la UI y el parser de eventos SSE.

/** Evento que emite el backend por SSE (ver api/pipeline.py). */
export type SSEEvent =
  | { type: "fase"; fase: string; label: string }
  | { type: "item"; texto: string }
  | { type: "fuentes"; articulos: Fuente[] }
  | { type: "token"; texto: string }
  | { type: "fin"; articulos: number; segundos: number }
  | { type: "error"; mensaje: string };

export interface Fuente {
  id: string;
  numero: string;
  norma: string;
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

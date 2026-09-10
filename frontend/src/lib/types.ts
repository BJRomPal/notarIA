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

/** Una conversación de la lista lateral.
 *
 * `cargada` distingue "no tiene mensajes" de "todavía no los pedí". Con el historial en
 * Postgres la lista llega sin mensajes —son 88 conversaciones, traerlas enteras sería absurdo—
 * y los de cada una se piden al abrirla. Sin esa marca, una conversación recién listada se
 * vería como una conversación vacía y el chat mostraría la pantalla de bienvenida encima de
 * una charla que existe.
 */
export interface Conversation {
  id: string;
  titulo: string;
  creada: number;
  messages: ChatMessage[];
  cargada: boolean;
}

/** El usuario y cómo quiere que el agente lo llame (GET /api/usuario). */
export interface Usuario {
  email: string;
  alias: string | null;
  /** Nombre de pila tentativo, derivado del email. El diálogo lo precarga y se puede editar. */
  alias_sugerido: string;
  /** `alias IS NULL` en la base: todavía no se le preguntó. Distinto de un alias borrado. */
  necesita_alias: boolean;
}

/** Consumo de una conversación (GET /api/consumo, campo por_conversacion). */
export interface ConsumoConversacion {
  id: string;
  titulo: string;
  llamadas: number;
  tokens_entrada: number;
  tokens_salida: number;
  tokens_pensamiento: number;
  costo_usd: number;
}

/** Totales de consumo del usuario más el detalle por conversación (GET /api/consumo). */
export interface ResumenConsumo {
  conversaciones: number;
  llamadas: number;
  tokens_entrada: number;
  tokens_salida: number;
  tokens_pensamiento: number;
  costo_usd: number;
  por_conversacion: ConsumoConversacion[];
}

/** Un mensaje tal como lo devuelve el servidor (GET /api/conversaciones/{id}).
 *
 * `fuentes` viene del jsonb de `notaria.mensajes`: son las MISMAS citas que se le mostraron al
 * usuario en su momento, así que los chips se reconstruyen sin volver a consultar Neo4j.
 */
export interface MensajeGuardado {
  rol: "usuario" | "asistente";
  contenido: string;
  fuentes: Fuente[];
  creado_en: string;
}

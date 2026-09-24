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

/** Una norma del inventario (GET /api/catalogo/normas).
 *
 * `nombre` es el canónico de cita («Ley 19.550», «DTR 6/2019»), NO el título: 100 de las 197
 * normas no tienen título, así que una lista basada en él vendría medio vacía. `titulo` está
 * igual, como texto secundario y para que el buscador lo encuentre.
 *
 * `rama` es una LISTA en las normas y un string en los fallos, y encima con otro vocabulario
 * («tributario» vs «tributaria»). Por eso son dos pestañas con su propio filtro.
 *
 * No trae el articulado ni cuántos artículos tiene: el inventario es un listado para contestar
 * «¿está cargada?», no un explorador del corpus.
 */
export interface NormaCatalogo {
  id: string;
  nombre: string;
  tipo: string;
  numero: string | null;
  titulo: string | null;
  rama: string[];
  jurisdiccion: string | null;
}

/** Un fallo del inventario (GET /api/catalogo/fallos). */
export interface FalloCatalogo {
  id: string;
  tribunal: string;
  caratula: string;
  fecha: string;
  rama: string;
}

/** El contenido de una fuente citada (GET /api/fuente/{tipo}/{id}).
 *
 * Unión discriminada por `tipo`: son tres cosas distintas y se muestran distinto. El fallo llega
 * sin `texto` a propósito —promedia 19.571 caracteres y el más largo tiene 286.611—; `largo_texto`
 * dice cuánto pesa para poder avisarlo antes de descargarlo.
 */
export type DetalleFuente =
  | {
      tipo: "articulo";
      numero: string;
      norma: string;
      norma_id: string;
      ubicacion: string;
      vigente: boolean;
      modificado: boolean;
      nota_vigencia: string;
      texto: string;
    }
  | { tipo: "entidad"; nombre: string; resumen: string }
  | {
      tipo: "fallo";
      tribunal: string;
      caratula: string;
      fecha: string;
      expediente: string;
      rama: string;
      resumen: string;
      largo_texto: number;
    };

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

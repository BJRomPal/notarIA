// Cliente de la API de NotarIA. Todas las llamadas pasan por acá salvo el chat, que es un
// stream y vive en useNotariaChat.ts.
//
// POR QUÉ EXISTE. Antes había dos fetch sueltos en dos archivos. Ahora son seis endpoints, y sin
// un solo lugar donde mirar cada componente terminaría repitiendo el manejo de errores — o, peor,
// no haciéndolo, y mostrando una lista vacía cuando lo que hubo fue un 503.
//
// El 401 NO se maneja acá a propósito: con IAP adelante, un pedido sin identidad válida no llega
// nunca al navegador con esta forma; lo intercepta el proxy de Google y muestra su pantalla de
// login. Si igual apareciera un 401, cae en el error genérico y se ve el mensaje del servidor,
// que es lo correcto para algo que no debería pasar.

import type { Conversation, MensajeGuardado, ResumenConsumo, Usuario } from "./types";

/** Error con el mensaje que mandó el servidor, no con "Failed to fetch". */
export class ErrorApi extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function pedir<T>(ruta: string, opciones?: RequestInit): Promise<T> {
  const res = await fetch(`/api${ruta}`, opciones);

  if (!res.ok) {
    // FastAPI pone el motivo en `detail`; el proxy, en `error` cuando no pudo ni conectar.
    let detalle = `El servidor respondió ${res.status}.`;
    try {
      const cuerpo = await res.json();
      detalle = cuerpo.detail ?? cuerpo.error ?? detalle;
    } catch {
      // Respuesta sin JSON (un 502 de infraestructura, por ejemplo): queda el mensaje genérico.
    }
    throw new ErrorApi(detalle, res.status);
  }

  // 204 del DELETE: no hay cuerpo que parsear.
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function json(metodo: string, cuerpo: unknown): RequestInit {
  return {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  };
}

/** Estado del servicio. `base` dice si hay Postgres, y de eso depende de dónde sale el historial. */
export function verSalud() {
  return pedir<{ status: string; autenticacion: boolean; base: boolean }>("/health");
}

export function verUsuario() {
  return pedir<Usuario>("/usuario");
}

export function guardarAlias(alias: string) {
  return pedir<{ alias: string }>("/usuario/alias", json("PUT", { alias }));
}

/** La lista para el panel lateral: sin mensajes, ordenada por actividad. */
export function listarConversaciones() {
  return pedir<{ id: string; titulo: string; actualizada_en: string }[]>("/conversaciones");
}

/** Los mensajes de una conversación, para rehidratarla al abrirla. */
export function verConversacion(id: string) {
  return pedir<{ id: string; titulo: string; mensajes: MensajeGuardado[] }>(
    `/conversaciones/${id}`,
  );
}

export function borrarConversacion(id: string) {
  return pedir<void>(`/conversaciones/${id}`, { method: "DELETE" });
}

export function verConsumo() {
  return pedir<ResumenConsumo>("/consumo");
}

/** Convierte los mensajes del servidor a los del chat.
 *
 * Los rehidratados llegan con `fases: []` y `done: true`: el detalle de las fases no se
 * persiste —es información de "lo que estaba pasando", sin valor una vez que la respuesta
 * está— y `segundos` tampoco, así que la píldora de tiempo no aparece en los mensajes viejos.
 * Las fuentes SÍ vuelven, que es lo que importa para poder verificar una respuesta guardada.
 */
export function aMensajesDeChat(guardados: MensajeGuardado[]): Conversation["messages"] {
  return guardados.map((m) =>
    m.rol === "usuario"
      ? { role: "user" as const, content: m.contenido }
      : {
          role: "assistant" as const,
          content: m.contenido,
          fases: [],
          fuentes: m.fuentes ?? [],
          done: true,
        },
  );
}

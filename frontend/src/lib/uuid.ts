// UUID v4, sin depender de un contexto seguro.
//
// `crypto.randomUUID()` es la vía nativa, pero el navegador solo la expone en un "contexto
// seguro" (https:// o http://localhost) — entrar por la IP de la red local en http:// (el
// "Network: http://192.168.x.x:3000" que imprime `next dev`) la deja `undefined`, y el turno
// explota antes de mandar nada ("crypto.randomUUID is not a function").
//
// `crypto.getRandomValues()` no tiene esa restricción: arma el UUID a mano con eso cuando
// `randomUUID()` no está. El fallback a Math.random() es el último recurso, para no romper en
// un navegador sin ninguna de las dos — no hace falta que sea criptográficamente fuerte, es un
// id de conversación, no un secreto.
export function randomUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  }

  bytes[6] = (bytes[6] & 0x0f) | 0x40; // versión 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variante 10xx

  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

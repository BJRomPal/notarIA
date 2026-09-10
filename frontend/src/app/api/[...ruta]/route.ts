// Proxy único hacia la API FastAPI de NotarIA. Mantiene al navegador en un solo origen (sin
// CORS) y reenvía todo tal cual: el SSE de /api/chat y el JSON del resto.
//
// POR QUÉ UNO SOLO Y NO UN ARCHIVO POR ENDPOINT
// ---------------------------------------------
// Reemplaza a `api/chat/route.ts` y `api/health/route.ts`. Son nueve endpoints y creciendo, y
// con un archivo por endpoint cada uno repite la URL de la API y el reenvío de headers. Basta
// que uno se olvide del header de IAP para que ESE endpoint devuelva 401 en producción y en
// local no, que es el peor lugar donde dejar un error: aparece recién en el deploy.
//
// EL HEADER DE IAP, QUE ES EL MOTIVO REAL DE ESTE ARCHIVO
// -------------------------------------------------------
// Con IAP adelante, el navegador nunca habla con FastAPI: habla con Next, y el JWT llega ACÁ.
// El proxy anterior reenviaba únicamente Content-Type, así que el token se perdía en este salto
// y FastAPI veía un pedido sin identidad — 401 en cada consulta, con la autenticación encendida.
// Los headers se reenvían por lista explícita y no en bloque: copiar Host o Content-Length de
// un request a otro rompe el upstream.

export const dynamic = "force-dynamic";

const API_URL = process.env.NOTARIA_API_URL ?? "http://localhost:8000";

const HEADER_IAP = "x-goog-iap-jwt-assertion";

async function reenviar(req: Request, ruta: string[]): Promise<Response> {
  const { search } = new URL(req.url);
  const destino = `${API_URL}/api/${ruta.join("/")}${search}`;

  const headers: Record<string, string> = {};
  const tipo = req.headers.get("content-type");
  if (tipo) headers["Content-Type"] = tipo;
  const jwt = req.headers.get(HEADER_IAP);
  if (jwt) headers[HEADER_IAP] = jwt;

  // GET y DELETE no llevan body; fetch rechaza un body en un GET.
  const conCuerpo = req.method !== "GET" && req.method !== "DELETE";

  let upstream: Response;
  try {
    upstream = await fetch(destino, {
      method: req.method,
      headers,
      body: conCuerpo ? await req.text() : undefined,
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { error: `No se pudo conectar con la API de NotarIA en ${API_URL}.` },
      { status: 502 },
    );
  }

  // Se devuelve el body sin leerlo para que el stream de /api/chat siga siendo un stream: si
  // acá se hiciera await upstream.text(), la respuesta llegaría entera al final y el chat
  // dejaría de escribirse token por token. El Content-Type se copia del upstream, así el SSE
  // sigue siendo text/event-stream y el resto application/json sin un caso especial por ruta.
  const salida = new Headers({ "Cache-Control": "no-cache" });
  const tipoUpstream = upstream.headers.get("content-type");
  if (tipoUpstream) salida.set("Content-Type", tipoUpstream);

  return new Response(upstream.body, { status: upstream.status, headers: salida });
}

export async function GET(req: Request, ctx: { params: Promise<{ ruta: string[] }> }) {
  return reenviar(req, (await ctx.params).ruta);
}

export async function POST(req: Request, ctx: { params: Promise<{ ruta: string[] }> }) {
  return reenviar(req, (await ctx.params).ruta);
}

export async function PUT(req: Request, ctx: { params: Promise<{ ruta: string[] }> }) {
  return reenviar(req, (await ctx.params).ruta);
}

export async function DELETE(req: Request, ctx: { params: Promise<{ ruta: string[] }> }) {
  return reenviar(req, (await ctx.params).ruta);
}

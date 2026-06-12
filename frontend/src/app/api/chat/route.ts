// Proxy de streaming hacia la API FastAPI de NotarIA.
// Mantiene al navegador en un solo origen (sin CORS) y reenvía el SSE tal cual.

export const dynamic = "force-dynamic";

const API_URL = process.env.NOTARIA_API_URL ?? "http://localhost:8000";

export async function POST(req: Request) {
  const body = await req.text();

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch {
    return Response.json(
      { error: `No se pudo conectar con la API de NotarIA en ${API_URL}.` },
      { status: 502 },
    );
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
    },
  });
}

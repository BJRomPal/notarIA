// Chequeo de salud: verifica que la API FastAPI esté accesible.

export const dynamic = "force-dynamic";

const API_URL = process.env.NOTARIA_API_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const res = await fetch(`${API_URL}/api/health`, { cache: "no-store" });
    return Response.json({ ok: res.ok });
  } catch {
    return Response.json({ ok: false });
  }
}

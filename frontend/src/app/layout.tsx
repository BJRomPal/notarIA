import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NotarIA — Asistente legal notarial",
  description:
    "Chat de consultas legales para el ámbito notarial argentino, basado en legislación societaria con GraphRAG.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es">
      <body className="font-sans antialiased bg-slate-50 text-slate-900">
        {children}
      </body>
    </html>
  );
}

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Para la imagen de Cloud Run (frontend/Dockerfile): un server.js con solo las dependencias
  // que usa, sin node_modules entero.
  output: "standalone",
};

export default nextConfig;

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next.js 16 uses Turbopack by default. Empty config satisfies the
  // "no turbopack config" warning without overriding any defaults.
  // Turbopack has its own native file watcher — no polling needed.
  turbopack: {},
};

export default nextConfig;

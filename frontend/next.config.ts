import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Cloud Run deploy (Task 15): produces .next/standalone + a minimal
  // server.js so the runtime image doesn't need node_modules installed.
  // See frontend/Dockerfile.
  output: "standalone",
};

export default nextConfig;

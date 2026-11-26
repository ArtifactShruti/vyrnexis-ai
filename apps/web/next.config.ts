import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Permit isolated verification builds while the default local server runs.
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;

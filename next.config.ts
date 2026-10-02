import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingIncludes: {
    "/*": ["./node_modules/next/dist/compiled/next-server/**/*", "./security-core/bin/audio-security-core.exe"],
  },
  outputFileTracingExcludes: {
    "/*": ["./data/**/*", "./.venv/**/*", "./dist/**/*", "./.env*"],
  },
  distDir: process.env.AUDIO_NEXT_DIST_DIR || ".next",
};

export default nextConfig;

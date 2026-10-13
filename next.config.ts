import type { NextConfig } from "next";

// The UI is a static export (re-architecture G5): `next build` writes plain HTML/JS/CSS to ./out, and the app's local API
// (worker/audio_translate/api) serves it. There is no Node server at run time, and no route handler: the backend is the API.
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  transpilePackages: ["@audio/ui"],   // the shared package is TypeScript source in this repository
};

export default nextConfig;

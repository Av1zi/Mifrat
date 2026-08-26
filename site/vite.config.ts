import { defineConfig } from "vite";

// Static, no-backend build: everything under public/ (including public/data,
// populated by scripts/copy-data.mjs) is copied verbatim into dist/.
export default defineConfig({
  build: {
    target: "es2022",
  },
});

import { resolve } from "node:path";
import { defineConfig } from "vite";

// Static, no-backend build: everything under public/ (including public/data,
// populated by scripts/copy-data.mjs) is copied verbatim into dist/.
// Two pages: the site (index.html) and the scrape console (admin/index.html,
// served at /admin/ behind Cloudflare Access); each gets its own bundle, so
// no admin code ships with the public site.
export default defineConfig({
  build: {
    target: "es2022",
    rolldownOptions: {
      input: {
        main: resolve(import.meta.dirname, "index.html"),
        admin: resolve(import.meta.dirname, "admin/index.html"),
      },
    },
  },
});

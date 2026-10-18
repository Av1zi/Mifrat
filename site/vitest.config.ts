import { defineConfig } from "vitest/config";

// Pure-logic tests (compat engine, routing, utils): no DOM needed. Tests that
// touch `location`/`localStorage` stub the global themselves.
export default defineConfig({
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
  },
});

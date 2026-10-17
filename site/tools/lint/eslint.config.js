// Flat config for the site. Lives here (not in site/) because typescript-eslint
// needs the TypeScript JS API (TS 6.x) and the site compiles with TS 7; see
// package.json in this folder. Run via `npm run lint` from site/.
//
// Deliberately syntax-level only (no type-aware rules): the existing code is
// checked for type errors by `tsc -b`, and this config is tuned so the
// current sources pass without a mass reformat. Formatting is Prettier's job
// and is opt-in (`npm run format:check`), so no style rules are enabled here.
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "public/**", "node_modules/**", "**/*.generated.ts", ".wrangler/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  prettier,
  {
    files: ["src/**/*.ts"],
    languageOptions: { globals: globals.browser },
  },
  {
    files: [
      "worker.ts",
      "scripts/**/*.mjs",
      "tools/**/*.{js,mjs}",
      "vite.config.ts",
      "vitest.config.ts",
      "test/**/*.ts",
    ],
    languageOptions: { globals: { ...globals.node, ...globals.worker } },
  },
  {
    rules: {
      // tsc already enforces noUnusedLocals/Parameters; keep the `_` escape hatch aligned.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" },
      ],
      "no-console": "off",
      eqeqeq: ["error", "always", { null: "ignore" }],
      "prefer-const": "error",
      "no-var": "error",
    },
  }
);

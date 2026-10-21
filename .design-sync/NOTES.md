# design-sync notes

- Project: "Mifrat Design System", https://claude.ai/design/p/f8e81bdf-9af2-4bd4-ab55-f4d4cd278eb9 (pinned in config.json). Re-sync = rebuild, validate, then atomic upload (sentinel, content, deletes, sentinel, `_ds_sync.json` last).
- **Look-only sync (owner decision 2026-10-21).** `site/` has no framework: `src/ui/*.ts` return HTML strings, so there are no React components for Claude Design. Only the look is synced (tokens, base, components and utilities CSS, plus fonts). The design agent writes its own JSX with these class names. Don't run `package-build.mjs`; it needs a React `dist/`.
- **Build (from the repo root):** `node .design-sync/build-css-bundle.mjs`, then `node .ds-sync/package-validate.mjs ./ds-bundle --no-render-check` (there are no previews to render). Stage `.ds-sync/` from the skill first so the anchor uses the skill's `styleShaFor`. The script falls back to its own hash otherwise.
- The script mirrors `site/src/styles/index.css` imports and layer order, minus `views/` (page layouts). Fonts come from `site/node_modules/@fontsource` (run `npm ci` in `site/` first). It ships woff2 only, the hebrew/latin/latin-ext subsets, and the weights `main.ts` loads.
- Validator `tokens: 2 missing` = `--hi` and `--lo`, which the range slider sets at runtime. Expected.
- Conventions check: grep every class and token named in `conventions.md` against `ds-bundle/tokens/**`. Names like `btn--md`, `chip--neutral` and `state--error` are emitted by the TS but have no CSS. Keep them out of the conventions.
- Visual spot check: serve `ds-bundle/` (`node .ds-sync/storybook/http-serve.mjs ./ds-bundle`) and open a hand-written `.check.html` (dot-prefixed, so it never uploads), in light and in `data-theme="dark"`.

## Re-sync risks
- New stylesheet added to `index.css` → picked up automatically, unless it's in the `views` layer.
- New font weight imported in `site/src/main.ts` → update the `FONTS` table in the script.

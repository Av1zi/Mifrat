#!/usr/bin/env node
// Look-only Claude Design bundle: the site has no React components (src/ui/*
// return HTML strings), so this ships tokens + base/component/utility CSS +
// fonts and a tokens-only (componentCount 0) bundle stub the app requires.
//
// Usage (repo root): node .design-sync/build-css-bundle.mjs [outDir=ds-bundle]
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = resolve(ROOT, process.argv[2] ?? "ds-bundle");
const STYLES = join(ROOT, "site/src/styles");
const FONTSRC = join(ROOT, "site/node_modules/@fontsource");
const cfg = JSON.parse(readFileSync(join(ROOT, ".design-sync/config.json"), "utf8"));

rmSync(OUT, { recursive: true, force: true });
const put = (rel, data) => {
  mkdirSync(dirname(join(OUT, rel)), { recursive: true });
  writeFileSync(join(OUT, rel), data);
};
const cp = (src, rel) => {
  mkdirSync(dirname(join(OUT, rel)), { recursive: true });
  copyFileSync(src, join(OUT, rel));
};

// ---- CSS: same files and layer order as site/src/styles/index.css, minus
// the page-specific views/ layer (app layouts, not reusable look).
const index = readFileSync(join(STYLES, "index.css"), "utf8");
const imports = [...index.matchAll(/@import\s+"\.\/([^"]+)"\s+layer\((\w+)\);/g)]
  .map(([, file, layer]) => ({ file, layer }))
  .filter((i) => i.layer !== "views");
for (const { file } of imports) cp(join(STYLES, file), `tokens/${file}`);

// ---- fonts: the weights main.ts loads, hebrew + latin subsets, woff2 only.
if (!existsSync(FONTSRC)) throw new Error("site/node_modules missing - run `npm ci` in site/");
const FONTS = [
  { pkg: "ibm-plex-sans-hebrew", family: "IBM Plex Sans Hebrew", weights: [400, 500, 600, 700], subsets: ["hebrew", "latin", "latin-ext"] },
  { pkg: "jetbrains-mono", family: "JetBrains Mono", weights: [400, 500], subsets: ["latin", "latin-ext"] },
];
let fontsCss = "/* Generated from @fontsource (SIL OFL 1.1). */\n";
for (const f of FONTS) {
  cp(join(FONTSRC, f.pkg, "LICENSE"), `fonts/${f.pkg}.LICENSE.txt`);
  for (const w of f.weights) {
    for (const s of f.subsets) {
      const css = readFileSync(join(FONTSRC, f.pkg, `${s}-${w}.css`), "utf8");
      const range = /unicode-range:\s*([^;]+);/.exec(css)?.[1];
      const file = `${f.pkg}-${s}-${w}-normal.woff2`;
      cp(join(FONTSRC, f.pkg, "files", file), `fonts/${file}`);
      fontsCss += `@font-face {\n  font-family: "${f.family}";\n  font-style: normal;\n  font-display: swap;\n  font-weight: ${w};\n  src: url("./${file}") format("woff2");\n${range ? `  unicode-range: ${range};\n` : ""}}\n`;
    }
  }
}
put("fonts/fonts.css", fontsCss);

// ---- styles.css: the closure every rendered design receives.
const layers = [...new Set(imports.map((i) => i.layer))];
put(
  "styles.css",
  `/* Mifrat design system - look only (tokens, base, components, utilities). */\n` +
    `@layer ${layers.join(", ")};\n\n` +
    `@import "./fonts/fonts.css";\n` +
    imports.map(({ file, layer }) => `@import "./tokens/${file}" layer(${layer});`).join("\n") +
    "\n",
);

// ---- bundle stub: no components, but the app's self-check needs the header.
const ns = cfg.globalName ?? "Mifrat";
const header = { namespace: ns, components: [], sourceHashes: {}, inlinedExternals: [] };
const bundle = `/* @ds-bundle: ${JSON.stringify(header)} */\nwindow.${ns} = window.${ns} || {};\n`;
put("_ds_bundle.js", bundle);

// ---- README: conventions header + generated body.
const conventions = cfg.readmeHeader ? readFileSync(join(ROOT, cfg.readmeHeader), "utf8").trim() + "\n\n" : "";
put(
  "README.md",
  conventions +
    `## Files\n\n- \`styles.css\` - entry; imports fonts and every stylesheet below in cascade-layer order.\n` +
    imports.map(({ file, layer }) => `- \`tokens/${file}\` (layer \`${layer}\`)`).join("\n") +
    `\n- \`fonts/fonts.css\` - IBM Plex Sans Hebrew 400-700, JetBrains Mono 400-500.\n\n` +
    `No React components ship: this is a look-only design system. Build markup with the classes above.\n`,
);

put("_ds_needs_recompile", JSON.stringify({ by: "design-sync-cli" }));
put(".ds-build-meta.json", JSON.stringify({ shape: "package", componentCount: 0, offScript: "build-css-bundle.mjs" }, null, 2));

// ---- anchor, via the skill's own hash helper when staged in .ds-sync/.
let styleSha = null;
try {
  const { styleShaFor } = await import(new URL("../.ds-sync/lib/sync-hashes.mjs", import.meta.url).href);
  styleSha = styleShaFor(OUT, { includeBundleBody: true });
} catch {
  const h = createHash("sha256");
  const walk = (d) => readdirSync(d, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))
    .forEach((e) => (e.isDirectory() ? walk(join(d, e.name)) : !e.name.startsWith(".") && h.update(e.name).update(readFileSync(join(d, e.name)))));
  walk(OUT);
  styleSha = h.digest("hex");
}
const bundleSha12 = createHash("sha256").update(bundle).digest("hex").slice(0, 12);
put("_ds_sync.json", JSON.stringify({ shape: "package", styleSha, renderHashes: {}, sourceKeys: {}, sourceHashes: {}, bundleSha12 }, null, 2));

console.log(`built ${OUT}: ${imports.length} stylesheets, ${readdirSync(join(OUT, "fonts")).length} font files`);

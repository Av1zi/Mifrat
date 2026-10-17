// `npm run lint` entry. ESLint's toolchain is a separate package (see
// package.json here), so install it on first use, then lint the site.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const site = join(here, "..", "..");
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
// npm.cmd needs a shell on Windows; node itself must not go through one (spaces in its path).
const run = (cmd, args, cwd, shell = false) =>
  spawnSync(cmd, args, { cwd, stdio: "inherit", shell }).status ?? 1;

if (!existsSync(join(here, "node_modules", "eslint"))) {
  const status = run(npm, ["ci", "--no-audit", "--no-fund"], here, process.platform === "win32");
  if (status !== 0) process.exit(status);
}

const eslint = join(here, "node_modules", "eslint", "bin", "eslint.js");
process.exit(
  run(
    process.execPath,
    [eslint, "--config", join(here, "eslint.config.js"), ...process.argv.slice(2), "."],
    site
  )
);

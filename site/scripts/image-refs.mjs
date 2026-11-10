// Which "/images/..." strings in the site JSON copy-data.mjs may turn into
// filesystem paths. Vendor titles reach that JSON too, so a ref is trusted
// only when it has the exact shape scraper/site_data.py writes
// (<vendor>/[thumbs|covers256/]<_safe_image_stem>.webp) and the resolved
// path stays inside its root.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

const SAFE_REF = /^[a-z0-9]+\/(?:(?:thumbs|covers256)\/)?[A-Za-z0-9._-]+\.webp$/;

export const isSafeImageRef = (rel) => typeof rel === "string" && SAFE_REF.test(rel);

export const isInsideDir = (root, target) => {
  const rel = path.relative(path.resolve(root), path.resolve(target));
  return rel !== "" && !path.isAbsolute(rel) && rel.split(path.sep)[0] !== "..";
};

export const collectImageRefs = (dir) => {
  const refs = new Set();
  const rejected = [];
  const walk = (current) => {
    if (!existsSync(current)) return;
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (!entry.name.endsWith(".json")) continue;
      const text = readFileSync(full, "utf8");
      const re = /"\/images\/([^"]+)"/g;
      let m;
      while ((m = re.exec(text)) !== null) {
        let rel = m[1];
        try {
          rel = decodeURIComponent(rel);
        } catch {
          // keep the raw text; it fails the shape check below
        }
        if (isSafeImageRef(rel)) refs.add(rel);
        else rejected.push(rel);
      }
    }
  };
  walk(dir);
  return { refs, rejected };
};

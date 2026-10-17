import { safeImageUrl } from "../utils";
import { html, type Html } from "./html";

type ThumbSize = "sm" | "md" | "lg" | "xl";

const PIXELS: Record<ThumbSize, number> = { sm: 40, md: 72, lg: 120, xl: 480 };

export function initialsOf(brand: string | null | undefined, name: string): string {
  return (brand ?? name).trim().slice(0, 2).toUpperCase() || "•";
}

/**
 * The only product-image primitive. Remote or missing images render the
 * initials fallback; a broken local image swaps to it via bindThumbs().
 */
export function thumb(
  src: string | null | undefined,
  initials: string,
  size: ThumbSize = "md",
  alt = "",
  priority = false
): Html {
  const safe = safeImageUrl(src);
  if (!safe) {
    return html`<span class="thumb thumb--${size}" aria-hidden="true">${initials}</span>`;
  }
  const px = PIXELS[size];
  return html`<span class="thumb thumb--${size}"><img src="${safe}" alt="${alt}" width="${px}" height="${px}" ${priority ? html`fetchpriority="high"` : html`loading="lazy" decoding="async"`} data-fb="${initials}"></span>`;
}

/** Swaps failed `<img data-fb>` thumbnails for the initials fallback. */
export function bindThumbs(root: ParentNode): void {
  root.querySelectorAll<HTMLImageElement>("img[data-fb]").forEach((img) => {
    const swap = (): void => {
      const holder = img.parentElement;
      if (!holder) return;
      holder.setAttribute("aria-hidden", "true");
      holder.textContent = img.dataset.fb || "•";
    };
    img.addEventListener("error", swap, { once: true });
    if (img.complete && img.naturalWidth === 0) swap();
  });
}

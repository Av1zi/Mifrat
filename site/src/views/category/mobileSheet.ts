/**
 * Off-canvas filter panel (below the lg breakpoint; inline column above).
 * Returns the cleanup that index.ts runs when the route changes.
 */
export function bindMobileSheet(container: HTMLElement): { open(open: boolean): void; dispose(): void } {
  const sheet = container.querySelector<HTMLElement>("#filter-rail")!;
  const backdrop = container.querySelector<HTMLElement>('[data-role="backdrop"]')!;
  const opener = container.querySelector<HTMLElement>('[data-role="filters-open"]');

  const open = (on: boolean): void => {
    sheet.classList.toggle("is-open", on);
    backdrop.hidden = !on;
    opener?.setAttribute("aria-expanded", String(on));
    document.body.classList.toggle("is-locked", on);
    if (on) sheet.querySelector<HTMLElement>('[data-role="filters-close"]')?.focus();
    else opener?.focus();
  };

  backdrop.addEventListener("click", () => open(false));
  // Close/apply live inside the rail; delegate from the persistent element.
  sheet.addEventListener("click", (e) => {
    const role = (e.target as HTMLElement).closest<HTMLElement>("[data-role]")?.dataset.role;
    if (role === "filters-close" || role === "filters-apply") open(false);
  });
  const onKey = (e: KeyboardEvent): void => {
    if (e.key === "Escape" && sheet.classList.contains("is-open")) open(false);
  };
  document.addEventListener("keydown", onKey);

  return {
    open,
    dispose() {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("is-locked");
    },
  };
}

/**
 * Off-canvas filter panel (below the lg breakpoint; inline column above).
 * Returns the cleanup that index.ts runs when the route changes.
 *
 * The page behind the open sheet is locked by pinning the body in place
 * (overflow: hidden alone does not stop iOS Safari scrolling it), and the
 * scroll position is restored on close so the list is where it was left.
 */
export function bindMobileSheet(container: HTMLElement): { open(open: boolean): void; dispose(): void } {
  const sheet = container.querySelector<HTMLElement>("#filter-rail")!;
  const backdrop = container.querySelector<HTMLElement>('[data-role="backdrop"]')!;
  const opener = container.querySelector<HTMLElement>('[data-role="filters-open"]');
  const body = sheet.querySelector<HTMLElement>(".sheet__body");
  const desktop = window.matchMedia("(min-width: 1024px)");
  let lockedAt: number | null = null;

  const lock = (): void => {
    if (lockedAt !== null) return;
    lockedAt = window.scrollY;
    document.body.style.top = `-${lockedAt}px`;
    document.body.classList.add("is-locked");
  };
  const unlock = (): void => {
    if (lockedAt === null) return;
    const y = lockedAt;
    lockedAt = null;
    document.body.classList.remove("is-locked");
    document.body.style.top = "";
    window.scrollTo({ top: y, behavior: "instant" });
    // Filtering can shrink the list under the old position; land on the
    // results head instead of past the end of a short list.
    const head = container.querySelector<HTMLElement>(".list-head__count");
    if (head && head.getBoundingClientRect().bottom < 0) head.scrollIntoView({ block: "start", behavior: "instant" });
  };

  const isOpen = (): boolean => sheet.classList.contains("is-open");
  const open = (on: boolean): void => {
    if (on === isOpen()) return;
    sheet.classList.toggle("is-open", on);
    backdrop.hidden = !on;
    opener?.setAttribute("aria-expanded", String(on));
    if (on) {
      lock();
      if (body) body.scrollTop = 0;
      sheet.querySelector<HTMLElement>('[data-role="filters-close"]')?.focus({ preventScroll: true });
    } else {
      unlock();
      opener?.focus({ preventScroll: true });
    }
  };

  backdrop.addEventListener("click", () => open(false));
  // Close/apply live inside the rail; delegate from the persistent element.
  sheet.addEventListener("click", (e) => {
    const role = (e.target as HTMLElement).closest<HTMLElement>("[data-role]")?.dataset.role;
    if (role === "filters-close" || role === "filters-apply") open(false);
  });
  const onKey = (e: KeyboardEvent): void => {
    if (e.key === "Escape" && isOpen()) open(false);
  };
  document.addEventListener("keydown", onKey);
  // Rotating or resizing into the desktop layout turns the sheet into the inline rail.
  const onBreakpoint = (): void => {
    if (desktop.matches) open(false);
  };
  desktop.addEventListener("change", onBreakpoint);

  return {
    open,
    dispose() {
      document.removeEventListener("keydown", onKey);
      desktop.removeEventListener("change", onBreakpoint);
      sheet.classList.remove("is-open");
      // The next view starts at the top (main.ts), so no position to restore.
      lockedAt = null;
      document.body.classList.remove("is-locked");
      document.body.style.top = "";
    },
  };
}

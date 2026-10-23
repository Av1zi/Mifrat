import { loadCategory, loadIndex } from "../api";
import { BUILD_SLOTS, checkCompatibility, knownPartWattage, slotForCategory } from "../build";
import { formatPrice } from "../format";
import { categoryLabel, partsCount, t } from "../i18n";
import { icon } from "../icons";
import { bestOffer, effectivePrice } from "../offers";
import { getSaved, onSavedChange } from "../saved";
import {
  duplicateSavedBuild,
  getSavedBuilds,
  removeSavedBuild,
  renameSavedBuild,
  type SavedBuild,
} from "../savedBuilds";
import { addToBuild, buildHash, categoriesHash, compareHash, getStoredBuild, navigate, parseRoute, productHash, setStoredBuild } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang, Product } from "../types";
import { html, mount, type Html } from "../ui/html";
import { pageHero } from "../ui/pageHero";
import { saveButtonRef, syncPickControls } from "../ui/pick";
import { emptyValue } from "../ui/empty";
import { loadingState } from "../ui/state";
import { bindThumbs, initialsOf, thumb } from "../ui/thumb";
import { vendorTag } from "../ui/vendor";
import { displayName } from "../utils";
import type { SavedPart } from "../saved";

type Tab = "all" | "products" | "builds";

/** Bumped per render so a superseded instance (language switch) stops redrawing. */
let generation = 0;

/** Live catalog rows for every id the page needs, looked up by category via index.json. */
async function resolve(ids: string[]): Promise<Map<string, Product>> {
  const out = new Map<string, Product>();
  if (ids.length === 0) return out;
  const index = await loadIndex().catch(() => []);
  const categoryOf = new Map(index.map((row) => [row[0], row[1]]));
  const categories = [...new Set(ids.map((id) => categoryOf.get(id)).filter((c): c is string => !!c))];
  await Promise.all(
    categories.map(async (category) => {
      const products = await loadCategory(category).catch(() => [] as Product[]);
      for (const p of products) if (ids.includes(p.id)) out.set(p.id, p);
    })
  );
  return out;
}

function productCard(ref: SavedPart, product: Product | undefined, lang: Lang, currency: Currency): Html {
  const href = productHash(ref.category, ref.id);
  const price = product ? effectivePrice(product) : null;
  const offer = product ? bestOffer(product) : null;
  const canAdd = slotForCategory(ref.category) !== null && product !== undefined;
  return html`<article class="card pcard">
    <span class="pcard__heart">${saveButtonRef(ref, lang)}</span>
    <a class="pcard__img" href="${href}" tabindex="-1" aria-hidden="true">${thumb(product?.image ?? ref.thumb, initialsOf(ref.brand, ref.name), "lg")}</a>
    <div class="pcard__body">
      <span class="pcard__cat">${categoryLabel(ref.category, lang)}</span>
      <a class="pcard__name" href="${href}" dir="auto">${ref.name}</a>
      <div class="pcard__price">
        <b>${price !== null ? formatPrice(price, currency, lang) : emptyValue(lang)}</b>
        ${offer ? vendorTag(offer.vendor) : product ? "" : html`<span class="pcard__gone">${t(lang, "savedGone")}</span>`}
      </div>
      <div class="pcard__actions">
        <a class="btn btn--primary btn--sm" href="${href}">${t(lang, "allPrices")}</a>
        ${canAdd
          ? html`<button type="button" class="btn btn--ghost btn--sm" data-add-build="${ref.id}" data-category="${ref.category}">${icon("plus", 15)}<span>${t(lang, "toBuild")}</span></button>`
          : ""}
      </div>
    </div>
  </article>`;
}

interface ResolvedBuild {
  saved: SavedBuild;
  rows: Array<{ slot: string; product: Product }>;
}

function buildRows(saved: SavedBuild, products: Map<string, Product>): ResolvedBuild {
  const rows: ResolvedBuild["rows"] = [];
  for (const slot of BUILD_SLOTS) {
    for (const id of saved.build[slot.id] ?? []) {
      const product = products.get(id);
      if (product) rows.push({ slot: slot.id, product });
    }
  }
  return { saved, rows };
}

function buildTitle(b: ResolvedBuild, lang: Lang): string {
  if (b.saved.name) return b.saved.name;
  const cpu = b.rows.find((r) => r.slot === "cpu");
  return cpu ? displayName(cpu.product) : t(lang, "untitledBuild");
}

function buildCard(b: ResolvedBuild, lang: Lang, currency: Currency): Html {
  const { saved, rows } = b;
  const title = buildTitle(b, lang);
  const total = rows.reduce((sum, r) => sum + (effectivePrice(r.product) ?? 0), 0);
  const first: Record<string, Product> = {};
  for (const r of rows) first[r.slot] ??= r.product;
  const watts = rows.reduce((sum, r) => sum + knownPartWattage(r.slot, r.product), 0);
  const issues = checkCompatibility(first, watts);
  const errors = issues.filter((i) => i.level === "err").length;
  const gpu = rows.find((r) => r.slot === "gpu");
  const sub = saved.name && first.cpu ? `${displayName(first.cpu)}${gpu ? ` · ${displayName(gpu.product)}` : ""}` : gpu ? `${t(lang, "withLabel")} ${displayName(gpu.product)}` : "";
  const key = rows.slice(0, 4);
  const more = rows.length - key.length;
  const label = (slot: string): string => BUILD_SLOTS.find((s) => s.id === slot)?.label[lang] ?? slot;
  return html`<article class="card bcard" data-build="${saved.id}">
    <header class="bcard__top">
      <div class="bcard__title">
        <h3 class="bcard__name"><button type="button" class="bcard__rename" data-rename="${saved.id}" title="${t(lang, "renameBuild")}"><span dir="auto">${title}</span><span class="bcard__pen" aria-hidden="true">${icon("pencil", 14)}</span><span class="visually-hidden">${t(lang, "renameBuild")}</span></button></h3>
        ${sub ? html`<p class="bcard__sub" dir="auto">${sub}</p>` : ""}
        <p class="bcard__meta">
          <span>${partsCount(lang, rows.length)}</span>
          ${rows.length > 1
            ? issues.length === 0
              ? html`<span class="ok-tag">${icon("check", 13)}${t(lang, "allCompatible")}</span>`
              : html`<span class="ok-tag ${errors > 0 ? "ok-tag--err" : "ok-tag--warn"}">${icon("alert", 13)}${errors > 0 ? t(lang, "hasConflicts") : t(lang, "hasWarnings")}</span>`
            : ""}
        </p>
      </div>
      <button type="button" class="x-btn" data-remove-build="${saved.id}" aria-label="${t(lang, "deleteBuild")}: ${title}" title="${t(lang, "deleteBuild")}">${icon("trash", 17)}</button>
    </header>
    <div class="bcard__thumbs">${rows.map((r) => html`<a class="bcard__thumb" href="${productHash(r.product.category, r.product.id)}" title="${displayName(r.product)}">${thumb(r.product.thumb ?? r.product.image, initialsOf(r.product.brand, r.product.name), "sm")}</a>`)}</div>
    <ul class="bcard__parts">${key.map((r) => {
      const price = effectivePrice(r.product);
      return html`<li><span class="bcard__k">${label(r.slot)}</span><span class="bcard__v" dir="auto">${displayName(r.product)}</span><span class="bcard__pr">${price !== null ? formatPrice(price, currency, lang) : ""}</span></li>`;
    })}</ul>
    ${more > 0 ? html`<p class="bcard__more">${t(lang, "andMoreParts").replace("{n}", String(more))}</p>` : ""}
    <footer class="bcard__foot">
      <span class="bcard__total"><span>${t(lang, "totalShort")}</span><b>${formatPrice(total, currency, lang)}</b></span>
      <span class="bcard__actions">
        <button type="button" class="btn btn--ghost btn--sm" data-duplicate="${saved.id}" data-name="${title}">${icon("copy", 15)}<span>${t(lang, "duplicateBuild")}</span></button>
        <a class="btn btn--primary btn--sm" href="${buildHash(saved.build)}">${t(lang, "openBuild")}${icon("forward", 15)}</a>
      </span>
    </footer>
  </article>`;
}

/** Saved parts and parts lists (localStorage only), with live prices where the catalog still lists them. */
export async function renderSaved(container: HTMLElement, lang: Lang, currency: Currency): Promise<void> {
  setPageTitle(lang, t(lang, "savedNav"), t(lang, "metaSavedDesc"));
  const hero = pageHero({ lang, crumbs: [{ label: t(lang, "savedNav") }], title: t(lang, "savedNav"), sub: t(lang, "savedHeroSub") });
  mount(container, html`${hero}${loadingState(lang)}`);
  const mine = ++generation;
  const alive = (): boolean => mine === generation && parseRoute().view === "saved";
  let tab: Tab = "all";

  const draw = async (): Promise<void> => {
    const saved = getSaved();
    const builds = getSavedBuilds();
    const ids = [...saved.map((p) => p.id), ...builds.flatMap((b) => Object.values(b.build).flat())];
    const products = await resolve([...new Set(ids)]);
    if (!alive()) return;
    const resolved = builds.map((b) => buildRows(b, products));

    // "Compare saved": the biggest same-category group, up to four.
    const byCat = new Map<string, string[]>();
    for (const p of saved) byCat.set(p.category, [...(byCat.get(p.category) ?? []), p.id]);
    const group = [...byCat.values()].sort((a, b) => b.length - a.length)[0] ?? [];

    const tabBtn = (id: Tab, label: string, n: number): Html =>
      html`<button type="button" role="tab" class="stab" data-tab="${id}" aria-selected="${tab === id ? "true" : "false"}">${label}<span class="stab__n">${n}</span></button>`;

    mount(
      container,
      html`<div class="contents" data-saved-root>
        ${hero}
        <div class="saved-bar">
          <div class="stabs" role="tablist" aria-label="${t(lang, "savedFilter")}">
            ${tabBtn("all", t(lang, "allLabel"), saved.length + builds.length)}
            ${tabBtn("products", t(lang, "savedProducts"), saved.length)}
            ${tabBtn("builds", t(lang, "savedBuilds"), builds.length)}
          </div>
          ${group.length >= 2
            ? html`<a class="btn btn--ghost btn--sm" href="${compareHash(group.slice(0, 4))}">${icon("compare", 15)}<span>${t(lang, "compareSaved")}</span></a>`
            : ""}
        </div>
        <p class="notice" role="note">${icon("info", 18)}<span><b>${t(lang, "localOnlyTitle")}</b> ${t(lang, "localOnlyBody")}</span></p>

        <section class="saved-sec"${tab === "builds" ? html` hidden` : ""} aria-labelledby="saved-products">
          <header class="sec-head"><div><h2 id="saved-products">${t(lang, "savedProducts")}</h2><p>${t(lang, "savedProductsSub")}</p></div></header>
          ${saved.length > 0
            ? html`<div class="pgrid">${saved.map((ref) => productCard(ref, products.get(ref.id), lang, currency))}</div>`
            : html`<div class="card saved-empty"><b>${t(lang, "savedEmptyTitle")}</b><span>${t(lang, "savedEmpty")}</span><a class="btn btn--primary btn--sm" href="${categoriesHash()}">${t(lang, "savedBrowse")}</a></div>`}
        </section>

        <section class="saved-sec"${tab === "products" ? html` hidden` : ""} aria-labelledby="saved-builds">
          <header class="sec-head">
            <div><h2 id="saved-builds">${t(lang, "savedBuilds")}</h2><p>${t(lang, "savedBuildsSub")}</p></div>
            <a class="btn btn--primary btn--sm" href="#/build">${icon("plus", 15)}<span>${t(lang, "startNew")}</span></a>
          </header>
          ${resolved.length > 0
            ? html`<div class="bgrid">${resolved.map((b) => buildCard(b, lang, currency))}</div>`
            : html`<div class="card saved-empty"><b>${t(lang, "savedBuildsEmptyTitle")}</b><span>${t(lang, "savedBuildsEmpty")}</span><a class="btn btn--primary btn--sm" href="#/build">${t(lang, "builderNav")}</a></div>`}
        </section>
      </div>`
    );
    bindThumbs(container);
    syncPickControls();
    bind(container.querySelector<HTMLElement>("[data-saved-root]")!);
  };

  const startRename = (button: HTMLButtonElement): void => {
    const id = button.dataset.rename ?? "";
    const current = getSavedBuilds().find((b) => b.id === id);
    if (!current) return;
    const input = document.createElement("input");
    input.className = "input bcard__input";
    input.type = "text";
    input.maxLength = 60;
    input.value = current.name;
    input.placeholder = button.textContent?.trim() ?? "";
    input.setAttribute("aria-label", t(lang, "renameBuild"));
    let done = false;
    const finish = (save: boolean): void => {
      if (done) return;
      done = true;
      if (save && input.value.trim() !== current.name) renameSavedBuild(id, input.value);
      else void draw();
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") finish(true);
      else if (e.key === "Escape") finish(false);
    });
    input.addEventListener("blur", () => finish(true));
    button.replaceWith(input);
    input.focus();
    input.select();
  };

  const bind = (root: HTMLElement): void => {
    root.addEventListener("click", (e) => {
      const target = e.target as HTMLElement;
      const tabEl = target.closest<HTMLElement>("[data-tab]");
      if (tabEl) {
        tab = (tabEl.dataset.tab as Tab) ?? "all";
        void draw().then(() => container.querySelector<HTMLElement>(`[data-tab="${tab}"]`)?.focus());
        return;
      }
      const rename = target.closest<HTMLButtonElement>("[data-rename]");
      if (rename) {
        startRename(rename);
        return;
      }
      const remove = target.closest<HTMLElement>("[data-remove-build]");
      if (remove) {
        removeSavedBuild(remove.dataset.removeBuild ?? "");
        return;
      }
      const dup = target.closest<HTMLElement>("[data-duplicate]");
      if (dup) {
        duplicateSavedBuild(dup.dataset.duplicate ?? "", `${dup.dataset.name ?? ""} (${t(lang, "copyLabel")})`);
        return;
      }
      const add = target.closest<HTMLElement>("[data-add-build]");
      if (add) {
        const slot = slotForCategory(add.dataset.category ?? "");
        if (!slot) return;
        const build = getStoredBuild();
        addToBuild(build, slot.id, add.dataset.addBuild ?? "");
        setStoredBuild(build);
        navigate(buildHash(build));
      }
    });
  };

  await draw();

  // Hearts, renames and deletes (one storage event for parts and builds) redraw the page;
  // a stale instance unsubscribes itself.
  const off = onSavedChange(() => {
    if (alive()) void draw();
    else off();
  });
}

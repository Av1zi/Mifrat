import { loadCategory, resolveProductAlias } from "../../api";
import { slotForCategory } from "../../build";
import { categoryLabel, productMetaDesc, t } from "../../i18n";
import { icon } from "../../icons";
import { addToBuild, buildHash, categoriesHash, categoryHash, getStoredBuild, navigate, productHash, setStoredBuild } from "../../state";
import type { Currency, Lang } from "../../types";
import { formatPrice } from "../../format";
import { loadSignals } from "../../signals";
import { setPageTitle } from "../../titles";
import { card } from "../../ui/card";
import { bindPageTabs, pageHero } from "../../ui/pageHero";
import { syncPickControls } from "../../ui/pick";
import { positivePrice } from "../../ui/price";
import { signalBadges } from "../../ui/signal";
import { html, mount } from "../../ui/html";
import { emptyBox } from "../../ui/emptyBox";
import { errorState, loadingState } from "../../ui/state";
import { bindThumbs } from "../../ui/thumb";
import { displayName, skuOf } from "../../utils";
import { chipText, pickColumns } from "../category/columns";
import { buyBarMarkup, buyBoxMarkup, offersCard } from "./buybox";
import { renderPriceHistory } from "./history";
import { similarMarkup } from "./similar";
import { specsCard } from "./specs";
import { makeEchoOf, normEcho } from "./text";
import { variantsMarkup } from "./variants";

export async function renderProduct(
  container: HTMLElement,
  lang: Lang,
  currency: Currency,
  category: string,
  productId: string
): Promise<void> {
  mount(container, loadingState(lang));

  let products;
  try {
    products = await loadCategory(category);
  } catch (err) {
    mount(container, errorState(lang, err));
    return;
  }

  const product = products.find((p) => p.id === productId);
  if (!product) {
    // A retired pid (§3.6): the catalog rework moved this product's listings
    // under a new id, and a bookmark still points at the old one. Follow the
    // alias instead of declaring the product gone.
    const successor = await resolveProductAlias(productId);
    if (successor) {
      const moved = products.find((p) => p.id === successor);
      if (moved) {
        navigate(productHash(category, successor));
        return;
      }
    }
    mount(
      container,
      html`${pageHero({ lang, crumbs: [{ label: t(lang, "allCategoriesTitle"), href: categoriesHash() }, { label: categoryLabel(category, lang), href: categoryHash(category) }], title: t(lang, "productNotFound") })}
        ${emptyBox({
          icon: "search",
          title: t(lang, "productGoneTitle"),
          body: t(lang, "productGoneBody"),
          actions: html`<a class="btn btn--primary" href="${categoryHash(category)}">${t(lang, "backToCategory").replace("{c}", categoryLabel(category, lang))}</a>
            <a class="btn btn--ghost" href="#/build">${icon("wrench", 16)}${t(lang, "builderNav")}</a>`,
        })}`
    );
    return;
  }

  const name = displayName(product);
  const bestPrice = positivePrice(product.min_price);
  setPageTitle(
    lang,
    name,
    productMetaDesc(lang, name, product.vendor_count, bestPrice !== null ? formatPrice(bestPrice, currency, lang) : null)
  );
  const echoOf = makeEchoOf(name);
  const description = (product.description ?? "").trim();
  const brand = (product.brand ?? "").trim();
  const sku = skuOf(product).trim();
  // A brand line under a title that already starts with the brand reads as a stutter.
  const meta = [
    brand !== "" && !normEcho(name).startsWith(normEcho(brand)) ? brand : "",
    sku !== "" && !echoOf(sku) ? `${t(lang, "skuLabel")}: ${sku}` : "",
  ].filter(Boolean);

  const slot = slotForCategory(product.category);
  const similar = similarMarkup(product, products, lang, currency, echoOf);
  const chips = pickColumns([product], category)
    .map((field) => chipText(product, field, lang))
    .filter(Boolean)
    .slice(0, 6);
  const heroMeta =
    chips.length > 0 || meta.length > 0
      ? html`<div class="hero-chips">
          ${chips.map((c) => html`<span class="hero-chip"><bdi>${c}</bdi></span>`)}
          ${meta.length > 0 ? html`<span class="hero-chips__sku">${meta.join(" · ")}</span>` : ""}
        </div>`
      : html``;

  mount(
    container,
    html`
    ${pageHero({
      lang,
      crumbs: [
        { label: t(lang, "allCategoriesTitle"), href: categoriesHash() },
        { label: categoryLabel(category, lang), href: categoryHash(category) },
      ],
      title: name,
      titleDir: "auto",
      sub: description !== "" && !echoOf(description) ? description : undefined,
      meta: heroMeta,
      tabs: [
        { label: t(lang, "tabOverview"), href: "#pdp-top", active: true },
        { label: t(lang, "tabSpecs"), href: "#pdp-specs" },
        { label: t(lang, "tabHistory"), href: "#pdp-history" },
      ],
    })}
    <div class="pdp" id="pdp-top">
      <div class="pdp__buy">
        ${buyBoxMarkup(product, lang, currency, slot !== null, variantsMarkup(product, products, lang), name)}
        ${buyBarMarkup(product, lang, currency)}
        ${specsCard(product, lang, products)}
      </div>
      <div class="pdp__main">
        ${offersCard(product, lang, currency)}
        <section class="card" id="pdp-history" hidden></section>
        ${similar ? card(similar, { title: t(lang, "similarHeading") }) : ""}
      </div>
    </div>`
  );
  bindThumbs(container);
  syncPickControls();
  bindBuyBar(container);

  const add = container.querySelector<HTMLButtonElement>("#pdp-add");
  if (add && slot) {
    add.addEventListener("click", () => {
      const build = getStoredBuild();
      addToBuild(build, slot.id, product.id);
      setStoredBuild(build);
      navigate(buildHash(build));
    });
  }

  const historyHost = container.querySelector<HTMLElement>("#pdp-history");
  if (historyHost) void renderPriceHistory(historyHost, lang, currency, category, product.id);

  const signalHost = container.querySelector<HTMLElement>("#pdp-signals");
  if (signalHost) {
    void loadSignals(category).then((signals) => {
      if (signalHost.isConnected) mount(signalHost, signalBadges(signals.get(product.id), lang));
    });
  }
  bindPageTabs(container);
}

/**
 * Shows the buy bar once the buy box's own buy link (or, without one, the
 * price) is above the viewport. On phones and tablets it is pinned to the
 * bottom edge and steps aside while the offers card (a store link per row)
 * is on screen; on desktop it docks in the buy column beside the offers.
 */
function bindBuyBar(container: HTMLElement): void {
  const bar = container.querySelector<HTMLElement>('[data-role="buybar"]');
  const anchor = container.querySelector<HTMLElement>(".buy-cta, .buybox__price");
  const offers = container.querySelector<HTMLElement>("#pdp-offers");
  if (!bar || !anchor) return;
  const desktop = window.matchMedia("(min-width: 1024px)");
  let pastAnchor = false;
  let offersVisible = false;
  const sync = (): void => {
    const show = pastAnchor && (desktop.matches || !offersVisible);
    bar.classList.toggle("is-concealed", !show);
    // Concealed is still laid out on desktop: keep it out of reach then.
    bar.toggleAttribute("inert", !show);
    bar.setAttribute("aria-hidden", String(!show));
    document.body.classList.toggle("has-buybar", show && !desktop.matches);
  };
  desktop.addEventListener("change", sync);
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.target === anchor) pastAnchor = !entry.isIntersecting && entry.boundingClientRect.top < 0;
      else offersVisible = entry.isIntersecting;
    }
    sync();
  });
  // A reload can land mid-page: match the state before the first callback.
  pastAnchor = anchor.getBoundingClientRect().bottom < 0;
  sync();
  observer.observe(anchor);
  if (offers) observer.observe(offers);
  window.addEventListener(
    "hashchange",
    () => {
      observer.disconnect();
      desktop.removeEventListener("change", sync);
      document.body.classList.remove("has-buybar");
    },
    { once: true }
  );
}

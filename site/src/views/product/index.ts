import { loadCategory } from "../../api";
import { slotForCategory } from "../../build";
import { categoryLabel, productMetaDesc, t } from "../../i18n";
import { icon } from "../../icons";
import { addToBuild, buildHash, categoriesHash, categoryHash, getStoredBuild, navigate, setStoredBuild } from "../../state";
import type { Currency, Lang } from "../../types";
import { formatPrice } from "../../format";
import { loadSignals } from "../../signals";
import { setPageTitle } from "../../titles";
import { button } from "../../ui/button";
import { card } from "../../ui/card";
import { bindPageTabs, pageHero } from "../../ui/pageHero";
import { syncPickControls } from "../../ui/pick";
import { positivePrice } from "../../ui/price";
import { signalBadges } from "../../ui/signal";
import { html, mount } from "../../ui/html";
import { emptyState, errorState, loadingState } from "../../ui/state";
import { bindThumbs } from "../../ui/thumb";
import { displayName, skuOf } from "../../utils";
import { chipText, pickColumns } from "../category/columns";
import { buyBoxMarkup, offersCard } from "./buybox";
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
    mount(
      container,
      html`${pageHero({ lang, crumbs: [{ label: t(lang, "allCategoriesTitle"), href: categoriesHash() }, { label: categoryLabel(category, lang), href: categoryHash(category) }], title: t(lang, "productNotFound") })}
        ${emptyState(t(lang, "productNotFound"), button({ label: t(lang, "backToCategories"), icon: icon("back", 14), href: categoryHash(category) }))}`
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
      ${buyBoxMarkup(product, lang, currency, slot !== null, variantsMarkup(product, products, lang), name)}
      <div class="pdp__main">
        ${offersCard(product, lang, currency)}
        <section class="card" id="pdp-history" hidden></section>
        ${similar ? card(similar, { title: t(lang, "similarHeading") }) : ""}
      </div>
      ${specsCard(product, lang, products)}
    </div>`
  );
  bindThumbs(container);
  syncPickControls();

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

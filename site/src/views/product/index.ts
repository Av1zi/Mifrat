import { loadCategory } from "../../api";
import { slotForCategory } from "../../build";
import { categoryLabel, productMetaDesc, t } from "../../i18n";
import { icon } from "../../icons";
import { addToBuild, buildHash, categoriesHash, categoryHash, getStoredBuild, navigate, setStoredBuild } from "../../state";
import type { Currency, Lang } from "../../types";
import { formatPrice } from "../../format";
import { loadSignals } from "../../signals";
import { setPageTitle } from "../../titles";
import { card } from "../../ui/card";
import { syncPickControls } from "../../ui/pick";
import { positivePrice } from "../../ui/price";
import { signalBadges } from "../../ui/signal";
import { html, mount } from "../../ui/html";
import { emptyState, errorState, loadingState } from "../../ui/state";
import { bindThumbs, initialsOf, thumb } from "../../ui/thumb";
import { displayName, skuOf } from "../../utils";
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
      html`<nav class="crumbs"><a href="${categoriesHash()}">${icon("back", 14)}${t(lang, "backToCategories")}</a></nav>
        ${emptyState(t(lang, "productNotFound"))}`
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

  mount(
    container,
    html`
    <nav class="crumbs">
      <a href="${categoriesHash()}">${icon("back", 14)}${t(lang, "backToCategories")}</a>
      <span class="crumbs__sep" aria-hidden="true">/</span>
      <a href="${categoryHash(category)}">${categoryLabel(category, lang)}</a>
    </nav>
    <header class="page-head">
      <p class="eyebrow">${categoryLabel(category, lang)}</p>
      <h1>${name}</h1>
      ${description !== "" && !echoOf(description) ? html`<p>${description}</p>` : ""}
      ${meta.length > 0 ? html`<p class="text-dim">${meta.join(" · ")}</p>` : ""}
    </header>
    <div class="pdp">
      ${card(thumb(product.image, initialsOf(product.brand, name), "xl", name, true), { className: "pdp__gallery" })}
      <div class="pdp__aside">${buyBoxMarkup(product, lang, currency, slot !== null, variantsMarkup(product, products, lang))}</div>
      <div class="pdp__main">
        ${offersCard(product, lang, currency)}
        <section class="card" id="pdp-history" hidden></section>
        ${specsCard(product, lang)}
        ${similar ? card(similar, { title: t(lang, "similarHeading") }) : ""}
      </div>
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
}

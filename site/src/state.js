"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.MULTI_SLOTS = void 0;
exports.getTheme = getTheme;
exports.setTheme = setTheme;
exports.applyStoredTheme = applyStoredTheme;
exports.getLang = getLang;
exports.setLang = setLang;
exports.getCurrency = getCurrency;
exports.setCurrency = setCurrency;
exports.getStoredBuild = getStoredBuild;
exports.setStoredBuild = setStoredBuild;
exports.addToBuild = addToBuild;
exports.removeFromBuild = removeFromBuild;
exports.buildItemCount = buildItemCount;
exports.parseRoute = parseRoute;
exports.categoryHash = categoryHash;
exports.productHash = productHash;
exports.buildHash = buildHash;
exports.homeHash = homeHash;
exports.navigate = navigate;
exports.replaceRoute = replaceRoute;
const LANG_KEY = "mifrat:lang";
const CURRENCY_KEY = "mifrat:currency";
const BUILD_KEY = "mifrat:build";
const THEME_KEY = "mifrat:theme";
function getTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "dark" || saved === "light")
        return saved;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function setTheme(theme) {
    localStorage.setItem(THEME_KEY, theme);
    document.documentElement.dataset.theme = theme;
}
function applyStoredTheme() {
    const theme = getTheme();
    document.documentElement.dataset.theme = theme;
    return theme;
}
function getLang() {
    return localStorage.getItem(LANG_KEY) === "en" ? "en" : "he";
}
function setLang(lang) {
    localStorage.setItem(LANG_KEY, lang);
}
function getCurrency() {
    return localStorage.getItem(CURRENCY_KEY) === "USD" ? "USD" : "ILS";
}
function setCurrency(currency) {
    localStorage.setItem(CURRENCY_KEY, currency);
}
exports.MULTI_SLOTS = new Set([
    "memory",
    "storage",
    "gpu",
    "psu",
]);
function getStoredBuild() {
    try {
        const raw = localStorage.getItem(BUILD_KEY);
        if (raw) {
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed === "object") {
                const out = {};
                for (const [key, value] of Object.entries(parsed)) {
                    if (Array.isArray(value)) {
                        const ids = value.filter((v) => typeof v === "string" && v.length > 0);
                        if (ids.length > 0)
                            out[key] = ids;
                    }
                    else if (typeof value === "string" && value) {
                        // Migrate pre-multi entries stored as a bare id string.
                        out[key] = [value];
                    }
                }
                return out;
            }
        }
    }
    catch {
        // corrupt entry — start fresh
    }
    return {};
}
function setStoredBuild(build) {
    localStorage.setItem(BUILD_KEY, JSON.stringify(build));
}
/** Append (multi slots) or replace (single slots), skipping duplicates. */
function addToBuild(build, slotId, productId) {
    const list = build[slotId] ?? [];
    if (exports.MULTI_SLOTS.has(slotId)) {
        if (!list.includes(productId))
            list.push(productId);
        build[slotId] = list;
    }
    else {
        build[slotId] = [productId];
    }
}
function removeFromBuild(build, slotId, productId) {
    const list = (build[slotId] ?? []).filter((id) => id !== productId);
    if (list.length > 0)
        build[slotId] = list;
    else
        delete build[slotId];
}
function buildItemCount(build) {
    return Object.values(build).reduce((n, ids) => n + ids.length, 0);
}
function defaultCategoryParams() {
    return {
        q: "",
        sort: "price_asc",
        stockOnly: false,
        filters: {},
        ranges: {},
        productId: null,
        pick: null,
    };
}
const VALID_SORTS = [
    "price_asc",
    "price_desc",
    "vendors_desc",
    "name",
];
function parseRoute() {
    const raw = location.hash.replace(/^#/, "");
    const [path, queryStr] = raw.split("?");
    if (path === "/build" || path === "/build/") {
        const search = new URLSearchParams(queryStr ?? "");
        const shared = {};
        // getAll keeps repeated params (?memory=a&memory=b) as multi picks.
        for (const key of new Set(search.keys())) {
            const ids = search.getAll(key).filter(Boolean);
            if (ids.length > 0)
                shared[key] = ids;
        }
        return {
            view: "build",
            shared: Object.keys(shared).length ? shared : null,
        };
    }
    const productMatch = /^\/p\/([^/]+)\/([^/]+)/.exec(path ?? "");
    if (productMatch) {
        return {
            view: "product",
            category: decodeURIComponent(productMatch[1]),
            productId: decodeURIComponent(productMatch[2]),
        };
    }
    const match = /^\/c\/([^/]+)/.exec(path ?? "");
    if (!match) {
        return { view: "home" };
    }
    const category = decodeURIComponent(match[1]);
    const params = defaultCategoryParams();
    const search = new URLSearchParams(queryStr ?? "");
    params.q = search.get("q") ?? "";
    const sort = search.get("sort");
    if (sort && VALID_SORTS.includes(sort)) {
        params.sort = sort;
    }
    params.stockOnly = search.get("stock") === "1";
    params.productId = search.get("p");
    params.pick = search.get("pick");
    for (const [key, value] of search.entries()) {
        if (key.startsWith("f.")) {
            const attrKey = key.slice(2);
            params.filters[attrKey] = value.split("|").filter(Boolean);
        }
        else if (key.startsWith("r.")) {
            const attrKey = key.slice(2);
            const [minStr, maxStr] = value.split(",");
            const min = minStr ? parseFloat(minStr) : null;
            const max = maxStr ? parseFloat(maxStr) : null;
            const minValid = min !== null && !isNaN(min);
            const maxValid = max !== null && !isNaN(max);
            if (minValid || maxValid) {
                params.ranges[attrKey] = { min: minValid ? min : null, max: maxValid ? max : null };
            }
        }
    }
    return { view: "category", category, params };
}
function categoryHash(category, params = {}) {
    const merged = {
        ...defaultCategoryParams(),
        ...params,
    };
    const search = new URLSearchParams();
    if (merged.q)
        search.set("q", merged.q);
    if (merged.sort !== "price_asc")
        search.set("sort", merged.sort);
    if (merged.stockOnly)
        search.set("stock", "1");
    if (merged.productId)
        search.set("p", merged.productId);
    if (merged.pick)
        search.set("pick", merged.pick);
    for (const [key, values] of Object.entries(merged.filters)) {
        if (values.length > 0)
            search.set(`f.${key}`, values.join("|"));
    }
    for (const [key, range] of Object.entries(merged.ranges)) {
        const minStr = range.min !== null ? String(range.min) : "";
        const maxStr = range.max !== null ? String(range.max) : "";
        if (minStr || maxStr)
            search.set(`r.${key}`, `${minStr},${maxStr}`);
    }
    const query = search.toString();
    return `#/c/${encodeURIComponent(category)}${query ? `?${query}` : ""}`;
}
/** Shareable per-product page: #/p/<category>/<productId>. */
function productHash(category, productId) {
    return `#/p/${encodeURIComponent(category)}/${encodeURIComponent(productId)}`;
}
/** The build IS the URL — shareable with no backend. */
function buildHash(build) {
    const search = new URLSearchParams();
    for (const [slot, ids] of Object.entries(build)) {
        for (const id of ids) {
            if (id)
                search.append(slot, id);
        }
    }
    const query = search.toString();
    return `#/build${query ? `?${query}` : ""}`;
}
function homeHash() {
    return "#/";
}
/** Real navigation: adds a history entry. */
function navigate(hash) {
    location.hash = hash;
}
/**
In-page state changes: updates address bar without adding history entry.
Does NOT fire hashchange — callers re-render locally.
*/
function replaceRoute(hash) {
    history.replaceState(null, "", hash);
}

// Orion Web. Product names and URLs are text from shop pages: inserted with textContent only.
"use strict";

let data = null;
const money = (v) => (v == null ? "–" : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const ago = (iso) => {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} days ago`;
};
const host = (url) => { try { return new URL(url).host; } catch { return url; } };

function render(d) {
  data = d;
  $("#version").textContent = `v${d.version}`;
  $("#demo").hidden = !d.demo;
  $("#telegram").textContent = d.demo ? "Demo: nothing is fetched or sent" : d.telegram ? "Telegram alerts on" : "Telegram off: prices are only logged";
  $("#check-all").disabled = d.demo || !d.products.length;

  const below = d.products.filter((p) => p.status === "below").length;
  const savings = d.products.filter((p) => p.price != null && p.history.length)
    .reduce((sum, p) => sum + Math.max(0, p.history[0] - p.price), 0);
  const stat = (value, label) => el("div", { class: "stat" }, el("div", { class: "stat__value" }, value), el("div", { class: "stat__label" }, label));
  $("#stats").replaceChildren(
    stat(d.products.length, "products watched"),
    stat(below, "at or below target"),
    stat(money(savings), "cheaper than first seen"),
    stat(ago(d.products.map((p) => p.checked).filter(Boolean).sort().at(-1)), "last check"),
  );

  const list = $("#products");
  if (!d.products.length) {
    list.replaceChildren(el("div", { class: "empty" }, el("p", {}, "The watchlist is empty."), el("p", { class: "muted" }, "Add a product page on the left.")));
    return;
  }
  const order = { below: 0, above: 1, unchecked: 2 };
  const products = [...d.products].sort((a, b) => order[a.status] - order[b.status] || (a.price ?? 0) / a.target - (b.price ?? 0) / b.target);
  list.replaceChildren(...products.map(card));
  for (const message of d.errors || []) list.prepend(el("p", { class: "error" }, `watchlist.txt ${message}`));
}

function card(p) {
  const gap = p.price == null ? null : (p.price - p.target) / p.target;
  const status = p.status === "below"
    ? el("span", { class: "badge badge--good" }, p.alerted ? "target reached · alert sent" : "target reached")
    : p.status === "above" ? el("span", { class: "badge" }, `${(gap * 100).toFixed(1)} % above target`)
    : el("span", { class: "badge badge--warn" }, "not checked yet");
  const first = p.history[0];
  const change = first && p.price != null ? (p.price - first) / first : null;
  const progress = p.price == null ? 0 : Math.max(0, Math.min(1, p.target / p.price));

  return el("article", { class: `product product--${p.status}` },
    el("div", { class: "product__main" },
      el("div", { class: "product__head" },
        el("div", {},
          el("h2", { class: "product__name" }, p.name || host(p.url)),
          el("a", { class: "product__url", href: p.url, target: "_blank", rel: "noopener noreferrer" }, host(p.url))),
        status),
      el("div", { class: "product__prices" },
        el("div", {}, el("div", { class: "price" }, money(p.price)), el("div", { class: "note" }, "now")),
        el("div", {}, el("div", { class: "price price--target" }, money(p.target)), el("div", { class: "note" }, "target")),
        el("div", {}, el("div", { class: `price price--small ${change < 0 ? "down" : change > 0 ? "up" : ""}` },
          change == null ? "–" : `${change > 0 ? "+" : ""}${(change * 100).toFixed(1)} %`), el("div", { class: "note" }, "since first check"))),
      el("div", { class: "meter", role: "img", "aria-label": `${Math.round(progress * 100)} % of the way to the target` },
        meterFill(progress))),
    el("div", { class: "product__chart" },
      sparkline(p.history, { color: p.status === "below" ? "var(--good)" : "var(--accent)", target: p.target, height: 64 }),
      el("div", { class: "note chart-note" },
        el("span", {}, `low ${money(p.low)} · high ${money(p.high)}`),
        el("span", {}, `checked ${ago(p.checked)}`))),
    el("div", { class: "product__actions" },
      el("button", { class: "btn btn--small", type: "button", disabled: data.demo, onclick: () => check(p.url) }, "Check"),
      el("button", { class: "btn btn--small btn--ghost", type: "button", onclick: () => remove(p) }, "Remove")));
}

function meterFill(fraction) {
  const span = el("span");
  span.style.width = `${(fraction * 100).toFixed(1)}%`;  // CSSOM, allowed by the CSP
  return span;
}

async function load() {
  try { render(await api("/api/products")); } catch (error) { toast(error.message); }
}

async function check(url) {
  const button = $("#check-all");
  button.disabled = true;
  button.textContent = "Checking…";
  try {
    const d = await api("/api/check", url ? { url } : {});
    render(d);
    toast(d.failed.length ? `${d.failed.length} page(s) could not be read` : "Prices updated");
  } catch (error) {
    toast(error.message);
  } finally {
    button.textContent = "Check all now";
    button.disabled = data?.demo;
  }
}

async function remove(p) {
  if (!confirm(`Stop watching "${p.name || host(p.url)}"? Its price history stays in price_history.csv.`)) return;
  try { render(await api("/api/products/remove", { url: p.url })); } catch (error) { toast(error.message); }
}

const form = $("#add-form");
function formData() {
  const f = new FormData(form);
  return { url: f.get("url").trim(), target: Number(f.get("target")), selector: f.get("selector").trim(), name: f.get("name").trim() };
}
function showError(text) { const e = $("#add-error"); e.textContent = text; e.hidden = !text; }

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = formData();
  showError("");
  if (!body.url || !(body.target > 0)) return showError("A product URL and a target price are needed.");
  try {
    render(await api("/api/products", body));
    form.reset();
    $("#preview").hidden = true;
    toast("Added to the watchlist");
  } catch (error) { showError(error.message); }
});

$("#preview-btn").addEventListener("click", async () => {
  const { url, selector } = formData();
  showError("");
  if (!url) return showError("Enter a product URL first.");
  const box = $("#preview");
  box.hidden = false;
  box.replaceChildren(el("span", { class: "note" }, "Loading the page…"));
  try {
    const r = await api("/api/preview", { url, selector });
    box.replaceChildren(r.price == null
      ? el("span", {}, "No price found. Try a CSS selector such as ", el("span", { class: "mono" }, ".price"), ".")
      : el("span", {}, el("b", {}, money(r.price)), ` · ${r.name || "unnamed"} · found via ${r.source}`));
    if (r.name && !form.elements.name.value) form.elements.name.value = r.name.slice(0, 120);
  } catch (error) { box.replaceChildren(el("span", { class: "error" }, error.message)); }
});

$("#check-all").addEventListener("click", () => check());
load();

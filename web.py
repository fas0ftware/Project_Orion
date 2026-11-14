#!/usr/bin/env python3
"""Orion Web: the watchlist in the browser.

    python web.py              # uses watchlist.txt, orion_state.json and price_history.csv here
    python web.py --demo       # fictional products and price history, nothing is fetched

Add or remove products, see each price against its target with its history, check
pages now, and try a CSS selector on a page before adding it. The same files are
used by `python main.py`, so the web page and the hourly checker can run together.
Local only: see web_base.py for the safety rules.
"""
import argparse
import csv
import os
import random
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

import requests

import main as orion
from web_base import App, HttpError, field

HERE = Path(__file__).resolve().parent
HISTORY_POINTS = 60


class Orion:
    def __init__(self, folder: Path, demo: bool = False):
        self.folder = folder
        self.demo = demo
        self.lock = threading.Lock()
        self.watchlist = folder / "watchlist.txt"
        self.state_file = str(folder / orion.STATE_FILE)
        self.history_file = str(folder / orion.HISTORY_FILE)

    # --- files ---------------------------------------------------------------------------
    def products(self):
        if not self.watchlist.exists():
            return [], []
        return orion.parse_watchlist(self.watchlist.read_text(encoding="utf-8"))

    def history(self):
        rows = {}
        if os.path.exists(self.history_file):
            with open(self.history_file, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    try:
                        rows.setdefault(row["url"], []).append((row["time"], float(row["price"])))
                    except (KeyError, ValueError, TypeError):
                        continue
        return rows

    def listing(self):
        products, errors = self.products()
        state = orion.load_state(self.state_file)
        history = self.history()
        out = []
        for p in products:
            s = state.get(p.url, {})
            points = history.get(p.url, [])
            prices = [price for _, price in points]
            price = s.get("price", prices[-1] if prices else None)
            status = "unchecked" if price is None else ("below" if price <= p.target else "above")
            out.append({
                "url": p.url, "name": p.name or "", "target": p.target, "selector": p.selector or "",
                "price": price, "low": min(prices) if prices else s.get("low"),
                "high": max(prices) if prices else None, "checked": s.get("checked"),
                "alerted": s.get("alerted_price") is not None, "status": status,
                "history": prices[-HISTORY_POINTS:], "since": points[0][0] if points else None,
            })
        return {"demo": self.demo, "telegram": bool(os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")),
                "products": out, "errors": errors, "version": orion.__version__}

    def add(self, url, target, selector, name):
        for value in (url, selector, name):
            if "|" in value or "\n" in value or "\r" in value:
                raise HttpError(400, "fields cannot contain | or line breaks")
        line = " | ".join([url, f"{target:g}", selector, name]).rstrip(" |")
        parsed, errors = orion.parse_watchlist(line)
        if errors or not parsed:
            raise HttpError(400, (errors or ["invalid product"])[0].replace("line 1: ", ""))
        with self.lock:
            products, _ = self.products()
            if any(p.url == url for p in products):
                raise HttpError(409, "this page is already on the watchlist")
            text = self.watchlist.read_text(encoding="utf-8") if self.watchlist.exists() else \
                "# URL | target price | CSS selector | name\n"
            if text and not text.endswith("\n"):
                text += "\n"
            self.watchlist.write_text(text + line + "\n", encoding="utf-8")

    def remove(self, url):
        with self.lock:
            if not self.watchlist.exists():
                raise HttpError(404, "no watchlist")
            lines = self.watchlist.read_text(encoding="utf-8").splitlines(keepends=True)
            kept = [ln for ln in lines if ln.strip().startswith("#") or ln.split("|")[0].strip() != url]
            if len(kept) == len(lines):
                raise HttpError(404, "not on the watchlist")
            self.watchlist.write_text("".join(kept), encoding="utf-8")

    def check(self, url=None):
        if self.demo:
            raise HttpError(409, "demo mode: no shop pages are fetched")
        products, _ = self.products()
        chosen = [p for p in products if url is None or p.url == url]
        if not chosen:
            raise HttpError(404, "not on the watchlist")
        token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        telegram = (lambda msg: orion.send_telegram_message(token, chat, msg)) if token and chat else None
        with self.lock:
            cwd = os.getcwd()
            os.chdir(self.folder)  # append_history writes next to the watchlist
            try:
                state = orion.load_state(self.state_file)
                failed = [p.url for p in chosen if orion.check_product(p, state, telegram) is None]
                orion.save_state(state, self.state_file)
            finally:
                os.chdir(cwd)
        return failed

    def preview(self, url, selector):
        if self.demo:
            raise HttpError(409, "demo mode: no shop pages are fetched")
        products, errors = orion.parse_watchlist(f"{url} | 1")
        if errors:
            raise HttpError(400, "not an http(s) URL")
        try:
            name, price, source = orion.extract_price(orion.fetch(url), selector or None)
        except (requests.RequestException, RuntimeError) as error:
            raise HttpError(502, f"could not load the page: {error if isinstance(error, RuntimeError) else type(error).__name__}")
        return {"name": name, "price": price, "source": source}


def seed_demo(folder: Path):
    """Fictional shop, products and 45 days of prices. Clearly not real data."""
    # Seeded so the demo looks the same every time; these are demo prices, not secrets.
    rng = random.Random(7)  # nosec B311
    items = [  # url, name, target, first price, price today
        ("https://shop.example/keyboard-k3", "Mechanical keyboard K3", 89.0, 109.0, 94.9),
        ("https://shop.example/headphones-nc700", "Noise-cancelling headphones", 199.0, 249.0, 189.0),
        ("https://shop.example/monitor-27q", "27-inch QHD monitor", 279.0, 319.0, 299.0),
        ("https://shop.example/grinder-g2", "Espresso grinder G2", 149.0, 139.0, 152.5),
        ("https://shop.example/ereader-6", "E-reader 6\"", 99.0, 129.0, 97.99),
    ]
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    lines = ["# URL | target price | CSS selector | name  (demo data)"]
    state = {}
    days = 45
    with open(folder / orion.HISTORY_FILE, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "url", "name", "price"])
        for url, name, target, start, end in items:
            lines.append(f"{url} | {target:g} | .price | {name}")
            prices = []
            for day in range(days):
                trend = start + (end - start) * day / (days - 1)
                noise = 0 if day in (0, days - 1) else rng.uniform(-1.5, 1.5) * start / 100
                sale = 0.9 if 0 < day < days - 3 and rng.random() < 0.05 else 1.0
                prices.append(round((trend + noise) * sale, 2))
                w.writerow([(now - timedelta(days=days - 1 - day)).isoformat(timespec="seconds"), url, name,
                            f"{prices[-1]:.2f}"])
            state[url] = {"price": prices[-1], "checked": now.isoformat(timespec="seconds"), "low": min(prices),
                          "alerted_price": prices[-1] if prices[-1] <= target else None}
    (folder / "watchlist.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    orion.save_state(state, str(folder / orion.STATE_FILE))


def build_app(core: Orion) -> App:
    app = App(HERE / "static")

    @app.get("/api/products")
    def products(query):
        return core.listing()

    @app.post("/api/products")
    def add(body):
        target = field(body, "target", float)
        if not 0 < target < 1e9:
            raise HttpError(400, "target must be a positive price")
        core.add(field(body, "url", max_len=2000), target, field(body, "selector", required=False, max_len=200, default=""),
                 field(body, "name", required=False, max_len=120, default=""))
        return core.listing()

    @app.post("/api/products/remove")
    def remove(body):
        core.remove(field(body, "url", max_len=2000))
        return core.listing()

    @app.post("/api/check")
    def check(body):
        url = field(body, "url", required=False, max_len=2000)
        failed = core.check(url or None)
        return core.listing() | {"failed": failed}

    @app.post("/api/preview")
    def preview(body):
        return core.preview(field(body, "url", max_len=2000), field(body, "selector", required=False, max_len=200, default=""))

    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Orion Web: the watchlist in the browser (local only)")
    parser.add_argument("--port", type=int, default=8741)
    parser.add_argument("--dir", default=".", help="folder with watchlist.txt (default: here)")
    parser.add_argument("--demo", action="store_true", help="fictional products; nothing is fetched")
    args = parser.parse_args(argv)
    if args.demo:
        folder = Path(tempfile.mkdtemp(prefix="orion-demo-"))
        seed_demo(folder)
    else:
        folder = Path(args.dir).resolve()
    build_app(Orion(folder, demo=args.demo)).serve(args.port, "Orion Web" + (" (demo data)" if args.demo else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

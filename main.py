"""Orion: watches product pages and sends a Telegram message when a price drops.

    python main.py                      # watch every product in watchlist.txt forever
    python main.py --once               # one round (for cron / systemd timers)
    python main.py --report             # price history summary
    python main.py --check URL          # show what Orion finds on a page, send nothing

watchlist.txt, one product per line:   URL | target price [| CSS selector] [| name]
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

__version__ = "2.1.0"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
REQUEST_TIMEOUT = 20
MAX_PAGE_BYTES = 5 * 1024 * 1024
DEFAULT_PRICE_CLASS = "product-list__price"  # v1 default, still used when nothing else is found
STATE_FILE = "orion_state.json"
HISTORY_FILE = "price_history.csv"


# --- price parsing ---------------------------------------------------------------

_NUMBER = re.compile(r"\d[\d.,\s  ']*")


def parse_price(raw) -> float | None:
    """Parse '35.499,90 TL', '₺1.299', '$1,299.99', '1 299,00 €', '1299' ... into a float.

    The last separator followed by exactly 1-2 digits is the decimal mark; every other
    '.', ',', space or apostrophe is a thousands separator."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw >= 0 else None
    m = _NUMBER.search(str(raw))
    if not m:
        return None
    digits = re.sub(r"[\s  ']", "", m.group(0)).rstrip(".,")
    if not digits:
        return None
    last = max(digits.rfind("."), digits.rfind(","))
    if last != -1 and 1 <= len(digits) - last - 1 <= 2:
        whole, frac = digits[:last], digits[last + 1:]
    else:
        whole, frac = digits, ""
    whole = re.sub(r"[.,]", "", whole)
    try:
        return float(f"{whole}.{frac}" if frac else whole)
    except ValueError:
        return None


# --- price extraction ---------------------------------------------------------------

def _jsonld_prices(soup):
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            stack.extend(v for k, v in item.items() if k in ("@graph", "offers", "itemOffered"))
            types = item.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(t in ("Offer", "AggregateOffer") for t in types):
                for key in ("price", "lowPrice"):
                    price = parse_price(item.get(key))
                    if price:
                        yield price, item.get("priceCurrency")


def extract_price(page, selector: str | None = None):
    """Return (name, price, source) or (None, None, None).

    Order: a configured CSS selector, schema.org JSON-LD, price meta tags, itemprop=price,
    then the v1 default class."""
    soup = BeautifulSoup(page, "html.parser")
    name = None
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        name = og["content"].strip()
    elif soup.title and soup.title.text:
        name = soup.title.text.strip()
    name = (name or "Product")[:60]

    if selector:
        element = soup.select_one(selector) if not re.fullmatch(r"[\w-]+", selector) else soup.find(class_=selector)
        if element is not None:
            price = parse_price(element.get("content") or element.get_text(" "))
            if price:
                return name, price, "selector"
    for price, _currency in _jsonld_prices(soup):
        return name, price, "json-ld"
    for prop in ("product:price:amount", "og:price:amount"):
        meta = soup.find("meta", property=prop)
        if meta and parse_price(meta.get("content")):
            return name, parse_price(meta.get("content")), "meta"
    item = soup.find(attrs={"itemprop": "price"})
    if item is not None:
        price = parse_price(item.get("content") or item.get_text(" "))
        if price:
            return name, price, "itemprop"
    element = soup.find(class_=DEFAULT_PRICE_CLASS)
    if element is not None:
        price = parse_price(element.get_text(" "))
        if price:
            return name, price, "default-class"
    return None, None, None


# --- watchlist, state and history ------------------------------------------------------

@dataclass
class Product:
    url: str
    target: float
    selector: str | None = None
    name: str | None = None


def parse_watchlist(text: str) -> tuple[list[Product], list[str]]:
    products, errors = [], []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        url = parts[0]
        parsed = urlparse(url)
        target = parse_price(parts[1]) if len(parts) > 1 else None
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            errors.append(f"line {number}: not an http(s) URL")
        elif not target:
            errors.append(f"line {number}: missing or invalid target price")
        else:
            products.append(Product(url, target, (parts[2] or None) if len(parts) > 2 else None,
                                    (parts[3] or None) if len(parts) > 3 else None))
    return products, errors


def load_products(path: str, environ=os.environ) -> list[Product]:
    """watchlist.txt, or the v1 single-product environment variables."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            products, errors = parse_watchlist(fh.read())
        if errors:
            raise ValueError(f"{path}: " + "; ".join(errors))
        return products
    if environ.get("ORION_URL") and environ.get("ORION_TARGET_PRICE"):
        target = parse_price(environ["ORION_TARGET_PRICE"])
        if not target:
            raise ValueError("ORION_TARGET_PRICE must be a number")
        return [Product(environ["ORION_URL"], target, environ.get("ORION_PRICE_CLASS"))]
    raise ValueError(f"No products: create {path} (URL | target price) or set ORION_URL and ORION_TARGET_PRICE")


def load_state(path: str = STATE_FILE) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict, path: str = STATE_FILE) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, path)


def append_history(url: str, name: str, price: float, path: str = HISTORY_FILE) -> None:
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(["time", "url", "name", "price"])
        safe_name = "'" + name if name[:1] in ("=", "+", "-", "@") else name  # spreadsheet formulas
        writer.writerow([datetime.now().isoformat(timespec="seconds"), url, safe_name, f"{price:.2f}"])


def decide_alert(previous: dict | None, price: float, target: float) -> str | None:
    """Alert when the price first reaches the target, and again on every new low below it.

    Hourly checks of an unchanged price therefore send one message, not one per hour."""
    if price > target:
        return None
    if not previous or previous.get("alerted_price") is None:
        return "target"
    return "new-low" if price < previous["alerted_price"] else None


# --- network ------------------------------------------------------------------------------

def fetch(url: str, session=requests):
    response = session.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "tr,en;q=0.8"},
                           timeout=REQUEST_TIMEOUT, stream=True)
    try:
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_PAGE_BYTES:
                raise RuntimeError("page larger than 5 MB")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.close()


def send_telegram_message(token: str, chat_id: str, message: str, session=requests) -> bool:
    try:
        response = session.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                data={"chat_id": chat_id, "text": message, "parse_mode": "HTML",
                                      "disable_web_page_preview": "true"},
                                timeout=REQUEST_TIMEOUT)
        return response.ok
    except requests.RequestException as error:  # never print the URL: it contains the token
        print(f"  could not send the Telegram message: {type(error).__name__}")
        return False


def alert_text(kind: str, product: Product, name: str, price: float, previous: dict | None) -> str:
    e = html.escape
    title = "🎯 <b>Target reached</b>" if kind == "target" else "📉 <b>New low price</b>"
    lines = [title, "", f"<b>{e(product.name or name)}</b>", f"Price: <b>{price:,.2f}</b> (target {product.target:,.2f})"]
    if previous and previous.get("price") and previous["price"] != price:
        lines.append(f"Before: {previous['price']:,.2f}")
    lines += ["", e(product.url)]
    return "\n".join(lines)


def check_product(product: Product, state: dict, telegram, session=requests) -> float | None:
    stamp = datetime.now().strftime("%H:%M:%S")
    try:
        page = fetch(product.url, session)
    except (requests.RequestException, RuntimeError) as error:
        print(f"[{stamp}] {product.url[:60]}: {error if isinstance(error, RuntimeError) else type(error).__name__}")
        return None
    name, price, source = extract_price(page, product.selector)
    if price is None:
        print(f"[{stamp}] {product.url[:60]}: no price found (try a CSS selector in watchlist.txt)")
        return None
    label = product.name or name
    previous = state.get(product.url)
    print(f"[{stamp}] {label[:40]}: {price:,.2f} (target {product.target:,.2f}, via {source})")
    append_history(product.url, label, price)
    entry = {"price": price, "checked": datetime.now().isoformat(timespec="seconds"),
             "low": min(price, (previous or {}).get("low", price)),
             "alerted_price": (previous or {}).get("alerted_price")}
    if price > product.target:
        entry["alerted_price"] = None  # back above target: the next drop alerts again
    kind = decide_alert(previous, price, product.target)
    if kind and telegram:
        if telegram(alert_text(kind, product, name, price, previous)):
            entry["alerted_price"] = price
            print(f"  alert sent ({kind})")
    state[product.url] = entry
    return price


def report(path: str = HISTORY_FILE) -> int:
    if not os.path.exists(path):
        print("No price history yet.")
        return 1
    rows: dict[str, list] = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                rows.setdefault(row["url"], []).append((row["time"], row["name"], float(row["price"])))
            except (KeyError, ValueError):
                continue
    print(f"{'PRODUCT':<42}{'LAST':>12}{'LOW':>12}{'HIGH':>12}{'CHECKS':>8}")
    for url, items in rows.items():
        prices = [p for _, _, p in items]
        print(f"{items[-1][1][:40]:<42}{prices[-1]:>12,.2f}{min(prices):>12,.2f}{max(prices):>12,.2f}{len(prices):>8}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="orion", description="Price drop alerts on Telegram.")
    p.add_argument("--watchlist", default="watchlist.txt")
    p.add_argument("--once", action="store_true", help="check every product once and exit")
    p.add_argument("--report", action="store_true", help="summarise price_history.csv and exit")
    p.add_argument("--check", metavar="URL", help="show the price found on a page; sends nothing")
    p.add_argument("--selector", help="CSS selector or class to use with --check")
    p.add_argument("--interval", type=float, default=float(os.environ.get("ORION_INTERVAL_MINUTES", "60")),
                   help="minutes between rounds (default 60)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    if args.report:
        return report()
    if args.check:
        try:
            name, price, source = extract_price(fetch(args.check), args.selector)
        except (requests.RequestException, RuntimeError) as error:
            print(f"Request failed: {error}")
            return 1
        print(f"{name}: {price} (via {source})" if price else "No price found.")
        return 0 if price else 1
    if args.interval < 5:
        print("--interval must be at least 5 minutes (be kind to the shops)")
        return 2
    try:
        products = load_products(args.watchlist)
    except ValueError as error:
        print(error)
        return 2
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    telegram = (lambda msg: send_telegram_message(token, chat, msg)) if token and chat else None
    if telegram is None:
        print("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID not set: prices are logged, no messages are sent.")

    print(f"Orion {__version__}: {len(products)} product(s), every {args.interval:g} min")
    state = load_state()
    try:
        while True:
            for product in products:
                check_product(product, state, telegram)
            save_state(state)
            if args.once:
                return 0
            time.sleep(args.interval * 60)
    except KeyboardInterrupt:
        save_state(state)
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

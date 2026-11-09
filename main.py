"""Orion: watches a product page and sends a Telegram message when the price drops."""

import os
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

DEFAULT_PRICE_CLASS = "product-list__price"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20


def parse_price(raw):
    """Turn a Turkish-formatted price such as '35.499,90 TL' into 35499.9. Returns None if unparsable."""
    cleaned = raw.replace("TL", "").replace("₺", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_price(html, css_class=DEFAULT_PRICE_CLASS):
    """Return (product_name, price) from a product page, or (None, None) if the price is missing."""
    soup = BeautifulSoup(html, "html.parser")
    element = soup.find(class_=css_class)
    if element is None:
        return None, None
    price = parse_price(element.text)
    if price is None:
        return None, None
    name = soup.title.text.strip()[:40] if soup.title and soup.title.text else "Product"
    return name, price


def load_settings(environ=os.environ):
    """Read settings from environment variables. Raises ValueError listing what is missing."""
    missing = [k for k in ("ORION_URL", "ORION_TARGET_PRICE", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID") if not environ.get(k)]
    if missing:
        raise ValueError("Missing environment variables: " + ", ".join(missing))
    try:
        target = float(environ["ORION_TARGET_PRICE"])
        interval = float(environ.get("ORION_INTERVAL_MINUTES", "60"))
    except ValueError:
        raise ValueError("ORION_TARGET_PRICE and ORION_INTERVAL_MINUTES must be numbers")
    if interval <= 0:
        raise ValueError("ORION_INTERVAL_MINUTES must be greater than 0")
    return {
        "url": environ["ORION_URL"],
        "target": target,
        "interval": interval,
        "token": environ["TELEGRAM_TOKEN"],
        "chat_id": environ["TELEGRAM_CHAT_ID"],
        "css_class": environ.get("ORION_PRICE_CLASS", DEFAULT_PRICE_CLASS),
    }


def send_telegram_message(token, chat_id, message):
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message},
            timeout=REQUEST_TIMEOUT,
        )
        return response.ok
    except requests.RequestException as error:
        print(f"Could not send the message: {type(error).__name__}")
        return False


def check_price(settings):
    """One check. Returns the price found (or None)."""
    stamp = datetime.now().strftime("%H:%M:%S")
    try:
        response = requests.get(settings["url"], headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as error:
        print(f"[{stamp}] Request failed: {type(error).__name__}")
        return None
    if response.status_code != 200:
        print(f"[{stamp}] Connection problem: HTTP {response.status_code}")
        return None
    name, price = extract_price(response.content, settings["css_class"])
    if price is None:
        print(f"[{stamp}] Price element '{settings['css_class']}' not found.")
        return None
    print(f"[{stamp}] Checked: {price} TL")
    if price <= settings["target"]:
        message = (
            f"Price alert!\n\nProduct: {name}\nPrice: {price} TL\n"
            f"Your target: {settings['target']} TL\n\n{settings['url']}"
        )
        if send_telegram_message(settings["token"], settings["chat_id"], message):
            print("Price is at or below target. Message sent.")
        else:
            print("Price is at or below target, but the message could not be sent.")
    else:
        print(f"Still above the target of {settings['target']} TL.")
    return price


def main():
    try:
        settings = load_settings()
    except ValueError as error:
        print(error)
        return 2
    print(f"Orion started. Checking every {settings['interval']:g} minutes.")
    send_telegram_message(settings["token"], settings["chat_id"], "Orion is active. Price tracking has started.")
    while True:
        check_price(settings)
        time.sleep(settings["interval"] * 60)


if __name__ == "__main__":
    sys.exit(main())

# 👁️ FA Software - Project Orion

> **"Perception is the beginning of control."**

This project is the inaugural automation initiative of the **FA Software** ecosystem. Architected by **Anıl**, it is designed to monitor e-commerce data streams with aesthetic precision and automate strategic purchasing decisions.

![Architect](https://img.shields.io/badge/Lead%20Architect-Anıl-blueviolet)
![Brand](https://img.shields.io/badge/Powered%20By-FA%20Software-black)
![Core](https://img.shields.io/badge/Python-3.12-white)

## 🌌 Vision & Project

**Orion** is a universal digital observer designed for the modern web. Architected by **Anıl**, this system abstracts the complexity of data tracking, allowing any user to monitor any product across various e-commerce platforms with precision.

It is not limited to a specific item or store. Whether for high-end electronics, market assets, or daily essentials, **FA Software** adapts to the user's need. Once a target URL and a strategic price point are defined, the sentinel silently patrols the web 24/7. Upon detecting the desired value, it transmits an instant, encrypted intelligence signal to the user via Telegram, ensuring that no opportunity is missed.
## 🛠️ Architecture

Crafted with the perfectionist approach of **FA Software**, this tool is optimized for native performance on Arch Linux.

* **Engine:** Python 3.x
* **Observation (Scraping):** `BeautifulSoup4` & `Requests`
* **Communication:** Telegram Bot API
* **Cycle:** Custom Daemon Loop

## 🚀 Setup & Usage

```bash
pip install -r requirements.txt
```

Orion is configured with environment variables, so no token is ever written into the code (see `.env.example`):

| Variable | Meaning |
|---|---|
| `ORION_URL` | Product page to watch |
| `ORION_TARGET_PRICE` | Alert when the price is at or below this (TL) |
| `ORION_INTERVAL_MINUTES` | Minutes between checks (default 60) |
| `ORION_PRICE_CLASS` | CSS class of the price element (default `product-list__price`) |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram bot token and the chat to notify |

```bash
export ORION_URL=... ORION_TARGET_PRICE=35000 TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=...
python main.py
```

Prices are expected in the Turkish format (`35.499,90 TL`). Every site names its price element differently, so for a new store set `ORION_PRICE_CLASS`; sites that render prices with JavaScript cannot be read with this approach.

## ✅ Tests

```bash
python -m unittest discover -v
```

The tests cover price parsing, settings validation and the alert logic with the network mocked.

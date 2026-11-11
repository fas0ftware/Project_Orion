# 👁️ Project Orion

> *"Perception is the beginning of control."*

[![CI](https://github.com/fas0ftware/Project_Orion/actions/workflows/ci.yml/badge.svg)](https://github.com/fas0ftware/Project_Orion/actions/workflows/ci.yml)
![Version](https://img.shields.io/badge/version-2.0.0-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-yellow)
![License](https://img.shields.io/badge/license-MIT-green)

Orion watches product pages and sends you a **Telegram message when a price drops** to your target. The first automation project of **FA Software**.

![Live check, one round and the report](docs/demo.svg)

<sub>Demo against books.toscrape.com, a site built for scraping practice.</sub>

## Features

- **Many products** in `watchlist.txt`, each with its own target price, optional CSS selector and display name.
- **Works on most shops without configuration:** finds the price in schema.org **JSON-LD**, then `product:price:amount` / `og:price:amount` meta tags, then `itemprop="price"`, then your CSS selector or class.
- **Any price format:** `35.499,90 TL`, `₺1.299`, `$1,299.99`, `1 299,00 €`, `CHF 1'299.50`.
- **No spam:** one message when the price first reaches the target, another only for a **new low**; a price that goes back above the target re-arms the alert. State survives restarts (`orion_state.json`).
- **Price history** in `price_history.csv` and a `--report` with last / low / high per product.
- `--once` for cron or systemd timers, `--check URL` to test a page before adding it.
- Safe by default: 20 s timeouts, 5 MB page limit, HTML-escaped messages, the bot token never appears in logs, CSV cells cannot become spreadsheet formulas, at least 5 minutes between rounds.

## Setup

```bash
pip install -r requirements.txt
cp watchlist.example.txt watchlist.txt     # URL | target | CSS selector (optional) | name (optional)
export TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=...   # from @BotFather and getUpdates; optional
```

Without the Telegram variables Orion still checks and logs prices.

## Usage

```bash
python main.py --check "https://shop.example/product/123"     # what does Orion see on this page?
python main.py --once                                         # one round (cron: */60 * * * *)
python main.py --interval 30                                  # run forever, every 30 minutes
python main.py --report
```

The v1 single-product variables (`ORION_URL`, `ORION_TARGET_PRICE`, `ORION_PRICE_CLASS`) still work when no `watchlist.txt` exists. Pages that only render their price with JavaScript cannot be read this way.

## Tests

14 tests, network mocked: price formats, all four extraction strategies, broken JSON-LD, watchlist validation, alert de-duplication across price changes, history and state files, formula-injection guard, oversized pages and network errors, token-safe error messages, the CLI.

```bash
pip install -r requirements-dev.txt
python -m pytest -v
```

![Test results](docs/test-results.svg)

![Security scan](docs/security-scan.svg)

## Notes

Check a shop's terms of use before monitoring it, keep the interval reasonable, and never use automated purchases or high-frequency polling.

## Changelog

- **2.0.0** – Watchlist with many products, JSON-LD/meta/itemprop/CSS price detection, international price formats, alert only on target or new low, persistent state, price history and report, `--once`/`--check`/`--report`, page size limit, HTML-escaped messages, pytest suite, CI with bandit + pip-audit.
- **1.0.0** – One product, one CSS class, Telegram alert on every check below target.

---

Part of the **FA Software** projects. Licensed under the [MIT License](LICENSE).

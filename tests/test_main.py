import json
import os
import tempfile
import unittest
from unittest import mock

import requests

import main


class Resp:
    def __init__(self, status=200, body=b"", ok=True):
        self.status_code, self.body, self.ok = status, body, ok

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]

    def close(self):
        pass


class Session:
    def __init__(self, pages):
        self.pages, self.posts = pages, []

    def get(self, url, **kw):
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page if isinstance(page, Resp) else Resp(body=page.encode())

    def post(self, url, data=None, **kw):
        self.posts.append((url, data))
        return Resp()


JSONLD = '''<html><head><title>Phone X | Shop</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Product","name":"Phone X",
"offers":{"@type":"Offer","price":"34999.90","priceCurrency":"TRY"}}]}</script></head><body></body></html>'''
META = '<html><head><meta property="og:title" content="Laptop"><meta property="product:price:amount" content="1299.5"></head></html>'
ITEMPROP = '<html><body><span itemprop="price" content="45.00">45,00 TL</span></body></html>'
V1 = '<html><title>Old shop</title><div class="product-list__price">35.499,90 TL</div></html>'
CUSTOM = '<html><title>T</title><div id="p"><b class="now">₺2.150,00</b></div></html>'


class ParsePriceTests(unittest.TestCase):
    def test_formats(self):
        cases = {"35.499,90 TL": 35499.9, "₺1.299": 1299, "$1,299.99": 1299.99, "1 299,00 €": 1299.0,
                 "1299": 1299, "12,5": 12.5, "1.234.567,89": 1234567.89, "1,234,567.89": 1234567.89,
                 "CHF 1'299.50": 1299.5, "45": 45, 34999.9: 34999.9, "Fiyat: 750 TL": 750}
        for raw, expected in cases.items():
            self.assertAlmostEqual(main.parse_price(raw), expected, msg=raw)

    def test_garbage(self):
        for raw in (None, "", "TL", "free", -5):
            self.assertIsNone(main.parse_price(raw), raw)


class ExtractTests(unittest.TestCase):
    def test_strategies(self):
        self.assertEqual(main.extract_price(JSONLD), ("Phone X | Shop", 34999.9, "json-ld"))
        self.assertEqual(main.extract_price(META), ("Laptop", 1299.5, "meta"))
        self.assertEqual(main.extract_price(ITEMPROP)[1:], (45.0, "itemprop"))
        self.assertEqual(main.extract_price(V1)[1:], (35499.9, "default-class"))
        self.assertEqual(main.extract_price(CUSTOM, "#p .now")[1:], (2150.0, "selector"))
        self.assertEqual(main.extract_price(CUSTOM, "now")[1:], (2150.0, "selector"))  # bare class name
        self.assertEqual(main.extract_price("<html></html>"), (None, None, None))

    def test_broken_jsonld_is_skipped(self):
        page = '<script type="application/ld+json">{oops</script>' + META
        self.assertEqual(main.extract_price(page)[1], 1299.5)


class WatchlistTests(unittest.TestCase):
    def test_parse(self):
        products, errors = main.parse_watchlist(
            "# comment\nhttps://a.example/p | 35.000 TL\nhttps://b.example/x | 99,90 | .price | My item\n"
            "ftp://x | 5\nhttps://c.example | abc\n\n")
        self.assertEqual([(p.url, p.target, p.selector, p.name) for p in products],
                         [("https://a.example/p", 35000.0, None, None),
                          ("https://b.example/x", 99.9, ".price", "My item")])
        self.assertEqual(len(errors), 2)

    def test_v1_environment_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"ORION_URL": "https://a.example", "ORION_TARGET_PRICE": "100"}
            self.assertEqual(main.load_products(os.path.join(tmp, "none.txt"), env)[0].target, 100)
            with self.assertRaises(ValueError):
                main.load_products(os.path.join(tmp, "none.txt"), {})


class AlertTests(unittest.TestCase):
    def test_decide_alert(self):
        self.assertIsNone(main.decide_alert(None, 120, 100))
        self.assertEqual(main.decide_alert(None, 95, 100), "target")
        self.assertIsNone(main.decide_alert({"alerted_price": 95}, 95, 100))  # no hourly spam
        self.assertEqual(main.decide_alert({"alerted_price": 95}, 90, 100), "new-low")
        self.assertEqual(main.decide_alert({"alerted_price": None}, 99, 100), "target")

    def test_message_escapes_html(self):
        product = main.Product("https://a.example/?q=<x>&y=1", 100, name="<b>Evil</b>")
        text = main.alert_text("target", product, "n", 95.5, {"price": 120})
        self.assertIn("&lt;b&gt;Evil&lt;/b&gt;", text)
        self.assertIn("&amp;y=1", text)
        self.assertIn("Before: 120.00", text)


class CheckProductTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, old)
        self.sent = []

    def telegram(self, msg):
        self.sent.append(msg)
        return True

    def test_one_alert_until_the_price_moves(self):
        product = main.Product("https://shop.example/p", 36000)
        state = {}
        session = Session({product.url: V1})
        for _ in range(3):
            main.check_product(product, state, self.telegram, session)
        self.assertEqual(len(self.sent), 1)
        session.pages[product.url] = V1.replace("35.499,90", "34.000,00")
        main.check_product(product, state, self.telegram, session)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("New low price", self.sent[-1])
        session.pages[product.url] = V1.replace("35.499,90", "40.000,00")  # back above target
        main.check_product(product, state, self.telegram, session)
        session.pages[product.url] = V1.replace("35.499,90", "34.500,00")
        main.check_product(product, state, self.telegram, session)
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(state[product.url]["low"], 34000.0)

    def test_history_and_state_files(self):
        product = main.Product("https://shop.example/p", 1, name="=cmd|' /C calc'!A0")
        main.check_product(product, {}, None, Session({product.url: META}))
        with open(main.HISTORY_FILE) as fh:
            content = fh.read()
        self.assertIn("time,url,name,price", content)
        self.assertIn("'=cmd", content)  # spreadsheet formula neutralised
        main.save_state({"a": 1})
        self.assertEqual(main.load_state(), {"a": 1})
        self.assertEqual(main.report(), 0)

    def test_errors_do_not_raise(self):
        product = main.Product("https://shop.example/p", 1)
        for page in (requests.ConnectionError("down"), Resp(status=503), Resp(body=b"x" * (6 * 1024 * 1024)),
                     "<html>no price</html>"):
            self.assertIsNone(main.check_product(product, {}, self.telegram, Session({product.url: page})))
        self.assertEqual(self.sent, [])

    def test_telegram_failure_does_not_mark_as_alerted(self):
        product = main.Product("https://shop.example/p", 999999)
        state = {}
        main.check_product(product, state, lambda m: False, Session({product.url: V1}))
        self.assertIsNone(state[product.url]["alerted_price"])


class TelegramTests(unittest.TestCase):
    def test_token_never_printed_on_error(self):
        session = mock.Mock()
        session.post.side_effect = requests.ConnectionError("https://api.telegram.org/botSECRET/sendMessage")
        with mock.patch("builtins.print") as printed:
            self.assertFalse(main.send_telegram_message("SECRET", "1", "hi", session))
        self.assertNotIn("SECRET", str(printed.call_args_list))


class CliTests(unittest.TestCase):
    def test_validation_and_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main.main(["--watchlist", os.path.join(tmp, "none.txt"), "--once"]), 2)
            self.assertEqual(main.main(["--interval", "1"]), 2)
        with mock.patch.object(main, "fetch", return_value=JSONLD.encode()):
            self.assertEqual(main.main(["--check", "https://x.example"]), 0)


if __name__ == "__main__":
    unittest.main()

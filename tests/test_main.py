import unittest
from unittest import mock

import main


class ParsePriceTests(unittest.TestCase):
    def test_turkish_format(self):
        self.assertEqual(main.parse_price("35.499,90 TL"), 35499.9)
        self.assertEqual(main.parse_price(" 1.250 TL "), 1250.0)
        self.assertEqual(main.parse_price("₺999,50"), 999.5)

    def test_garbage_returns_none(self):
        self.assertIsNone(main.parse_price("out of stock"))


class ExtractPriceTests(unittest.TestCase):
    HTML = '<html><title>Phone X</title><body><span class="product-list__price">12.000,00 TL</span></body></html>'

    def test_finds_price_and_name(self):
        self.assertEqual(main.extract_price(self.HTML), ("Phone X", 12000.0))

    def test_custom_class(self):
        html = '<title>T</title><b class="p">5,5 TL</b>'
        self.assertEqual(main.extract_price(html, "p"), ("T", 5.5))

    def test_missing_element(self):
        self.assertEqual(main.extract_price("<html></html>"), (None, None))


class SettingsTests(unittest.TestCase):
    ENV = {"ORION_URL": "https://x.test", "ORION_TARGET_PRICE": "100", "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}

    def test_defaults(self):
        s = main.load_settings(self.ENV)
        self.assertEqual((s["target"], s["interval"], s["css_class"]), (100.0, 60.0, main.DEFAULT_PRICE_CLASS))

    def test_missing_variables_are_listed(self):
        with self.assertRaises(ValueError) as ctx:
            main.load_settings({})
        self.assertIn("TELEGRAM_TOKEN", str(ctx.exception))

    def test_bad_numbers(self):
        with self.assertRaises(ValueError):
            main.load_settings({**self.ENV, "ORION_TARGET_PRICE": "cheap"})
        with self.assertRaises(ValueError):
            main.load_settings({**self.ENV, "ORION_INTERVAL_MINUTES": "0"})


class CheckPriceTests(unittest.TestCase):
    SETTINGS = {"url": "https://x.test", "target": 100.0, "interval": 1, "token": "t", "chat_id": "1", "css_class": "p"}

    def response(self, html, status=200):
        return mock.Mock(status_code=status, content=html.encode())

    def test_alert_sent_when_price_is_low(self):
        with mock.patch.object(main.requests, "get", return_value=self.response('<b class="p">90 TL</b>')), \
             mock.patch.object(main, "send_telegram_message", return_value=True) as send:
            self.assertEqual(main.check_price(self.SETTINGS), 90.0)
        send.assert_called_once()

    def test_no_alert_when_price_is_high(self):
        with mock.patch.object(main.requests, "get", return_value=self.response('<b class="p">500 TL</b>')), \
             mock.patch.object(main, "send_telegram_message") as send:
            self.assertEqual(main.check_price(self.SETTINGS), 500.0)
        send.assert_not_called()

    def test_http_error_and_network_error(self):
        with mock.patch.object(main.requests, "get", return_value=self.response("", 503)):
            self.assertIsNone(main.check_price(self.SETTINGS))
        with mock.patch.object(main.requests, "get", side_effect=main.requests.ConnectionError()):
            self.assertIsNone(main.check_price(self.SETTINGS))


if __name__ == "__main__":
    unittest.main()

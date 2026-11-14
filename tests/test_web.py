"""Orion Web: watchlist editing, demo data, checks with a fake shop, and the HTTP guards."""
import http.client
import json
import socket
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import web
from web_base import HttpError

PAGE = b'<html><h1>Lamp</h1><script type="application/ld+json">{"@type":"Product","name":"Lamp",' \
       b'"offers":{"@type":"Offer","price":"42.50"}}</script></html>'


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.core = web.Orion(self.dir)

    def test_add_list_remove(self):
        self.core.add("https://shop.example/lamp", 40.0, "", "Lamp")
        self.core.add("https://shop.example/desk", 199.5, ".price", "")
        listing = self.core.listing()
        self.assertEqual([p["url"] for p in listing["products"]], ["https://shop.example/lamp", "https://shop.example/desk"])
        self.assertEqual(listing["products"][1]["selector"], ".price")
        self.assertEqual(listing["products"][0]["status"], "unchecked")
        with self.assertRaises(HttpError):
            self.core.add("https://shop.example/lamp", 30.0, "", "")  # already there
        self.core.remove("https://shop.example/lamp")
        self.assertEqual(len(self.core.listing()["products"]), 1)
        self.assertIn("# URL | target price", (self.dir / "watchlist.txt").read_text())

    def test_hostile_fields_cannot_break_the_watchlist_format(self):
        for url, selector, name in (("https://a.example/x | 1", "", ""), ("https://a.example/x", ".p\n.q", ""),
                                    ("https://a.example/x", "", "a|b"), ("ftp://a.example/x", "", ""),
                                    ("javascript:alert(1)", "", "")):
            with self.subTest(url=url), self.assertRaises(HttpError):
                self.core.add(url, 10.0, selector, name)
        self.assertFalse((self.dir / "watchlist.txt").exists())

    def test_check_with_a_fake_shop_writes_state_and_history(self):
        self.core.add("https://shop.example/lamp", 45.0, "", "")
        with mock.patch.object(web.orion, "fetch", return_value=PAGE):
            self.assertEqual(self.core.check(), [])
        product = self.core.listing()["products"][0]
        self.assertEqual((product["price"], product["status"], product["history"]), (42.5, "below", [42.5]))
        self.assertTrue((self.dir / "price_history.csv").exists())

    def test_preview(self):
        with mock.patch.object(web.orion, "fetch", return_value=PAGE):
            self.assertEqual(self.core.preview("https://shop.example/lamp", "")["price"], 42.5)
        with self.assertRaises(HttpError):
            self.core.preview("file:///etc/passwd", "")

    def test_demo_is_fictional_and_never_fetches(self):
        web.seed_demo(self.dir)
        demo = web.Orion(self.dir, demo=True)
        listing = demo.listing()
        self.assertEqual(len(listing["products"]), 5)
        self.assertTrue(all(p["url"].startswith("https://shop.example/") for p in listing["products"]))
        self.assertEqual({p["status"] for p in listing["products"]}, {"below", "above"})
        with mock.patch.object(web.orion, "fetch") as fetch:
            for call in (demo.check, lambda: demo.preview("https://shop.example/x", "")):
                with self.assertRaises(HttpError):
                    call()
            fetch.assert_not_called()


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()
        cls.dir = Path(tempfile.mkdtemp())
        app = web.build_app(web.Orion(cls.dir))
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), app.handler(cls.port))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, method, path, body=None, **headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": f"127.0.0.1:{self.port}"}
        if body is not None:
            h |= {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.port}"}
        h |= {k.replace("_", "-"): v for k, v in headers.items()}
        conn.request(method, path, json.dumps(body) if body is not None else None, h)
        r = conn.getresponse()
        return r.status, r, r.read()

    def test_page_and_headers(self):
        status, r, data = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Orion", data)
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))

    def test_guards(self):
        self.assertEqual(self.call("GET", "/api/products", Host="evil.example")[0], 403)
        self.assertEqual(self.call("POST", "/api/products", {"url": "https://a.example/x", "target": 5},
                                   Origin="http://evil.example")[0], 403)
        self.assertEqual(self.call("POST", "/api/products", {"x": 1}, Content_Type="text/plain")[0], 415)
        self.assertEqual(self.call("GET", "/static/../web.py")[0], 404)
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)

    def test_add_through_http_and_type_checks(self):
        status, _, data = self.call("POST", "/api/products", {"url": "https://a.example/x", "target": 5})
        self.assertEqual(status, 200, data)
        self.assertEqual(json.loads(data)["products"][0]["target"], 5)
        self.assertEqual(self.call("POST", "/api/products", {"url": "https://a.example/y", "target": "5"})[0], 400)
        self.assertEqual(self.call("POST", "/api/products", {"url": "https://a.example/y", "target": -1})[0], 400)
        self.assertEqual(self.call("POST", "/api/products", ["not", "an", "object"])[0], 400)


if __name__ == "__main__":
    unittest.main()

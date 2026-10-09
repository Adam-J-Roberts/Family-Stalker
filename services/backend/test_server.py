import contextlib
import http.client
import io
import json
import threading
import unittest
from http.server import HTTPServer

from server import Handler


class HealthServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=5)

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        try:
            connection.request(method, path, body=body)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_health_is_explicitly_scaffold(self):
        status, headers, body = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ok", "stage": "scaffold"})
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_unknown_routes_do_not_expose_data(self):
        for path in ("/", "/locations", "/healthz?secret=test"):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, 404)
                self.assertEqual(json.loads(body), {"error": "not_found"})

    def test_writes_are_not_accepted(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                status, _, body = self.request(method, "/locations", "synthetic")
                self.assertEqual(status, 405)
                self.assertEqual(json.loads(body), {"error": "not_implemented"})

    def test_head_has_no_body(self):
        for path, expected in (("/healthz", 200), ("/locations", 404)):
            with self.subTest(path=path):
                status, headers, body = self.request("HEAD", path)
                self.assertEqual(status, expected)
                self.assertGreater(int(headers["Content-Length"]), 0)
                self.assertEqual(body, b"")

    def test_request_details_are_not_logged(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.request("GET", "/unknown?private=synthetic-secret")
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()

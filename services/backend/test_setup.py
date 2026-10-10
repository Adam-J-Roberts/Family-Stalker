import json
import os
import re
import smtplib
import ssl
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app import Account, Base, Challenge, Device, HASHER, LoginSession, Outbox, Settings, create_app, digest

PASSWORD = "synthetic long test password"
PUBLIC = "https://stalker.example.invalid"
OWNER = "owner@example.invalid"
MAIL = {"host": "smtp.example.invalid", "port": 587, "mode": "starttls", "username": "synthetic", "password": "smtp-test-secret", "sender": OWNER}


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.db_url = os.environ.get("STALKER_TEST_DATABASE_URL", f"sqlite:///{self.path}/test.db")
        if os.environ.get("STALKER_TEST_DATABASE_URL"):
            # Explicit disposable test DB only; never reads DATABASE_URL.
            engine = create_engine(self.db_url)
            Base.metadata.drop_all(engine)
            engine.dispose()
        self.messages = []
        self.app = create_app(self.db_url, self.path, PUBLIC, mailer=lambda *args: self.messages.append(args), mail_worker=False)
        self.client = TestClient(self.app, base_url=PUBLIC)
        self.client.__enter__()
        self.client.headers["Origin"] = PUBLIC
        self.token = (self.path / "bootstrap-token").read_text()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def setup_owner(self):
        return self.client.post("/api/setup", json={"token": self.token, "household": "Test household", "email": OWNER, "username": "owner", "password": PASSWORD})

    def login(self, email=OWNER, password=PASSWORD):
        result = self.client.post("/api/login", json={"email": email, "password": password})
        if result.status_code == 200:
            self.client.headers["X-CSRF-Token"] = result.json()["csrf"]
        return result

    def configure(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.put("/api/mail", json=MAIL).status_code, 200)

    def invitation(self):
        self.configure()
        self.assertEqual(self.client.post("/api/invitations", json={"email": "member@example.invalid"}).status_code, 201)
        return re.search(r"#verify=(\S+)", self.messages[-1][3]).group(1)

    def activate(self, token):
        return self.client.post("/api/enrollment/verify", json={"token": token, "username": "member", "password": PASSWORD})

    def test_bootstrap_locks_and_hashes_password(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        self.assertFalse((self.path / "bootstrap-token").exists())
        self.assertEqual(self.setup_owner().status_code, 409)
        with Session(self.app.state.engine) as db:
            account = db.scalar(select(Account))
            self.assertNotEqual(account.password, PASSWORD)
            self.assertTrue(HASHER.verify(account.password, PASSWORD))
            self.assertIsNone(db.get(Settings, 1).bootstrap_hash)

    def test_configured_token_replaces_unclaimed_token_and_cannot_reopen_setup(self):
        with patch.dict(os.environ, {"STALKER_SETUP_TOKEN": "family-test"}):
            self.app.state.initialize()
            self.assertEqual((self.path / "bootstrap-token").read_text(), "family-test")
            self.assertEqual((self.path / "bootstrap-token").stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.setup_owner().status_code, 403)
            self.token = "family-test"
            self.assertEqual(self.setup_owner().status_code, 201)
            self.app.state.initialize()
            self.assertFalse((self.path / "bootstrap-token").exists())
            self.assertEqual(self.setup_owner().status_code, 409)

    def test_configured_token_on_fresh_install(self):
        with tempfile.TemporaryDirectory() as directory:
            database_url = "sqlite:///" + directory + "/fresh.db"
            with patch.dict(os.environ, {"STALKER_SETUP_TOKEN": "fresh-test-token"}):
                app = create_app(database_url, directory, PUBLIC, mail_worker=False)
                with TestClient(app, base_url=PUBLIC) as client:
                    result = client.post("/api/setup", headers={"Origin": PUBLIC}, json={"token": "fresh-test-token", "household": "Fresh", "email": OWNER, "username": "owner", "password": PASSWORD})
                    self.assertEqual(result.status_code, 201)

    def test_invalid_configured_token_does_not_replace_existing_token(self):
        with patch.dict(os.environ, {"STALKER_SETUP_TOKEN": "short"}):
            with self.assertRaises(ValueError):
                self.app.state.initialize()
        self.assertEqual((self.path / "bootstrap-token").read_text(), self.token)
        self.assertEqual(self.setup_owner().status_code, 201)

    def test_wrong_token_origin_host_and_weak_password(self):
        self.token = "wrong" * 8
        self.assertEqual(self.setup_owner().status_code, 403)
        self.client.headers["Origin"] = "https://attacker.invalid"
        self.assertEqual(self.setup_owner().status_code, 403)
        self.assertEqual(self.client.get("/api/setup", headers={"host": "attacker.invalid"}).status_code, 400)
        self.client.headers["Origin"] = PUBLIC
        result = self.client.post("/api/setup", json={"token": self.token, "household": "test", "email": OWNER, "username": "test", "password": "short-secret"})
        self.assertEqual(result.status_code, 422)
        self.assertNotIn("short-secret", result.text)
        self.assertIn({"field": "password", "message": "Use at least 15 characters."}, result.json()["fields"])

    def test_persistence_and_key_loss_fail_closed(self):
        self.configure()
        self.app.state.initialize()
        again = create_app(self.db_url, self.path, PUBLIC, mail_worker=False)
        with TestClient(again, base_url=PUBLIC) as client:
            self.assertTrue(client.get("/healthz").json()["configured"])
        (self.path / "server.key").unlink()
        with self.assertRaisesRegex(RuntimeError, "key is missing"):
            create_app(self.db_url, self.path, PUBLIC, mail_worker=False)

    def test_http_requires_explicit_opt_in(self):
        with self.assertRaises(ValueError):
            create_app(self.db_url, self.path, "http://localhost:8080", allow_http=False)

    def test_unknown_schema_refused(self):
        with Session(self.app.state.engine) as db:
            db.get(Settings, 1).version = 999
            db.commit()
        with self.assertRaisesRegex(RuntimeError, "Unsupported database version"):
            self.app.state.initialize()

    def test_login_cookie_session_csrf_expiry_and_logout(self):
        self.setup_owner()
        response = self.login()
        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=strict"):
            self.assertIn(flag, cookie)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(LoginSession, self.client.cookies.get("stalker_session")))
        self.assertEqual(self.client.get("/api/admin").status_code, 200)
        csrf = self.client.headers.pop("X-CSRF-Token")
        self.assertEqual(self.client.post("/api/logout", json={}).status_code, 403)
        self.client.headers["X-CSRF-Token"] = csrf
        self.assertEqual(self.client.post("/api/logout", json={}).status_code, 200)
        self.assertEqual(self.client.get("/api/session").status_code, 401)
        self.login()
        with Session(self.app.state.engine) as db:
            db.scalar(select(LoginSession)).expires = time.time() - 1
            db.commit()
        self.assertEqual(self.client.get("/api/session").status_code, 401)

    def test_brute_force_throttled_without_enumeration(self):
        self.setup_owner()
        known = self.login(password="incorrect").json()
        unknown = self.login(email="unknown@example.invalid").json()
        self.assertEqual(known, unknown)
        for _ in range(8):
            self.assertEqual(self.login(password="incorrect").status_code, 401)
        self.assertEqual(self.login(password="incorrect").status_code, 429)

    def test_anonymous_cannot_manage_accounts_mail_or_devices(self):
        self.setup_owner()
        for path in ("/api/admin", "/api/accounts", "/api/mail", "/api/devices"):
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_smtp_secret_encrypted_and_never_returned(self):
        self.configure()
        result = self.client.get("/api/mail")
        self.assertNotIn("password", result.json())
        with Session(self.app.state.engine) as db:
            stored = db.get(Settings, 1).smtp
            self.assertNotIn(MAIL["password"], stored)
            self.assertEqual(json.loads(self.app.state.cipher.decrypt(stored.encode()))["password"], MAIL["password"])
        changed = {**MAIL, "password": None}
        self.client.put("/api/mail", json=changed)
        self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 200)
        self.assertEqual(self.messages[-1][0]["password"], MAIL["password"])

    def test_smtp_must_use_tls_and_header_injection_rejected(self):
        self.configure()
        self.assertEqual(self.client.put("/api/mail", json={**MAIL, "mode": "plain"}).status_code, 422)
        self.assertEqual(self.client.put("/api/mail", json={**MAIL, "sender": "a@example.invalid\r\nBcc:evil@example.invalid"}).status_code, 422)

    def test_smtp_verifies_certificates_and_authenticates_after_starttls(self):
        self.configure()
        real = create_app(self.db_url, self.path, PUBLIC, mail_worker=False)
        with TestClient(real, base_url=PUBLIC) as client:
            client.headers.update(dict(self.client.headers))
            client.cookies.update(self.client.cookies)
            for mode in ("starttls", "tls"):
                client.put("/api/mail", json={**MAIL, "mode": mode})
                with patch("app.smtplib.SMTP") as plain, patch("app.smtplib.SMTP_SSL") as secure:
                    self.assertEqual(client.post("/api/mail/test", json={}).status_code, 200)
                    factory = plain if mode == "starttls" else secure
                    connection = factory.return_value
                    context = (connection.starttls.call_args.kwargs["context"] if mode == "starttls" else factory.call_args.kwargs["context"])
                    self.assertTrue(context.check_hostname)
                    self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                    connection.login.assert_called_once_with(MAIL["username"], MAIL["password"])
                    connection.send_message.assert_called_once()
                    if mode == "starttls":
                        calls = [call[0] for call in connection.method_calls]
                        self.assertLess(calls.index("starttls"), calls.index("login"))
                        secure.assert_not_called()
                    else:
                        plain.assert_not_called()

    def test_wrong_server_key_refuses_startup(self):
        self.configure()
        from cryptography.fernet import Fernet
        (self.path / "server.key").write_bytes(Fernet.generate_key())
        wrong = create_app(self.db_url, self.path, PUBLIC, mail_worker=False)
        with self.assertRaisesRegex(RuntimeError, "key does not match"):
            wrong.state.initialize()
        wrong.state.engine.dispose()

    def test_invite_verify_single_use_and_member_cannot_admin(self):
        token = self.invitation()
        result = self.activate(token)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["device_approval_required"])
        self.assertEqual(self.activate(token).status_code, 400)
        self.client.post("/api/logout", json={})
        self.assertEqual(self.login(email="member@example.invalid").status_code, 200)
        self.assertEqual(self.client.get("/api/admin").status_code, 403)
        self.assertEqual(self.client.put("/api/mail", json=MAIL).status_code, 403)

    def test_uninvited_resend_generic_and_no_account_creation(self):
        self.configure()
        self.client.post("/api/invitations", json={"email": "member@example.invalid"})
        known = self.client.post("/api/enrollment/request", json={"email": "member@example.invalid"})
        unknown = self.client.post("/api/enrollment/request", json={"email": "unknown@example.invalid"})
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(unknown.status_code, 202)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.scalar(select(Account).where(Account.email == "unknown@example.invalid")))

    def test_resend_invalidates_old_token_and_expiry_rejected(self):
        token = self.invitation()
        self.client.post("/api/enrollment/request", json={"email": "member@example.invalid"})
        self.assertEqual(self.activate(token).status_code, 400)
        self.client.post("/api/mail/retry", json={})
        fresh = re.search(r"#verify=(\S+)", self.messages[-1][3]).group(1)
        with Session(self.app.state.engine) as db:
            db.get(Challenge, digest(fresh)).expires = time.time() - 1
            db.commit()
        self.assertEqual(self.activate(fresh).status_code, 400)

    def test_owner_confirmation_does_not_reset_password(self):
        self.configure()
        self.client.post("/api/enrollment/request", json={"email": OWNER})
        self.client.post("/api/mail/retry", json={})
        token = re.search(r"#verify=(\S+)", self.messages[-1][3]).group(1)
        self.client.post("/api/enrollment/verify", json={"token": token, "password": "a different long password", "username": "hijack"})
        with Session(self.app.state.engine) as db:
            owner = db.scalar(select(Account).where(Account.email == OWNER))
            self.assertTrue(owner.verified)
            self.assertEqual(owner.username, "owner")
            self.assertTrue(HASHER.verify(owner.password, PASSWORD))

    def test_revocation_kills_sessions_and_pending_devices(self):
        token = self.invitation()
        self.activate(token)
        with Session(self.app.state.engine) as db:
            member = db.scalar(select(Account).where(Account.email == "member@example.invalid"))
            member_id = member.id
            db.add(Device(id="test-device", account_id=member_id))
            db.add(LoginSession(id=digest("synthetic-token"), account_id=member_id, csrf="synthetic", expires=time.time()+100))
            db.commit()
        self.assertEqual(self.client.post(f"/api/accounts/{member_id}/revoke", json={}).status_code, 200)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(LoginSession, digest("synthetic-token")))
            self.assertEqual(db.get(Device, "test-device").status, "revoked")
        self.assertEqual(self.login(email="member@example.invalid").status_code, 401)

    def test_mail_failure_is_retryable_and_secret_not_leaked(self):
        self.configure()
        def fail(*args):
            raise smtplib.SMTPException("smtp-test-secret")
        failed = create_app(self.db_url, self.path, PUBLIC, mailer=fail, mail_worker=False)
        with TestClient(failed, base_url=PUBLIC) as client:
            client.headers.update(dict(self.client.headers))
            client.cookies.update(self.client.cookies)
            response = client.post("/api/invitations", json={"email": "member@example.invalid"})
            self.assertEqual(response.json()["delivery"], "pending")
            self.assertNotIn("smtp-test-secret", response.text)
        self.assertEqual(self.client.post("/api/mail/retry", json={}).json()["sent"], 1)
        with Session(self.app.state.engine) as db:
            item = db.scalar(select(Outbox))
            self.assertEqual(item.payload, "")
            self.assertEqual(item.status, "sent")

    def test_plaintext_location_endpoints_are_not_exposed(self):
        self.setup_owner()
        for path in ("/api/locations", "/locations", "/api/devices/approve"):
            self.assertEqual(self.client.post(path, json={"location": "synthetic"}).status_code, 404)
        self.login()
        self.assertTrue(self.client.get("/api/devices").json()["pairing_available"])

    def test_setup_ui_and_security_headers(self):
        for path in ("/", "/app.js", "/style.css"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["referrer-policy"], "no-referrer")
            self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertNotIn(self.token, self.client.get("/").text)

    def test_default_map_configuration_requires_login(self):
        self.assertEqual(self.client.get("/api/maps").status_code, 401)
        self.configure()
        self.assertEqual(self.client.get("/api/maps").json(), {"provider": "openstreetmap", "api_key": ""})
        self.assertNotIn("googleapis.com", self.client.get("/").headers["content-security-policy"])

    def test_configured_google_maps_key_and_nonce(self):
        self.configure()
        with patch.dict(os.environ, {"STALKER_GOOGLE_MAPS_API_KEY": " synthetic-maps-key "}):
            application = create_app(self.db_url, self.path, PUBLIC, mail_worker=False)
        with TestClient(application, base_url=PUBLIC) as client:
            self.assertEqual(client.get("/api/maps").status_code, 401)
            client.cookies.update(self.client.cookies)
            result = client.get("/api/maps")
            self.assertEqual(result.json(), {"provider": "google", "api_key": "synthetic-maps-key"})
            self.assertEqual(result.headers["cache-control"], "no-store")
            page = client.get("/")
            nonce = re.search(r'<script nonce="([^"]+)"', page.text).group(1)
            self.assertIn(f"'nonce-{nonce}'", page.headers["content-security-policy"])
            self.assertIn("'strict-dynamic'", page.headers["content-security-policy"])
            self.assertNotIn("synthetic-maps-key", page.text)
            self.assertEqual(page.headers["referrer-policy"], "strict-origin-when-cross-origin")
            self.assertNotIn(f'nonce="{nonce}"', client.get("/").text)

    def test_whitespace_google_key_keeps_default_policy(self):
        with patch.dict(os.environ, {"STALKER_GOOGLE_MAPS_API_KEY": "   "}):
            application = create_app(self.db_url, self.path, PUBLIC, mail_worker=False)
        with TestClient(application, base_url=PUBLIC) as client:
            self.assertEqual(client.get("/").headers["referrer-policy"], "no-referrer")


if __name__ == "__main__":
    unittest.main()

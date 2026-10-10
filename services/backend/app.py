"""Persistent server setup. Location and cryptographic device APIs are gated."""
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from contextlib import asynccontextmanager
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Float, Integer, String, Text, create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

SCHEMA_VERSION = 2
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))


class Base(DeclarativeBase):
    pass


class Settings(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=SCHEMA_VERSION)
    household: Mapped[str | None] = mapped_column(String(80))
    bootstrap_hash: Mapped[str | None] = mapped_column(String(64))
    smtp: Mapped[str | None] = mapped_column(Text)
    mail_tested: Mapped[bool] = mapped_column(Boolean, default=False)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True)
    password: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(10), default="member")
    status: Mapped[str] = mapped_column(String(10), default="pending")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)


class Challenge(Base):
    __tablename__ = "challenges"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    expires: Mapped[float] = mapped_column(Float)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    created: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[float] = mapped_column(Float, default=0)


class Rate(Base):
    __tablename__ = "rate_limits"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started: Mapped[float] = mapped_column(Float)
    count: Mapped[int] = mapped_column(Integer)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetupInput(Input):
    token: str = Field(min_length=8, max_length=256)
    household: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=15, max_length=128)


class LoginInput(Input):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    native: bool = False


class EmailInput(Input):
    email: str = Field(min_length=3, max_length=254)


class VerifyInput(Input):
    token: str = Field(min_length=20, max_length=128)
    username: str | None = Field(default=None, min_length=3, max_length=64)
    password: str | None = Field(default=None, min_length=15, max_length=128)


class MailInput(Input):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    mode: str = Field(pattern="^(starttls|tls)$")
    username: str = Field(max_length=254)
    password: str | None = Field(default=None, max_length=1024)
    sender: str = Field(min_length=3, max_length=254)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def email_address(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[^\s<>@\r\n]+@[^\s<>@\r\n]+\.[^\s<>@\r\n]+", value):
        raise HTTPException(422, "Enter a valid email address")
    return value


def username(value):
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,64}", value):
        raise HTTPException(422, "Username: 3–64 letters, numbers, dots, dashes or underscores")
    return value.lower()


def secret_file(path, generator):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    value = generator()
    with os.fdopen(fd, "w") as f:
        f.write(value)
    return value


def create_app(database_url=None, data_dir=None, public_url=None, allow_http=None, mailer=None, mail_worker=True, notifier=None):
    from data_service import ServiceState, initialize_service, install, revoke_account_data
    database_url = database_url or os.environ["DATABASE_URL"]
    directory = Path(data_dir or os.environ.get("STALKER_DATA_DIR", "/data"))
    public_url = (public_url or os.environ["STALKER_PUBLIC_URL"]).rstrip("/")
    allow_http = allow_http if allow_http is not None else os.environ.get("STALKER_ALLOW_HTTP") == "1"
    url = urlsplit(public_url)
    if (url.scheme not in ("http", "https") or not url.hostname or url.username
            or url.password or url.path or url.query or url.fragment
            or (url.scheme == "http" and not allow_http)):
        raise ValueError("STALKER_PUBLIC_URL must be an HTTPS origin (HTTP requires explicit development opt-in)")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    engine = create_engine(database_url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        from sqlalchemy import event
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
    key_file = directory / "server.key"
    # An existing schema must never silently get a replacement encryption key.
    from sqlalchemy import inspect
    if not key_file.exists() and inspect(engine).has_table("settings"):
        raise RuntimeError("Server key is missing; restore the server data volume")
    cipher = Fernet(secret_file(key_file, lambda: Fernet.generate_key().decode()).encode())
    bootstrap_file = directory / "bootstrap-token"

    def initialize():
        from sqlalchemy import inspect, text
        with engine.begin() as connection:
            old = connection.execute(text("SELECT version FROM settings WHERE id=1")).scalar() if inspect(connection).has_table("settings") else None
            if old not in (None, 1, SCHEMA_VERSION):
                raise RuntimeError("Unsupported database version; apply a reviewed migration")
            Base.metadata.create_all(connection)
            if old == 1:
                connection.execute(text("UPDATE settings SET version=2 WHERE id=1"))
        with Session(engine) as db:
            settings = db.get(Settings, 1)
            configured_token = (os.environ.get("STALKER_SETUP_TOKEN") or None) if not settings or not settings.household else None
            if configured_token is not None:
                if not 8 <= len(configured_token) <= 256 or configured_token.strip() != configured_token:
                    raise ValueError("STALKER_SETUP_TOKEN must contain 8–256 characters without surrounding whitespace")
                # Explicit deployment configuration can replace an unclaimed token.
                # Completed setup never reads, restores or applies this value.
                fd = os.open(bootstrap_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(configured_token)
                bootstrap_file.chmod(0o600)
                if settings:
                    settings.bootstrap_hash = digest(configured_token)
                    db.commit()
            if settings is None:
                token = secret_file(bootstrap_file, lambda: secrets.token_urlsafe(32))
                db.add(Settings(id=1, bootstrap_hash=digest(token)))
                db.commit()
            elif settings.version != SCHEMA_VERSION:
                raise RuntimeError("Unsupported database version; restore the matching image or apply a reviewed migration")
            elif settings.household:
                bootstrap_file.unlink(missing_ok=True)
            elif not bootstrap_file.exists():
                raise RuntimeError("Bootstrap token file is missing; restore the server data volume")
            if settings and settings.smtp:
                try:
                    cipher.decrypt(settings.smtp.encode())
                except InvalidToken:
                    raise RuntimeError("Server key does not match stored credentials; restore the matching server data volume") from None

        try:
            initialize_service(engine, directory, cipher)
        except InvalidToken:
            raise RuntimeError("Server key does not match stored credentials; restore matching server data") from None

    @asynccontextmanager
    async def lifespan(app):
        initialize()
        async def worker():
            while True:
                await asyncio.sleep(5)
                try:
                    await asyncio.to_thread(worker_batch)
                    await asyncio.to_thread(app.state.maintenance)
                except (SQLAlchemyError, OSError, smtplib.SMTPException):
                    # Do not log provider exceptions, addresses or credentials.
                    pass
        task = asyncio.create_task(worker()) if mail_worker else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        engine.dispose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine, app.state.initialize, app.state.cipher = engine, initialize, cipher

    @app.middleware("http")
    async def boundaries(request, call_next):
        if request.url.path != "/healthz":
            if request.headers.get("host", "").lower() != url.netloc.lower():
                return JSONResponse({"detail": "Unrecognized server address"}, 400)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                native = request.headers.get("authorization", "").startswith("Bearer ") or (request.headers.get("x-stalker-client") == "native" and request.url.path in ("/api/login", "/api/enrollment/request", "/api/enrollment/verify"))
                if origin != public_url and not (origin is None and native):
                    return JSONResponse({"detail": "Origin rejected"}, 403)
                length = request.headers.get("content-length", "")
                maximum = 1048576 if request.url.path == "/api/records" else 32768 if request.url.path == "/api/push/config" else 16384 if request.url.path == "/api/roster" else 8192
                if not length.isdecimal() or int(length) > maximum:
                    return JSONResponse({"detail": "Request size rejected"}, 413)
                if len(await request.body()) > maximum:
                    return JSONResponse({"detail": "Request size rejected"}, 413)
                if not request.headers.get("content-type", "").startswith("application/json"):
                    return JSONResponse({"detail": "JSON required"}, 415)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tile.openstreetmap.org; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        return JSONResponse({"detail": "Database operation unavailable"}, 503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Return field constraints, never Pydantic's submitted input or context objects.
        fields = []
        for issue in error.errors():
            location = [str(part) for part in issue["loc"] if part != "body"]
            kind, context = issue["type"], issue.get("ctx", {})
            message = "Enter a valid value."
            if kind == "missing":
                message = "This field is required."
            elif kind == "string_too_short":
                message = f"Use at least {context['min_length']} characters."
            elif kind == "string_too_long":
                message = f"Use no more than {context['max_length']} characters."
            elif kind == "string_pattern_mismatch":
                message = "Check the allowed characters."
            elif kind == "json_invalid":
                message = "The request must contain valid JSON."
            fields.append({"field": ".".join(location), "message": message})
        return JSONResponse({"detail": "Please correct the highlighted fields.", "fields": fields}, 422)

    def database():
        with Session(engine) as db:
            yield db

    def rate(request, scope, limit=10):
        key = digest(f"{request.client.host}:{scope}")
        with Session(engine) as db:
            db.execute(select(Settings).where(Settings.id == 1).with_for_update()).scalar_one()
            item, now = db.get(Rate, key), time.time()
            if item is None:
                item = Rate(id=key, started=now, count=0)
                db.add(item)
            elif now - item.started >= 900:
                item.started, item.count = now, 0
            if item.count >= limit:
                raise HTTPException(429, "Too many requests; try again later")
            item.count += 1
            db.query(Rate).filter(Rate.started < now - 86400).delete()
            db.commit()

    def current(request: Request, db: Session = Depends(database)):
        bearer = request.headers.get("authorization", "")
        token = bearer[7:] if bearer.startswith("Bearer ") else request.cookies.get("stalker_session", "")
        session = db.get(LoginSession, digest(token))
        if not session or session.expires <= time.time():
            raise HTTPException(401, "Sign in required")
        account = db.get(Account, session.account_id)
        if not account or account.status != "active":
            raise HTTPException(401, "Sign in required")
        if not bearer.startswith("Bearer ") and request.method not in ("GET", "HEAD") and not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf):
            raise HTTPException(403, "Session confirmation required")
        return account, session

    def admin(auth=Depends(current)):
        if auth[0].role != "admin":
            raise HTTPException(403, "Administrator required")
        return auth

    def mail_settings(db):
        settings = db.get(Settings, 1)
        if not settings.smtp:
            raise HTTPException(409, "Configure email first")
        return json.loads(cipher.decrypt(settings.smtp.encode()))

    def deliver(config, recipient, subject, body):
        if mailer:
            mailer(config, recipient, subject, body)
            return
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = config["sender"], recipient, subject
        message.set_content(body)
        context = ssl.create_default_context()
        client = (smtplib.SMTP_SSL(config["host"], config["port"], timeout=10, context=context)
                  if config["mode"] == "tls" else smtplib.SMTP(config["host"], config["port"], timeout=10))
        with client:
            if config["mode"] == "starttls":
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            if config["username"]:
                client.login(config["username"], config["password"] or "")
            client.send_message(message)

    def queue(db, account):
        db.query(Outbox).filter_by(account_id=account.id, status="pending").update({Outbox.status: "expired", Outbox.payload: ""})
        db.query(Challenge).filter_by(account_id=account.id, used=False).delete()
        token = secrets.token_urlsafe(32)
        db.add(Challenge(id=digest(token), account_id=account.id, expires=time.time() + 1800))
        payload = {"recipient": account.email, "subject": "Family-Stalker: confirm your email",
                   "body": f"Confirm your invited account within 30 minutes:\n{public_url}/#verify={token}\n\nEmail confirmation does not approve a device or grant access to locations."}
        db.add(Outbox(id=secrets.token_hex(16), account_id=account.id, payload=cipher.encrypt(json.dumps(payload).encode()).decode(), created=time.time()))

    def flush_mail(db):
        config, sent = mail_settings(db), 0
        for item in db.scalars(select(Outbox).where(Outbox.status == "pending", Outbox.retry_at <= time.time()).order_by(Outbox.created).limit(20).with_for_update(skip_locked=True)).all():
            if item.created < time.time() - 1800:
                item.status, item.payload = "expired", ""
                continue
            payload = json.loads(cipher.decrypt(item.payload.encode()))
            item.attempts += 1
            try:
                deliver(config, payload["recipient"], payload["subject"], payload["body"])
            except (OSError, smtplib.SMTPException):
                item.retry_at = time.time() + min(300, 2 ** min(item.attempts, 8))
                db.commit()
                return {"sent": sent, "delivery": "pending"}
            item.status, item.payload = "sent", ""
            sent += 1
        db.commit()
        return {"sent": sent, "delivery": "sent"}

    def worker_batch():
        with Session(engine) as db:
            if db.get(Settings, 1).smtp:
                flush_mail(db)

    @app.get("/healthz")
    def health(db: Session = Depends(database)):
        return {"status": "ok", "stage": "setup", "configured": bool(db.get(Settings, 1).household)}

    @app.get("/api/setup")
    def setup_status(db: Session = Depends(database)):
        return {"configured": bool(db.get(Settings, 1).household), "public_url": public_url,
                "location_service": "encrypted_relay"}

    @app.post("/api/setup", status_code=201)
    def setup(body: SetupInput, request: Request, db: Session = Depends(database)):
        rate(request, "setup", 5)
        settings = db.execute(select(Settings).where(Settings.id == 1).with_for_update()).scalar_one()
        if settings.household:
            raise HTTPException(409, "Setup is already complete")
        if not hmac.compare_digest(digest(body.token), settings.bootstrap_hash or ""):
            raise HTTPException(403, "Invalid setup token")
        name = body.household.strip()
        if not name:
            raise HTTPException(422, "Household name is required")
        db.add(Account(id=secrets.token_hex(16), email=email_address(body.email), username=username(body.username),
                       password=HASHER.hash(body.password), role="admin", status="active", verified=False))
        settings.household, settings.bootstrap_hash = name, None
        db.commit()
        bootstrap_file.unlink(missing_ok=True)
        return {"configured": True}

    @app.post("/api/login")
    def login(body: LoginInput, request: Request, response: Response, db: Session = Depends(database)):
        rate(request, "login")
        account = db.scalar(select(Account).where(Account.email == body.email.strip().lower()))
        try:
            valid = HASHER.verify(account.password if account and account.password else DUMMY_HASH, body.password)
        except VerificationError:
            valid = False
        if not valid or not account or account.status != "active":
            raise HTTPException(401, "Email or password not accepted")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.query(LoginSession).filter(LoginSession.expires < time.time()).delete()
        db.add(LoginSession(id=digest(token), account_id=account.id, csrf=csrf, expires=time.time() + 43200))
        db.commit()
        response.set_cookie("stalker_session", token, httponly=True, secure=url.scheme == "https", samesite="strict", max_age=43200, path="/")
        return {"csrf": csrf, **({"access_token": token, "expires_in": 43200} if body.native else {})}

    @app.get("/api/session")
    def session(auth=Depends(current)):
        return {"id": auth[0].id, "email": auth[0].email, "username": auth[0].username,
                "role": auth[0].role, "verified": auth[0].verified, "csrf": auth[1].csrf}

    @app.post("/api/logout")
    def logout(response: Response, auth=Depends(current), db: Session = Depends(database)):
        db.delete(auth[1])
        db.commit()
        response.delete_cookie("stalker_session", path="/")
        return {"signed_out": True}

    @app.get("/api/admin")
    def dashboard(auth=Depends(admin), db: Session = Depends(database)):
        settings = db.get(Settings, 1)
        return {"household": settings.household, "public_url": public_url, "mail_configured": bool(settings.smtp),
                "mail_tested": settings.mail_tested, "location_service": "encrypted_relay", "device_pairing": "signed_roster",
                "pending_mail": db.query(Outbox).filter_by(status="pending").count()}

    @app.get("/api/mail")
    def get_mail(auth=Depends(admin), db: Session = Depends(database)):
        if not db.get(Settings, 1).smtp:
            return {"configured": False}
        config = mail_settings(db)
        config.pop("password", None)
        return {"configured": True, **config}

    @app.put("/api/mail")
    def save_mail(body: MailInput, auth=Depends(admin), db: Session = Depends(database)):
        if not re.fullmatch(r"[a-zA-Z0-9.-]+", body.host):
            raise HTTPException(422, "Use an SMTP hostname or IP")
        settings = db.get(Settings, 1)
        previous = mail_settings(db) if settings.smtp else {}
        config = body.model_dump()
        config["sender"] = email_address(body.sender)
        config["password"] = body.password if body.password is not None else previous.get("password", "")
        settings.smtp, settings.mail_tested = cipher.encrypt(json.dumps(config).encode()).decode(), False
        db.commit()
        return {"saved": True}

    @app.post("/api/mail/test")
    def test_mail(request: Request, auth=Depends(admin), db: Session = Depends(database)):
        rate(request, "mail", 10)
        try:
            deliver(mail_settings(db), auth[0].email, "Family-Stalker email test", "Your server's encrypted SMTP connection is working.")
        except (OSError, smtplib.SMTPException):
            raise HTTPException(502, "Email delivery failed; check hostname, port, TLS mode and credentials")
        db.get(Settings, 1).mail_tested = True
        db.commit()
        return {"sent": True}

    @app.post("/api/mail/retry")
    def retry_mail(request: Request, auth=Depends(admin), db: Session = Depends(database)):
        rate(request, "mail", 10)
        db.query(Outbox).filter_by(status="pending").update({Outbox.retry_at: 0})
        db.commit()
        return flush_mail(db)

    @app.get("/api/accounts")
    def accounts(auth=Depends(admin), db: Session = Depends(database)):
        return [{"id": a.id, "email": a.email, "username": a.username, "role": a.role,
                 "status": a.status, "verified": a.verified} for a in db.scalars(select(Account).order_by(Account.email))]

    @app.post("/api/invitations", status_code=201)
    def invite(body: EmailInput, request: Request, auth=Depends(admin), db: Session = Depends(database)):
        rate(request, "invite", 20)
        mail_settings(db)
        address = email_address(body.email)
        if db.scalar(select(Account).where(Account.email == address)):
            raise HTTPException(409, "Account already exists; use resend for pending accounts")
        account = Account(id=secrets.token_hex(16), email=address)
        db.add(account)
        db.flush()
        queue(db, account)
        db.commit()
        return {"invited": True, **flush_mail(db)}

    @app.post("/api/enrollment/request", status_code=202)
    def request_enrollment(body: EmailInput, request: Request, db: Session = Depends(database)):
        rate(request, "enrollment", 5)
        address = email_address(body.email)
        account = db.scalar(select(Account).where(Account.email == address))
        if account and account.status != "revoked" and (account.status == "pending" or not account.verified) and db.get(Settings, 1).smtp:
            queue(db, account)
            db.commit()
        return {"message": "If this email is eligible, a confirmation email will be sent"}

    @app.post("/api/enrollment/verify")
    def verify(body: VerifyInput, request: Request, db: Session = Depends(database)):
        rate(request, "verify", 10)
        challenge = db.execute(select(Challenge).where(Challenge.id == digest(body.token)).with_for_update()).scalar_one_or_none()
        if not challenge or challenge.used or challenge.expires <= time.time():
            raise HTTPException(400, "Confirmation link is invalid or expired")
        account = db.execute(select(Account).where(Account.id == challenge.account_id).with_for_update()).scalar_one()
        if account.status == "revoked":
            raise HTTPException(400, "Confirmation link is invalid or expired")
        if account.status == "pending":
            if not body.password or not body.username:
                raise HTTPException(422, "Choose a username and password")
            chosen = username(body.username)
            if db.scalar(select(Account).where(Account.username == chosen)):
                raise HTTPException(409, "Username unavailable")
            account.username, account.password, account.status = chosen, HASHER.hash(body.password), "active"
        # Existing accounts only confirm email: never reset passwords via email.
        account.verified, challenge.used = True, True
        db.commit()
        return {"verified": True, "device_approval_required": True}

    @app.post("/api/accounts/{account_id}/revoke")
    def revoke(account_id: str, auth=Depends(admin), db: Session = Depends(database)):
        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        account = db.get(Account, account_id)
        if not account:
            raise HTTPException(404, "Account not found")
        if account.role == "admin":
            raise HTTPException(409, "Owner revocation is not supported")
        revoke_account_data(db, account_id, auth[0].id)
        account.status = "revoked"
        db.query(LoginSession).filter_by(account_id=account_id).delete()
        db.query(Challenge).filter_by(account_id=account_id).delete()
        db.query(Outbox).filter_by(account_id=account_id, status="pending").update({Outbox.status: "expired", Outbox.payload: ""})
        db.query(Device).filter_by(account_id=account_id).update({Device.status: "revoked"})
        db.commit()
        return {"revoked": True}

    install(app, engine, directory, cipher, database, current, admin, rate, notifier)
    from push_service import install_push
    install_push(app, cipher, database, admin, notifier)

    assets = Path(__file__).parent / "static"

    @app.get("/")
    def index():
        return FileResponse(assets / "index.html")

    @app.get("/app.js")
    def javascript():
        return FileResponse(assets / "app.js", media_type="text/javascript")

    @app.get("/style.css")
    def stylesheet():
        return FileResponse(assets / "style.css", media_type="text/css")

    @app.get("/client.js")
    def client_bundle():
        return FileResponse(assets / "client.js", media_type="text/javascript")

    @app.get("/leaflet.css")
    def map_style():
        return FileResponse(assets / "leaflet.css", media_type="text/css")

    @app.get("/images/{name}")
    def map_asset(name: str):
        if name not in ("marker-icon.png", "marker-icon-2x.png", "marker-shadow.png", "layers.png", "layers-2x.png"):
            raise HTTPException(404)
        return FileResponse(assets / "images" / name)

    return app

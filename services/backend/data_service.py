"""Authenticated opaque data relay. Private client keys never enter this module."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Depends, HTTPException, Request
from pydantic import Field, ConfigDict
from typing import Literal
from nacl.exceptions import BadSignatureError, CryptoError
from nacl.bindings import crypto_scalarmult
from nacl.signing import VerifyKey
from sqlalchemy import BigInteger, Boolean, Float, Integer, String, Text, UniqueConstraint, ForeignKey, Index, func, select, and_, or_
from sqlalchemy.orm import Mapped, Session, mapped_column
from app import Account, Base, Input, LoginSession, Settings, digest, secret_file

DAY = 86400
MAX_DEVICES = 32


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def decode(value, length=None, minimum=None, maximum=None):
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid base64 encoding")
    if base64.b64encode(result).decode() != value or (length is not None and len(result) != length) or (minimum is not None and len(result) < minimum) or (maximum is not None and len(result) > maximum):
        raise HTTPException(422, "Invalid encoded payload length")
    return result


def verify_signature(key, body, signature):
    try:
        VerifyKey(decode(key, 32)).verify(canonical(body), decode(signature, 64))
    except BadSignatureError:
        raise HTTPException(403, "Signature rejected")


class ServiceState(Base):
    __tablename__ = "service_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[str] = mapped_column(String(32))
    retention_days: Mapped[int] = mapped_column(Integer, default=14)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    anchor: Mapped[str | None] = mapped_column(String(44))
    bootstrap_hash: Mapped[str | None] = mapped_column(String(64))
    last_cleanup: Mapped[float] = mapped_column(Float, default=0)
    push_config: Mapped[str | None] = mapped_column(Text)
    key_check: Mapped[str] = mapped_column(Text)


class ClientDevice(Base):
    __tablename__ = "client_devices"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(64))
    signing_key: Mapped[str] = mapped_column(String(44), unique=True)
    box_key: Mapped[str] = mapped_column(String(44), unique=True)
    credential: Mapped[str] = mapped_column(String(64), unique=True)
    registration: Mapped[str] = mapped_column(Text)
    registration_signature: Mapped[str] = mapped_column(String(88))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    sharing: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    created: Mapped[float] = mapped_column(Float)
    seen: Mapped[float] = mapped_column(Float, default=0)


class RosterRevision(Base):
    __tablename__ = "roster_revisions"
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(String(88))
    hash: Mapped[str] = mapped_column(String(64))


class EncryptedRecord(Base):
    __tablename__ = "encrypted_records"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    device_id: Mapped[str] = mapped_column(String(32), index=True)
    sequence: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(10), index=True)
    entity_id: Mapped[str] = mapped_column(String(32), index=True)
    captured_at: Mapped[int] = mapped_column(BigInteger, index=True)
    received_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float | None] = mapped_column(Float, index=True)
    operation: Mapped[str] = mapped_column(String(10))
    envelope: Mapped[str] = mapped_column(Text)
    bytes: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("device_id", "sequence"), Index("ix_records_device_received", "device_id", "received_at"), Index("ix_record_history", "kind", "captured_at", "id"))


class RecordRecipient(Base):
    __tablename__ = "record_recipients"
    record_id: Mapped[str] = mapped_column(ForeignKey("encrypted_records.id", ondelete="CASCADE"), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)


class LatestState(Base):
    __tablename__ = "latest_state"
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("encrypted_records.id", ondelete="CASCADE"), unique=True)
    captured_at: Mapped[int] = mapped_column(BigInteger)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    device_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(10))
    token: Mapped[str] = mapped_column(Text)


class PushDelivery(Base):
    __tablename__ = "push_deliveries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    record_id: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[str] = mapped_column(String(32), index=True)
    created: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[float] = mapped_column(Float, default=0)


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    action: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str] = mapped_column(String(36))
    target_id: Mapped[str | None] = mapped_column(String(36))
    created: Mapped[float] = mapped_column(Float, index=True)


class CryptoInput(Input):
    model_config = ConfigDict(extra="forbid", strict=True)


class RegisterInput(CryptoInput):
    id: str = Field(pattern="^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=64)
    signing_key: str = Field(max_length=44)
    box_key: str = Field(max_length=44)
    signature: str = Field(max_length=88)


class Identity(CryptoInput):
    id: str = Field(pattern="^[a-f0-9]{32}$")
    account_id: str = Field(pattern="^[a-f0-9]{32}$")
    signing_key: str = Field(max_length=44)
    box_key: str = Field(max_length=44)


class RosterBody(CryptoInput):
    domain: Literal["family-stalker.roster.v1"]
    household: str = Field(pattern="^[a-f0-9]{32}$")
    revision: int = Field(ge=1, le=2147483647)
    previous: str = Field(pattern="^([a-f0-9]{64})?$")
    signer: str = Field(pattern="^[a-f0-9]{32}$")
    devices: list[Identity] = Field(min_length=1, max_length=MAX_DEVICES)
    issued_at: int = Field(ge=0)


class RosterInput(Input):
    body: RosterBody
    signature: str = Field(max_length=88)
    bootstrap_token: str | None = Field(default=None, max_length=128)


class Recipient(Input):
    device_id: str = Field(pattern="^[a-f0-9]{32}$")
    box: str = Field(min_length=64, max_length=100000)


class RecordBody(CryptoInput):
    domain: Literal["family-stalker.record.v1"]
    household: str = Field(pattern="^[a-f0-9]{32}$")
    revision: int = Field(ge=1)
    id: str = Field(pattern="^[a-f0-9]{32}$")
    sender: str = Field(pattern="^[a-f0-9]{32}$")
    sequence: int = Field(ge=1, le=9007199254740991)
    kind: str = Field(pattern="^(location|event|place|profile)$")
    entity_id: str = Field(pattern="^[a-f0-9]{32}$")
    operation: str = Field(pattern="^(upsert|delete)$")
    replaces: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    captured_at: int = Field(ge=0, le=9007199254740991)
    recipients: list[Recipient] = Field(min_length=1, max_length=MAX_DEVICES)


class RecordInput(Input):
    body: RecordBody
    signature: str = Field(max_length=88)


class SharingInput(Input):
    enabled: bool


class RetentionInput(Input):
    days: int = Field(ge=1, le=14)


class SubscribeInput(Input):
    provider: str = Field(pattern="^(apns|fcm)$")
    token: str = Field(min_length=16, max_length=4096)


def identity(device):
    return {"id": device.id, "account_id": device.account_id, "signing_key": device.signing_key, "box_key": device.box_key}


def audit(db, action, actor, target=None):
    db.add(AuditEntry(id=secrets.token_hex(16), action=action, actor_id=actor, target_id=target, created=time.time()))


def initialize_service(engine, directory, cipher):
    with Session(engine) as db:
        state = db.get(ServiceState, 1)
        if state is None:
            token = secret_file(directory / "device-bootstrap-token", lambda: secrets.token_urlsafe(32))
            db.add(ServiceState(id=1, household_id=secrets.token_hex(16), bootstrap_hash=digest(token), key_check=cipher.encrypt(b"family-stalker.storage.v1").decode()))
            db.commit()
        elif cipher.decrypt(state.key_check.encode()) != b"family-stalker.storage.v1":
            raise RuntimeError("Server storage key check failed")
        elif state.anchor:
            (directory / "device-bootstrap-token").unlink(missing_ok=True)
        elif not (directory / "device-bootstrap-token").exists():
            raise RuntimeError("Device bootstrap token missing; restore matching server data")


def prune(db):
    now = time.time()
    state = db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
    cutoff = int((now - state.retention_days * DAY) * 1000)
    db.query(EncryptedRecord).filter(EncryptedRecord.kind.in_(["location", "event"]), or_(EncryptedRecord.captured_at <= cutoff, EncryptedRecord.expires_at <= now)).delete(synchronize_session=False)
    db.query(PushDelivery).filter(PushDelivery.expires_at <= now).delete(synchronize_session=False)
    db.query(AuditEntry).filter(AuditEntry.created <= now - 14 * DAY).delete(synchronize_session=False)
    db.query(LoginSession).filter(LoginSession.expires <= now).delete(synchronize_session=False)
    state.last_cleanup = now
    db.commit()


def revoke_account_data(db, account_id, actor_id):
    ids = list(db.scalars(select(ClientDevice.id).where(ClientDevice.account_id == account_id)))
    db.query(ClientDevice).filter_by(account_id=account_id).update({ClientDevice.status: "revoked"})
    if ids:
        db.query(PushSubscription).filter(PushSubscription.device_id.in_(ids)).delete(synchronize_session=False)
        db.query(PushDelivery).filter(PushDelivery.device_id.in_(ids)).delete(synchronize_session=False)
    audit(db, "account.revoked", actor_id, account_id)


def install(app, engine, directory, cipher, database, current, admin, rate, notifier=None):
    quota = int(os.environ.get("STALKER_STORAGE_QUOTA_MIB", "512")) * 1024 * 1024
    if quota < 1024 * 1024:
        raise ValueError("Storage quota must be at least 1 MiB")

    def verified(auth=Depends(current)):
        if not auth[0].verified:
            raise HTTPException(403, "Confirm your email before enrolling a device")
        return auth

    def credential(request: Request, db: Session = Depends(database)):
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or len(header) > 200:
            raise HTTPException(401, "Device credential required")
        device = db.scalar(select(ClientDevice).where(ClientDevice.credential == digest(header[7:])))
        account = db.get(Account, device.account_id) if device else None
        if not device or device.status == "revoked" or not account or account.status != "active" or not account.verified:
            raise HTTPException(401, "Device credential not accepted")
        return device

    def approved(device=Depends(credential)):
        if device.status != "approved":
            raise HTTPException(403, "Trusted device approval required")
        return device

    def active_devices(db):
        return list(db.scalars(select(ClientDevice).join(Account, Account.id == ClientDevice.account_id).where(ClientDevice.status == "approved", Account.status == "active", Account.verified.is_(True)).order_by(ClientDevice.id)))

    def available(record, device):
        body = json.loads(record.envelope)["body"]
        return any(x["device_id"] == device.id for x in body["recipients"])

    def visible_query(db):
        cutoff = int((time.time() - db.get(ServiceState, 1).retention_days * DAY) * 1000)
        return select(EncryptedRecord).where((EncryptedRecord.expires_at.is_(None)) | and_(EncryptedRecord.captured_at > cutoff, EncryptedRecord.expires_at > time.time()))

    def serialize(record):
        return {"envelope": json.loads(record.envelope), "received_at": record.received_at, "expires_at": record.expires_at}

    @app.get("/api/household")
    def household(auth=Depends(current), db: Session = Depends(database)):
        s = db.get(ServiceState, 1)
        return {"id": s.household_id, "revision": s.revision, "anchor": s.anchor, "retention_days": s.retention_days, "transport": "https", "protocol": "sealed-box-ed25519-v1"}

    @app.post("/api/devices/register", status_code=201)
    def register(body: RegisterInput, request: Request, auth=Depends(verified), db: Session = Depends(database)):
        rate(request, "register", 10)
        state = db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        if db.query(ClientDevice).filter_by(account_id=auth[0].id).filter(ClientDevice.status != "revoked").count() >= 8 or db.query(ClientDevice).filter(ClientDevice.status != "revoked").count() >= 64:
            raise HTTPException(409, "Device limit reached; remove an unused device")
        if db.get(ClientDevice, body.id) or db.scalar(select(ClientDevice).where((ClientDevice.signing_key == body.signing_key) | (ClientDevice.box_key == body.box_key))):
            raise HTTPException(409, "Device identity already registered")
        try:
            crypto_scalarmult(secrets.token_bytes(32), decode(body.box_key, 32))
        except CryptoError:
            raise HTTPException(422, "Invalid X25519 public key")
        registration = {"domain": "family-stalker.device.v1", "household": state.household_id, "id": body.id, "account_id": auth[0].id, "signing_key": body.signing_key, "box_key": body.box_key}
        verify_signature(body.signing_key, registration, body.signature)
        token = secrets.token_urlsafe(32)
        db.add(ClientDevice(id=body.id, account_id=auth[0].id, name=body.name.strip(), signing_key=body.signing_key, box_key=body.box_key, credential=digest(token), registration=canonical(registration).decode(), registration_signature=body.signature, created=time.time()))
        audit(db, "device.registered", auth[0].id, body.id)
        db.commit()
        return {"id": body.id, "credential": token, "status": "pending"}

    @app.get("/api/devices")
    def devices(auth=Depends(current), db: Session = Depends(database)):
        query = select(ClientDevice).order_by(ClientDevice.created)
        if not auth[0].verified:
            query = query.where(ClientDevice.account_id == auth[0].id)
        return {"pairing_available": True, "devices": [{**identity(d), "name": d.name, "status": d.status, "sharing": d.sharing, "sequence": d.last_sequence, "seen": d.seen, "registration": json.loads(d.registration), "registration_signature": d.registration_signature} for d in db.scalars(query)]}

    @app.get("/api/device")
    def own_device(device=Depends(credential)):
        return {**identity(device), "name": device.name, "status": device.status, "sharing": device.sharing, "sequence": device.last_sequence}

    @app.get("/api/roster")
    def roster(after: int = 0, device=Depends(credential), db: Session = Depends(database)):
        if after < 0:
            raise HTTPException(422, "Invalid revision")
        state = db.get(ServiceState, 1)
        # Bounded chain pages; clients verify every revision, never just a directory.
        rows = list(db.scalars(select(RosterRevision).where(RosterRevision.revision > after).order_by(RosterRevision.revision).limit(100)))
        return {"household": state.household_id, "revision": state.revision, "anchor": state.anchor, "changes": [{"body": json.loads(r.payload), "signature": r.signature, "hash": r.hash} for r in rows]}

    @app.post("/api/roster")
    def change_roster(body: RosterInput, device=Depends(credential), db: Session = Depends(database)):
        state = db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        db.refresh(device)
        value = body.body.model_dump()
        if value["household"] != state.household_id or value["signer"] != device.id or value["revision"] != state.revision + 1 or abs(value["issued_at"] - int(time.time())) > 300:
            raise HTTPException(409, "Roster revision or identity mismatch")
        previous = db.get(RosterRevision, state.revision)
        if value["previous"] != (previous.hash if previous else ""):
            raise HTTPException(409, "Roster chain mismatch")
        ids = [d["id"] for d in value["devices"]]
        if ids != sorted(set(ids)):
            raise HTTPException(422, "Roster identities must be sorted and unique")
        actual = []
        for ident in value["devices"]:
            d = db.get(ClientDevice, ident["id"])
            a = db.get(Account, d.account_id) if d else None
            if not d or d.status == "revoked" or not a or a.status != "active" or not a.verified or identity(d) != ident:
                raise HTTPException(403, "Device identity is ineligible")
            actual.append(d)
        verify_signature(device.signing_key, value, body.signature)
        account = db.get(Account, device.account_id)
        if state.revision == 0:
            if account.role != "admin" or ids != [device.id] or not body.bootstrap_token or not hmac.compare_digest(digest(body.bootstrap_token), state.bootstrap_hash or ""):
                raise HTTPException(403, "Local device bootstrap authorization required")
            state.anchor, state.bootstrap_hash = device.signing_key, None
        else:
            if device.status != "approved":
                raise HTTPException(403, "An existing trusted device must approve membership")
            old = json.loads(previous.payload)["devices"]
            old_ids = {d["id"] for d in old}
            if account.role != "admin":
                # Any trusted recipient can approve an already-invited, verified device.
                # Only owners can revoke someone else; members can revoke their own.
                if any(d["account_id"] != device.account_id for d in old if d["id"] not in ids):
                    raise HTTPException(403, "Only an owner device can revoke other members")
        for d in active_devices(db):
            if d.id not in ids:
                d.status = "revoked"
                db.query(PushSubscription).filter_by(device_id=d.id).delete()
                db.query(PushDelivery).filter_by(device_id=d.id).delete()
        for d in actual:
            d.status = "approved"
        snapshot = {"body": value, "signature": body.signature}
        hash_value = hashlib.sha256(canonical(snapshot)).hexdigest()
        db.add(RosterRevision(revision=value["revision"], payload=canonical(value).decode(), signature=body.signature, hash=hash_value))
        state.revision = value["revision"]
        audit(db, "roster.changed", device.account_id)
        db.commit()
        (directory / "device-bootstrap-token").unlink(missing_ok=True)
        return {"revision": state.revision, "hash": hash_value}

    @app.put("/api/sharing")
    def sharing(body: SharingInput, device=Depends(approved), db: Session = Depends(database)):
        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        db.refresh(device)
        if device.status != "approved":
            raise HTTPException(403, "Device revoked")
        device.sharing = body.enabled
        audit(db, "sharing.resumed" if body.enabled else "sharing.paused", device.account_id, device.id)
        db.commit()
        return {"enabled": device.sharing}

    @app.post("/api/records", status_code=201)
    def ingest(body: RecordInput, device=Depends(approved), db: Session = Depends(database)):
        # Serialize household changes with publication: no stale-recipient race.
        state = db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        db.refresh(device)
        if device.status != "approved" or db.get(Account, device.account_id).status != "active":
            raise HTTPException(403, "Device access revoked")
        value, now = body.body.model_dump(), time.time()
        if value["sender"] != device.id or value["household"] != state.household_id:
            raise HTTPException(403, "Sender or household mismatch")
        verify_signature(device.signing_key, value, body.signature)
        envelope = canonical(body.model_dump()).decode()
        existing = db.get(EncryptedRecord, value["id"])
        if existing:
            if existing.device_id != device.id or existing.envelope != envelope:
                raise HTTPException(409, "Record identity collision")
            return {"id": existing.id, "duplicate": True}
        if value["revision"] != state.revision:
            raise HTTPException(409, "Refresh trusted membership and re-encrypt before publishing")
        recipients = [r["device_id"] for r in value["recipients"]]
        if recipients != sorted(d.id for d in active_devices(db)):
            raise HTTPException(409, "Encrypt separately for every currently approved device")
        for recipient in value["recipients"]:
            decode(recipient["box"], minimum=48, maximum=16384 if value["kind"] == "profile" else 2048)
        size = len(envelope.encode())
        if size > 1024 * 1024:
            raise HTTPException(413, "Encrypted record too large")
        if value["sequence"] <= device.last_sequence:
            raise HTTPException(409, "Device sequence replay rejected")
        if value["captured_at"] > int((now + 300) * 1000) or value["captured_at"] <= int((now - state.retention_days * DAY) * 1000):
            raise HTTPException(422, "Capture time outside the retention window")
        if value["kind"] in ("location", "event") and (not device.sharing or value["operation"] != "upsert"):
            raise HTTPException(403, "Sharing paused or invalid operation")
        if value["kind"] in ("location", "profile") and value["entity_id"] != device.account_id:
            raise HTTPException(403, "This record must describe the publishing account")
        used = db.scalar(select(func.coalesce(func.sum(EncryptedRecord.bytes), 0)))
        if used + size > quota:
            raise HTTPException(507, "Encrypted storage quota reached; run retention cleanup")
        latest_state = db.get(LatestState, (value["kind"], value["entity_id"]))
        if value["kind"] in ("place", "profile"):
            if value["replaces"] != (latest_state.record_id if latest_state else None):
                raise HTTPException(409, "Saved state changed; refresh before editing")
            if latest_state is None and db.query(LatestState).filter(LatestState.kind.in_(["place", "profile"])).count() >= 64:
                raise HTTPException(409, "Saved state limit reached")
        elif db.query(EncryptedRecord).filter_by(device_id=device.id).filter(EncryptedRecord.received_at > now - 60).count() >= 120:
            raise HTTPException(429, "Device update rate exceeded")
        record = EncryptedRecord(id=value["id"], account_id=device.account_id, device_id=device.id, sequence=value["sequence"], kind=value["kind"], entity_id=value["entity_id"], captured_at=value["captured_at"], received_at=now, expires_at=(value["captured_at"] / 1000 + state.retention_days * DAY) if value["kind"] in ("location", "event") else None, operation=value["operation"], envelope=envelope, bytes=size)
        db.add(record)
        db.flush()
        for recipient in recipients:
            db.add(RecordRecipient(record_id=record.id, device_id=recipient))
        if value["kind"] in ("location", "place", "profile"):
            if latest_state is None:
                db.add(LatestState(kind=value["kind"], entity_id=value["entity_id"], record_id=record.id, captured_at=value["captured_at"]))
            elif value["kind"] != "location" or value["captured_at"] >= latest_state.captured_at:
                old_id = latest_state.record_id
                latest_state.record_id, latest_state.captured_at = record.id, value["captured_at"]
                db.flush()
                if value["kind"] in ("place", "profile"):
                    db.query(EncryptedRecord).filter_by(id=old_id).delete(synchronize_session=False)
        device.last_sequence, device.seen = value["sequence"], now
        if value["kind"] == "event":
            for target in active_devices(db):
                if target.id != device.id and db.get(PushSubscription, target.id):
                    db.add(PushDelivery(id=secrets.token_hex(16), record_id=record.id, device_id=target.id, created=now, expires_at=min(record.expires_at, now + 3600)))
        db.commit()
        return {"id": record.id, "duplicate": False}

    @app.get("/api/records")
    def history(kind: str = "location", cursor: str | None = None, limit: int = 50, device=Depends(approved), db: Session = Depends(database)):
        if kind not in ("location", "event") or not 1 <= limit <= 50:
            raise HTTPException(422, "Use a history kind and limit 1–50")
        query = visible_query(db).join(RecordRecipient, RecordRecipient.record_id == EncryptedRecord.id).where(RecordRecipient.device_id == device.id, EncryptedRecord.kind == kind)
        if cursor is not None:
            import re
            if not re.fullmatch(r"[0-9]{1,16}:[a-f0-9]{32}", cursor):
                raise HTTPException(422, "Invalid history cursor")
            stamp, ident = cursor.split(":")
            query = query.where(or_(EncryptedRecord.captured_at < int(stamp), and_(EncryptedRecord.captured_at == int(stamp), EncryptedRecord.id < ident)))
        rows = list(db.scalars(query.order_by(EncryptedRecord.captured_at.desc(), EncryptedRecord.id.desc()).limit(limit + 1)))
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {"records": [serialize(r) for r in rows], "next_cursor": f"{rows[-1].captured_at}:{rows[-1].id}" if has_more else None}

    @app.get("/api/records/{record_id}")
    def get_record(record_id: str, device=Depends(approved), db: Session = Depends(database)):
        record = db.scalar(visible_query(db).where(EncryptedRecord.id == record_id))
        if not record or not available(record, device):
            raise HTTPException(404, "Record not available")
        return serialize(record)

    @app.get("/api/state")
    def latest(cursor: str | None = None, limit: int = 8, device=Depends(approved), db: Session = Depends(database)):
        if not 1 <= limit <= 8:
            raise HTTPException(422, "Use a state page size 1–8")
        query = visible_query(db).join(LatestState, LatestState.record_id == EncryptedRecord.id).join(RecordRecipient, RecordRecipient.record_id == EncryptedRecord.id).join(ClientDevice, ClientDevice.id == EncryptedRecord.device_id).where(RecordRecipient.device_id == device.id, or_(EncryptedRecord.kind != "location", and_(ClientDevice.status == "approved", ClientDevice.sharing.is_(True))))
        if cursor:
            import re
            if not re.fullmatch(r"(location|place|profile):[a-f0-9]{32}", cursor):
                raise HTTPException(422, "Invalid state cursor")
            kind, entity = cursor.split(":")
            query = query.where(or_(EncryptedRecord.kind > kind, and_(EncryptedRecord.kind == kind, EncryptedRecord.entity_id > entity)))
        rows = list(db.scalars(query.order_by(EncryptedRecord.kind, EncryptedRecord.entity_id).limit(limit + 1)))
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {"revision": db.get(ServiceState, 1).revision, "records": [serialize(r) for r in rows], "next_cursor": f"{rows[-1].kind}:{rows[-1].entity_id}" if has_more else None}

    @app.delete("/api/records/mine")
    def erase_own_history(device=Depends(approved), db: Session = Depends(database)):
        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
        db.query(PushDelivery).filter(PushDelivery.record_id.in_(select(EncryptedRecord.id).where(EncryptedRecord.account_id == device.account_id, EncryptedRecord.kind.in_(["location", "event"])))).delete(synchronize_session=False)
        count = db.query(EncryptedRecord).filter(EncryptedRecord.account_id == device.account_id, EncryptedRecord.kind.in_(["location", "event"])).delete(synchronize_session=False)
        audit(db, "history.deleted", device.account_id)
        db.commit()
        return {"deleted": count}

    @app.get("/api/storage")
    def storage(auth=Depends(admin), db: Session = Depends(database)):
        state = db.get(ServiceState, 1)
        count, size = db.execute(select(func.count(EncryptedRecord.id), func.coalesce(func.sum(EncryptedRecord.bytes), 0))).one()
        return {"retention_days": state.retention_days, "records": count, "bytes": size, "quota_bytes": quota, "last_cleanup": state.last_cleanup, "pending_push": db.query(PushDelivery).count(), "persistent_kinds": ["place", "profile"]}

    @app.put("/api/storage/retention")
    def retention(body: RetentionInput, auth=Depends(admin), db: Session = Depends(database)):
        db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one().retention_days = body.days
        db.query(EncryptedRecord).filter(EncryptedRecord.kind.in_(["location", "event"])).update({EncryptedRecord.expires_at: EncryptedRecord.captured_at / 1000 + body.days * DAY}, synchronize_session=False)
        db.query(PushDelivery).filter(PushDelivery.created <= time.time() - body.days * DAY).delete(synchronize_session=False)
        audit(db, "retention.changed", auth[0].id)
        db.commit()
        prune(db)
        return {"days": body.days}

    @app.post("/api/storage/cleanup")
    def cleanup(auth=Depends(admin), db: Session = Depends(database)):
        prune(db)
        return {"cleaned": True}

    @app.get("/api/audit")
    def audit_log(auth=Depends(admin), db: Session = Depends(database)):
        return [{"action": e.action, "actor_id": e.actor_id, "target_id": e.target_id, "created": e.created} for e in db.scalars(select(AuditEntry).where(AuditEntry.created > time.time() - 14 * DAY).order_by(AuditEntry.created.desc()).limit(100))]

    @app.put("/api/push/subscription")
    def subscribe(body: SubscribeInput, device=Depends(approved), db: Session = Depends(database)):
        import re
        if (body.provider == "apns" and not re.fullmatch(r"[a-fA-F0-9]{32,512}", body.token)) or not body.token.isascii() or any(c.isspace() for c in body.token):
            raise HTTPException(422, "Invalid push registration token")
        value = cipher.encrypt(body.token.encode()).decode()
        existing = db.get(PushSubscription, device.id)
        if existing:
            existing.provider, existing.token = body.provider, value
        else:
            db.add(PushSubscription(device_id=device.id, provider=body.provider, token=value))
        db.commit()
        return {"registered": True}

    @app.delete("/api/push/subscription")
    def unsubscribe(device=Depends(approved), db: Session = Depends(database)):
        db.query(PushSubscription).filter_by(device_id=device.id).delete()
        db.query(PushDelivery).filter_by(device_id=device.id).delete()
        db.commit()
        return {"removed": True}

    def maintenance():
        with Session(engine) as db:
            if time.time() - db.get(ServiceState, 1).last_cleanup >= 300:
                prune(db)
            from push_service import send_queued
            send_queued(db, cipher, notifier)
    app.state.maintenance = maintenance

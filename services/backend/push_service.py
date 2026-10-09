"""Generic push delivery; never accepts plaintext coordinates or place names."""
import json
import re
import time
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account
from app import Account, Input
from data_service import ClientDevice, PushDelivery, PushSubscription, ServiceState, audit


class APNsConfig(Input):
    team_id: str = Field(pattern="^[A-Z0-9]{10}$")
    key_id: str = Field(pattern="^[A-Z0-9]{10}$")
    topic: str = Field(pattern="^[A-Za-z0-9.-]{3,200}$")
    sandbox: bool = True
    private_key: str = Field(min_length=50, max_length=10000)


class PushConfig(Input):
    apns: APNsConfig | None = None
    fcm: dict | None = None


def config_value(body):
    value = body.model_dump()
    try:
        if value["apns"]:
            key = serialization.load_pem_private_key(value["apns"]["private_key"].encode(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
                raise ValueError()
        if value["fcm"]:
            conf = value["fcm"]
            if not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", conf.get("project_id", "")) or conf.get("token_uri") != "https://oauth2.googleapis.com/token":
                raise ValueError()
            service_account.Credentials.from_service_account_info(conf, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
    except (ValueError, TypeError, KeyError, GoogleAuthError):
        raise HTTPException(422, "Check the APNs P-256 key or FCM service-account credentials")
    return value


def deliver(provider, token, record_id, delivery_id, config, expires_at=None):
    expires_at = expires_at or time.time() + 3600
    if provider == "apns":
        c = config["apns"]
        jwt_token = jwt.encode({"iss": c["team_id"], "iat": int(time.time())}, c["private_key"], algorithm="ES256", headers={"kid": c["key_id"]})
        host = "https://api.sandbox.push.apple.com" if c["sandbox"] else "https://api.push.apple.com"
        with httpx.Client(http2=True, timeout=10, follow_redirects=False) as client:
            response = client.post(f"{host}/3/device/{token}", headers={"authorization": f"bearer {jwt_token}", "apns-topic": c["topic"], "apns-push-type": "alert", "apns-priority": "10", "apns-expiration": str(int(expires_at)), "apns-id": str(uuid.UUID(delivery_id))}, json={"aps": {"alert": {"title": "Family-Stalker", "body": "A household update is available."}, "sound": "default"}, "record_id": record_id})
        if response.status_code == 410:
            return "invalid"
        if response.status_code not in (200,):
            raise OSError("Push provider rejected delivery")
    else:
        c = config["fcm"]
        credentials = service_account.Credentials.from_service_account_info(c, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
        request = GoogleRequest()
        def bounded_request(*args, **kwargs):
            kwargs["timeout"] = 10
            return request(*args, **kwargs)
        credentials.refresh(bounded_request)
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            response = client.post(f"https://fcm.googleapis.com/v1/projects/{c['project_id']}/messages:send", headers={"authorization": f"Bearer {credentials.token}"}, json={"message": {"token": token, "notification": {"title": "Family-Stalker", "body": "A household update is available."}, "data": {"record_id": record_id}, "android": {"ttl": f"{max(0, min(3600, int(expires_at - time.time())))}s"}}})
        if response.status_code != 200:
            try:
                invalid = any(x.get("errorCode") == "UNREGISTERED" for x in response.json().get("error", {}).get("details", []))
            except (ValueError, TypeError, AttributeError):
                invalid = False
            if invalid:
                return "invalid"
            raise OSError("Push provider rejected delivery")
    return "sent"


def send_queued(db, cipher, notifier=None):
    state = db.get(ServiceState, 1)
    if not state.push_config:
        return
    config = json.loads(cipher.decrypt(state.push_config.encode()))
    rows = list(db.scalars(select(PushDelivery).where(PushDelivery.retry_at <= time.time()).order_by(PushDelivery.created).limit(4).with_for_update(skip_locked=True)))
    for item in rows:
        sub, device = db.get(PushSubscription, item.device_id), db.get(ClientDevice, item.device_id)
        account = db.get(Account, device.account_id) if device else None
        if item.expires_at <= time.time() or not sub or not device or device.status != "approved" or not account or account.status != "active":
            db.delete(item)
            continue
        if not config.get(sub.provider):
            continue
        try:
            status = (notifier or deliver)(sub.provider, cipher.decrypt(sub.token.encode()).decode(), item.record_id, item.id, config, item.expires_at)
        except (OSError, httpx.HTTPError, GoogleAuthError, jwt.PyJWTError, ValueError, TypeError):
            item.attempts += 1
            item.retry_at = time.time() + min(300, 2 ** min(item.attempts, 8))
            continue
        if status == "invalid":
            db.delete(sub)
        db.delete(item)
    db.commit()


def install_push(app, cipher, database, admin, notifier=None):
    @app.get("/api/push/config")
    def get_config(auth=Depends(admin), db=Depends(database)):
        state = db.get(ServiceState, 1)
        conf = json.loads(cipher.decrypt(state.push_config.encode())) if state.push_config else {}
        return {"apns": {key: value for key, value in conf.get("apns", {}).items() if key != "private_key"} if conf.get("apns") else None, "fcm_project": (conf.get("fcm") or {}).get("project_id")}

    @app.put("/api/push/config")
    def save_config(body: PushConfig, auth=Depends(admin), db=Depends(database)):
        conf = config_value(body)
        db.get(ServiceState, 1).push_config = cipher.encrypt(json.dumps(conf).encode()).decode()
        audit(db, "push.configured", auth[0].id)
        db.commit()
        return {"saved": True}

    @app.post("/api/push/test")
    def test_push(auth=Depends(admin), db=Depends(database)):
        state = db.get(ServiceState, 1)
        if not state.push_config:
            raise HTTPException(409, "Configure push first")
        config = json.loads(cipher.decrypt(state.push_config.encode()))
        # Only the requester's approved devices; no messages to other members.
        devices = list(db.scalars(select(ClientDevice).where(ClientDevice.account_id == auth[0].id, ClientDevice.status == "approved")))
        sent = 0
        try:
            for device in devices:
                sub = db.get(PushSubscription, device.id)
                if sub and config.get(sub.provider):
                    (notifier or deliver)(sub.provider, cipher.decrypt(sub.token.encode()).decode(), "0" * 32, uuid.uuid4().hex, config)
                    sent += 1
        except (OSError, httpx.HTTPError, GoogleAuthError, jwt.PyJWTError, ValueError, TypeError):
            raise HTTPException(502, "Push test failed; check provider credentials and device registration")
        return {"sent": sent}

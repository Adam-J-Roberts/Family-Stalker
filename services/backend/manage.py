"""Local administrator recovery; never manages household decryption keys."""
import argparse
import getpass
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from app import Account, HASHER, LoginSession, create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap-token", "device-bootstrap-token", "reset-owner-password", "cleanup", "reset-encryption"])
    args = parser.parse_args()
    directory = Path(os.environ.get("STALKER_DATA_DIR", "/data"))
    if args.command in ("bootstrap-token", "device-bootstrap-token"):
        path = directory / args.command
        if not path.exists():
            parser.exit(1, "No setup token: server has not started, or setup is already complete.\n")
        print(path.read_text().strip())
        return
    if args.command == "cleanup":
        app = create_app(mail_worker=False)
        app.state.initialize()
        app.state.maintenance()
        print("Expired records cleaned and pending delivery processed.")
        return
    if args.command == "reset-encryption":
        if input("This deletes ALL encrypted household data and device access. Type DELETE ENCRYPTED DATA: ") != "DELETE ENCRYPTED DATA":
            parser.exit(1, "Nothing changed.\n")
        import secrets
        from data_service import ClientDevice, EncryptedRecord, PushDelivery, PushSubscription, RosterRevision, ServiceState, audit
        from app import digest
        app = create_app(mail_worker=False)
        app.state.initialize()
        with Session(app.state.engine) as db:
            state = db.execute(select(ServiceState).where(ServiceState.id == 1).with_for_update()).scalar_one()
            db.query(PushDelivery).delete()
            db.query(PushSubscription).delete()
            db.query(EncryptedRecord).delete(synchronize_session=False)
            db.query(RosterRevision).delete()
            db.query(ClientDevice).delete()
            token = secrets.token_urlsafe(32)
            path = directory / "device-bootstrap-token"
            path.unlink(missing_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd,"w") as output:
                output.write(token)
            state.household_id, state.revision, state.anchor, state.bootstrap_hash = secrets.token_hex(16), 0, None, digest(token)
            owner = db.scalar(select(Account).where(Account.role == "admin"))
            audit(db, "encryption.reset", owner.id if owner else "local")
            db.commit()
        print("Encrypted data and devices deleted. Re-enroll the first device with the local device bootstrap token. Accounts and mail settings were preserved.")
        return
    password = getpass.getpass("New administrator password (15–128 characters): ")
    if not 15 <= len(password) <= 128 or password != getpass.getpass("Confirm password: "):
        parser.exit(1, "Password length or confirmation not accepted.\n")
    app = create_app(mail_worker=False)
    with Session(app.state.engine) as db:
        owner = db.scalar(select(Account).where(Account.role == "admin"))
        if not owner:
            parser.exit(1, "Complete setup first.\n")
        owner.password = HASHER.hash(password)
        db.query(LoginSession).filter_by(account_id=owner.id).delete()
        db.commit()
    print("Administrator password changed and existing sessions revoked. No device or encryption access was granted.")


if __name__ == "__main__":
    main()

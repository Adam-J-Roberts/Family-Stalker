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
    parser.add_argument("command", choices=["bootstrap-token", "reset-owner-password"])
    args = parser.parse_args()
    directory = Path(os.environ.get("STALKER_DATA_DIR", "/data"))
    if args.command == "bootstrap-token":
        path = directory / "bootstrap-token"
        if not path.exists():
            parser.exit(1, "No setup token: server has not started, or setup is already complete.\n")
        print(path.read_text().strip())
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

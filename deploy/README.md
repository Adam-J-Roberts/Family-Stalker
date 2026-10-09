# Deployment

This image runs the persistent setup website and account/email services. Compose also runs PostgreSQL; both services use durable volumes. Location sharing and mobile clients are not implemented.

## Publishing

On a reviewed merge to `main`, the Container workflow runs SQLite and PostgreSQL checks, validates Compose, builds and smoke-tests a non-root read-only container, then publishes:

- `ghcr.io/adam-j-roberts/family-stalker:latest`
- `ghcr.io/adam-j-roberts/family-stalker:sha-<full-commit-sha>`

Pull requests validate without publishing. Manual workflow runs publish only from `main`. GitHub's short-lived workflow token supplies registry authentication.

For anonymous pulls, set the GitHub `family-stalker` package visibility to **Public** in its package settings. Public repository visibility does not automatically change package visibility. Publishing currently targets Linux AMD64; ARM64 and release tags remain future work. Base-image digest pinning and automated dependency updates also remain release-hardening work.

## Prepare NJServer

After merging this milestone and the publish workflow succeeding, save `compose.yaml` and `prepare.py` from this directory in `/opt/docker/family-stalker`. Run there:

```bash
python3 prepare.py --url https://stalker.roberts.eco
# Creates a private .env with a random database password; never overwrites it.
docker compose pull
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8186/healthz
```

Expected health: `{"status":"ok","stage":"setup","configured":false}` until setup completes. Both containers should become healthy.

The application port defaults to localhost:8186. Put your HTTPS reverse proxy in front of it, forwarding the original `Host` header. Set the browser domain to the exact `STALKER_PUBLIC_URL`; mismatched Host or Origin is rejected. The application intentionally ignores forwarded IP headers. A proxy running in another container cannot reach the host's loopback: use an appropriately restricted host bind with `prepare.py --bind <NJServer-LAN-IP>` and the matching upstream address. Do not publish PostgreSQL or forward plain HTTP directly to the internet. The reverse proxy must obtain and renew the domain's TLS certificate.

For isolated LAN testing only, use `--url http://<NJServer-LAN-IP>:8186 --bind <NJServer-LAN-IP> --allow-http`. This explicitly disables secure-only cookies and transmits credentials without HTTPS. Switch to HTTPS before normal use.

## First-run website

1. Open the exact configured URL on your phone/computer.
2. Retrieve the local token:

   ```bash
   docker compose exec stalker python manage.py bootstrap-token
   ```

3. Enter the token, household name, owner email/username and a password of at least 15 characters. Setup closes permanently and the token file is removed.
4. Sign in. Configure your provider's SMTP hostname, port, TLS/STARTTLS, username, password and sender. Save, send a test to yourself, then confirm the administrator email.
5. Invite a test member. Their email link lets them choose credentials and verify ownership. Alternatively, the sign-in page lets them request a fresh link using their invited email. Uninvited emails never create accounts.
6. Run the [acceptance checklist](../docs/server-setup.md), including revocation and restart persistence. Email confirmation grants no encrypted device access; pairing is still gated.

SMTP credentials and queued email bodies are encrypted with `/data/server.key`. Protect Docker access and backups: a host operator with both database and key can decrypt them. Provider app passwords may be required. The setup does not request Apple/Google push secrets until their services exist.

## Updates and recovery

```bash
docker compose pull
docker compose up -d
```

`latest` is the development channel. To pin an image, add `STALKER_TAG=sha-<full-commit-sha>` to `.env`. Roll back only to an image compatible with the database schema; the backend refuses unsupported versions. Do not revert to the old health-only Compose file after creating persistent setup data.

A container restart/update preserves both volumes. `docker compose down` preserves them; **`docker compose down -v` destroys them**. Keep `.env` private and out of Git. Do not change its database password after initialization without also changing the PostgreSQL role password.

Recover a forgotten owner password through local Docker access:

```bash
docker compose exec stalker python manage.py reset-owner-password
```

This prompts without echo, revokes existing owner sessions and does not approve devices or recover household encryption keys.

## Backup and isolated restore

Back up the database **and** server-data volume together. Restoring only the database loses SMTP/outbox decryption. Protect `.env` as well. Take the application offline briefly to prevent writes while making the pair:

```bash
umask 077
mkdir -p backup
docker compose stop stalker
docker compose exec -T database pg_dump -U stalker -d stalker > backup/database.sql
docker compose cp --archive stalker:/data backup/server-data
cp .env backup/deployment.env
docker compose start stalker
```

Check every command succeeds and keep the backup encrypted/off the server. Test restoration into an isolated, empty deployment using a different Compose project, bind port and private PUBLIC_URL. Do not run these restore commands on your current database:

```bash
# Use a separate directory containing compose.yaml and a prepared private .env.
docker compose up -d database
# Wait until the database is healthy before importing.
docker compose exec -T database psql -v ON_ERROR_STOP=1 -U stalker -d stalker < backup/database.sql
docker compose create stalker
docker compose cp --archive backup/server-data/. stalker:/data
docker compose up -d stalker
```

Archived copying preserves the server volume's UID/GID (10001) and private permissions. Copy the key before starting the app; it fails closed if a schema exists but the key is missing. Keep restored SMTP from delivering old pending invitations during a restore test (use an isolated network/test mail server or clear pending delivery state in the disposable database). Confirm login/settings survive, then test delivery with your test account. Automated backups and schema upgrades are separate future work.

## Build locally

From the repository root:

```bash
docker build -t family-stalker:local .
STALKER_PUBLIC_URL=https://stalker.example.invalid STALKER_DB_PASSWORD=synthetic-build-only \
  docker compose -f deploy/compose.yaml config --quiet
```

For actual deployment use `prepare.py` to generate unique secrets. Never reuse the synthetic example password.

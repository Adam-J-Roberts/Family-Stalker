# Deployment

This image runs the persistent setup website and account/email services. Compose also runs PostgreSQL; both services use durable volumes. It also serves the encrypted browser map and data relay. Native mobile background-tracking clients are not implemented.

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

### Optional configured setup token

Set `STALKER_SETUP_TOKEN` in the Compose environment to choose the first-run setup token, for example `STALKER_SETUP_TOKEN: "family-test"` for an isolated test. Omit it or leave it empty to keep the generated token. Use a unique random value for normal deployments. The value must contain 8–256 characters without surrounding whitespace.

An explicitly configured value replaces the token on restart **only while setup is unfinished**, including an existing unclaimed deployment. Once the household/administrator is created, setup remains closed regardless of this variable. Remove it from your configuration after setup. It does not replace the separate encrypted-device bootstrap token.

For local-first setup, bind the application port to the server's LAN address and restrict access with your firewall. Do not forward it publicly until setup is complete. Docker/reverse proxies can mask the original client IP, so the application does not claim that a private source IP proves a request originated locally. Later server administration remains available to authenticated administrators at the configured URL.


1. Open the exact configured URL on your phone/computer.
2. Retrieve the local token:

   ```bash
   docker compose exec stalker python manage.py bootstrap-token
   ```

3. Enter the token, household name, owner email/username and a password of at least 15 characters. Setup closes permanently and the token file is removed.
4. Sign in. Configure your provider's SMTP hostname, port, TLS/STARTTLS, username, password and sender. Save, send a test to yourself, then confirm the administrator email.
5. Invite a test member. Their email link lets them choose credentials and verify ownership. Alternatively, the sign-in page lets them request a fresh link using their invited email. Uninvited emails never create accounts.
6. Run the [acceptance checklist](../docs/server-setup.md), including revocation and restart persistence. Email confirmation grants no encrypted device access. Open Household map, create the browser vault, then retrieve `docker compose exec stalker python manage.py device-bootstrap-token` to approve the first device. Invite another test browser, compare its fingerprint and the household root through a separate trusted channel, then approve it from the existing device.

SMTP credentials and queued email bodies are encrypted with `/data/server.key`. Protect Docker access and backups: a host operator with both database and key can decrypt them. Provider app passwords may be required. The setup does not request Apple/Google push secrets until their services exist.

## Optional Google Maps

The browser defaults to OpenStreetMap without a Google key. To select Google Maps, add this under the **stalker** service's `environment` in your Compose/Portainer YAML:

```yaml
      STALKER_GOOGLE_MAPS_API_KEY: "YOUR_GOOGLE_MAPS_API_KEY"
```

The supplied Compose file also accepts `STALKER_GOOGLE_MAPS_API_KEY` from `.env`. Leave it blank (`""`) or omit it to use OpenStreetMap. Recreate the application container after changing this setting; existing browser vaults and encrypted data remain valid.

Enable **Maps JavaScript API** in a Google Cloud project with billing enabled. Restrict the key to **Maps JavaScript API** and HTTP website referrers such as `https://stalker.roberts.eco/*` (add each actual deployment domain). This is a browser key and is visible to signed-in users; apply domain/API restrictions and appropriate quotas. Google billing applies above its current free allowance; OpenStreetMap needs no API key and follows its public tile usage policy.

After unlocking an approved device, select **Load Google Maps** or **Load OpenStreetMap tiles**. Neither provider is contacted before that choice. The selected provider receives the viewed region and normal browser network metadata. Google gets the map coordinates required to display it; household records still decrypt in the browser. Names/photos are DOM overlays rather than data submitted to a Google location service. An unsuccessful Google load displays an error and offers **Use OpenStreetMap instead**. Refreshes update existing map markers rather than constructing a new Google map. Locking and reopening, or leaving and returning to the map, requires a new explicit load and may count as another billable Google map load.

Provider references: [Google setup](https://developers.google.com/maps/documentation/javascript/get-api-key), [Google pricing](https://developers.google.com/maps/billing-and-pricing/pricing), [OpenStreetMap tile policy](https://operations.osmfoundation.org/policies/tiles/).

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

## Full-server acceptance

Read [server protocol](../docs/server-protocol.md) before real location use. Add an approved second browser, publish **synthetic** locations from the first, and verify both display the decrypted update. A pending browser must not read it. Test saved places, profiles, history, pause/resume, and member/device revocation. New devices receive future updates; use the reshare-places button after approval. A member revoked through account administration must also be removed from the signed roster through the map's reconciliation button before further publication.

In Server settings, history defaults to 14 days and can be reduced. Place/profile state persists. The cleanup button and `docker compose exec stalker python manage.py cleanup` trigger expiry processing. `STALKER_STORAGE_QUOTA_MIB` optionally sets the ciphertext budget (default 512); total PostgreSQL usage includes indexes/WAL and may be larger. Keep backups on their own 14-day expiry policy if you want that cap for all retained GPS copies.

Optional APNs configuration needs your Apple developer team/key IDs, .p8 key, native bundle ID and sandbox/production selection. Optional FCM needs a Firebase service-account JSON. These are encrypted at rest and never returned in settings responses. Neither provider receives readable GPS/place data. Real delivery needs a native app with a registered token; the browser's encrypted event test validates server flow without pretending to be native push.

Schema 1→2 is an additive migration under the initial version guard; it preserves accounts/mail settings and creates the relay/device tables. Back up both volumes before upgrading. Older images cannot run against schema 2; restore their matching database backup to roll back. Schema migration supports a single application worker/replica only.

If every trusted device is lost, first seek approval from another trusted household device. Otherwise the local `reset-encryption` command requires typed destructive confirmation, deletes all encrypted data/device state, and starts a new household cryptographic identity. It preserves account/mail administration and cannot recover past locations. Run it only after a backup, with no concurrent browser/client activity; this is a last-resort local recovery tool, not email recovery.

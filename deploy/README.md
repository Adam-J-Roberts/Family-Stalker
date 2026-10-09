# Deployment

The first image is a health-only development scaffold. It accepts no location writes, has no accounts/database, and provides no encryption or setup UI. Its HTTP server is temporary packaging infrastructure, not the future production API. Keep it private; no public exposure is needed for this test.

## Publishing

Merge the container PR into `main`. The Container workflow tests, validates Compose, builds and smoke-tests an unprivileged read-only container, then publishes:

- `ghcr.io/adam-j-roberts/family-stalker:latest`
- `ghcr.io/adam-j-roberts/family-stalker:sha-<full-commit-sha>`

Pull requests only validate and never publish. Manual workflow runs publish only when run against `main`. No separate registry secret is required: the publisher uses the workflow's short-lived GitHub token with `packages: write`.

After the first successful publish, open the account's **Packages** tab, select `family-stalker`, and use **Package settings** to change visibility to **Public** for anonymous pulls. Repository visibility does not automatically make a newly published container public. If this step is skipped, pulls may report unauthorized or denied.

Currently builds Linux AMD64 for NJServer. ARM64 publishing and numbered release tags are future additions. The Python base tag is refreshed during builds rather than digest-pinned; digest pinning and update automation remain release-hardening work.

## Run on NJServer

Save [compose.yaml](compose.yaml) as `/opt/docker/family-stalker/compose.yaml`, then from that directory run:

```bash
docker compose pull
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8186/healthz
```

Expected response: `{"status": "ok", "stage": "scaffold"}`. A healthy container only proves the packaging scaffold works, not that location sharing is implemented.

Port 8186 defaults to localhost on NJServer. For a deliberate LAN test, set `STALKER_BIND_ADDRESS` to NJServer's LAN IP in a local `.env` file. Check the port is free first; change `STALKER_PORT` if necessary. Do not forward this HTTP port to the internet.

Update with `docker compose pull` followed by `docker compose up -d`. To pin or roll back, set `STALKER_TAG=sha-<full-commit-sha>` in `.env` to a previously published image tag, then repeat those commands. `latest` follows reviewed changes on `main`; it is a development channel today.

No persistent volume or database is needed for this scaffold. Those will be added with the real backend; backup/restore and migration instructions must accompany them.

## Build locally

From the repository root:

```bash
docker build -t family-stalker:local .
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  -p 127.0.0.1:8186:8080 family-stalker:local
```

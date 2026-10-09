# Server setup: scope and acceptance

This milestone implements the server prerequisites and onboarding web experience. It does not claim to implement the full location-sharing product.

## Implemented

- FastAPI/Uvicorn serving local CSS/JavaScript, a setup wizard, login, mail settings, and household-member administration.
- PostgreSQL initialization with schema version 1 and a fail-closed version guard. Only one application replica/worker is supported. Future changes need explicit reviewed migrations; `create_all` is only the initial schema creator.
- One-time local bootstrap token; authenticated creation of the first owner; setup permanently locks afterward.
- Argon2id password hashes, hashed random session IDs, 12-hour sessions, HttpOnly/SameSite cookies, secure cookies on HTTPS, origin/Host checks and per-session CSRF protection.
- SMTP STARTTLS or TLS with certificate verification; credentials encrypted with a separate persistent server key. Settings responses omit passwords. Blank password preserves the saved value.
- Test mail, pending invited accounts, expiring single-use confirmation, requesting a new link without the original invitation, generic public responses, encrypted durable outbox with retry/backoff and a background delivery worker.
- Owner email confirmation never resets its password. Email ownership and cryptographic device approval remain separate.
- Account listing and revocation, session invalidation, pending-device revocation, and local owner-password recovery.
- Writable database/server-secret volumes with a read-only, non-root application container; healthcheck queries the database.

## Deliberately gated

There is no location ingestion, E2EE implementation, device registration/approval, map, profile photo upload, saved places, APNs/FCM registration, or mobile app. Device records are reserved for the future pairing service. Their status endpoint explicitly reports pairing unavailable. No administration setting can bypass this gate.

Profile images and shared place data require the approved client encryption design. The setup site handles household name, account email, and username as server-visible administrative metadata; it is not a browser location client.

## Acceptance on NJServer

1. Start Compose; both containers become healthy. Open the configured URL from a browser.
2. Retrieve the token through Docker and create the household. Refresh: setup must now show sign-in, and the token file must be gone.
3. Sign in, configure provider SMTP settings, send a test, and verify it arrives. Confirm the owner email from the received link.
4. Invite a synthetic/test member, open their link, create credentials, and sign in as that member. They must not see administrator settings or location data.
5. Request a replacement invitation by email; the previous unused link must stop working. Each successful confirmation link must be unusable a second time.
6. Revoke a member; their existing session and subsequent login must stop working.
7. Restart/recreate the application container without deleting volumes. Household, accounts, mail settings, and server key must survive.
8. Exercise the documented backup/restore on an isolated deployment, then confirm mail credentials still decrypt and accounts still work.

Use real email delivery only for this explicitly requested test. Synthetic test fixtures do not prove that your provider's TLS/authentication settings work.

## Limits and operational controls

Email/login rate limits apply per direct client IP and persist across restarts. Behind a reverse proxy this intentionally groups requests under the proxy IP because untrusted forwarded headers are ignored. A later trusted-proxy design can preserve client IPs safely. Global session/metadata confidentiality depends on HTTPS and protection of Docker access and backups.

The SMTP storage key protects a database-only copy, not a compromised host that also reads the key. It is not household end-to-end encryption. Account recovery through the local CLI restores administrative login only.

The HTTP development opt-in permits credentials on an unencrypted connection. Use it only for isolated private testing; use HTTPS through your reverse proxy for normal operation. PUBLIC_URL is fixed in `.env` to prevent hostile Host headers from rewriting invitations. Change it there and recreate the service when moving to a domain.

At present an administrator cannot delete the owner account or promote new administrators through the API. Automatic backup scheduling, MFA, production vulnerability review, schema upgrades, and the broader release security gate remain later milestones.

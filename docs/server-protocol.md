# Server and browser protocol v1

This implements a runnable server and reference browser client. Native iOS/Android background location and notification presentation are separate clients, not features Docker can collect on their behalf. Use synthetic/test data while the protocol and native clients undergo review.

## Trust and cryptography

Each device generates independent Ed25519 signing and X25519 encryption keypairs through libsodium. Each payload is separately encrypted for each approved device using libsodium sealed boxes (X25519/XSalsa20-Poly1305). The Ed25519 signature authenticates the complete ciphertext envelope and its routing/context metadata. No household private key is uploaded. This is a versioned per-recipient format, not an MLS implementation or custom ratchet.

Sealed boxes alone do not authenticate the sender; our separately verified signatures do. Recipient private keys are long-lived: **no recipient forward-secrecy guarantee** is made. A compromised recipient key may decrypt previously obtained ciphertext. The active database expires history; it cannot erase copies held by recipients, network observers or backups.

The browser encrypts its local vault with WebCrypto AES-256-GCM and a separate passphrase derived through PBKDF2-SHA256 (600,000 iterations, random 16-byte salt, random 12-byte IV, origin/account associated data). It requires HTTPS, except localhost testing. Signing secrets, encryption secrets, device credential and pinned membership state remain in that encrypted local vault. Locking/sign-out drops in-memory references; JavaScript cannot promise physical memory erasure. A server serving malicious JavaScript can steal keys/plaintext after browser unlock. A trusted native app is required for the stronger malicious-server boundary.

Primary references:

- https://doc.libsodium.org/public-key_cryptography/sealed_boxes
- https://doc.libsodium.org/public-key_cryptography/public-key_signatures
- https://github.com/jedisct1/libsodium.js
- https://pynacl.readthedocs.io/en/latest/public/

## Accounts and devices

Accounts are invited by the owner, verified through expiring email challenges and authenticated separately from device keys. SMTP and push-provider secrets are encrypted with the server's separate storage key. This storage key is not a household decryption key.

Device enrollment requires an active, verified account and proof of possession of its Ed25519 key. The server issues an opaque credential once and stores only its SHA256 hash. Native clients should keep credentials/private keys in platform-protected storage. Device credentials remain valid until revocation; account access tokens expire after 12 hours.

The first device must additionally supply the local `device-bootstrap-token` from Docker. Its signing key becomes the household trust anchor. Later devices compare their full registration fingerprint with an existing trusted device and pin the household root fingerprint through a separate trusted channel. Do not approve a fingerprint solely because a server displays it in both places.

An already-approved device signs the next roster revision. Any trusted member may approve a device belonging to an already-invited, verified member, including helping an owner recover onto a new device. Members may remove their own devices; only an owner device may remove other members' devices. Server account administration alone cannot manufacture these signatures.

The server serializes roster updates, publication and administrative revocation through a database row lock. A revoked account/device immediately loses server API access. If an account is administratively revoked before a signed roster change, publication fails closed until a trusted owner applies that removal to encryption membership. The map presents an explicit reconciliation button. Pending device registration does not change the current encryption recipients.

After approval, a new device receives future records. It does not automatically acquire keys to past history. A trusted client can reshare saved places for the new roster; users republish their profiles and fresh locations. Root/roster identities are retained as authentication metadata, not subject to GPS history expiry.

If all trusted devices/vault passphrases are lost, there is no email-based cryptographic recovery. The local `reset-encryption` CLI deliberately destroys ciphertext/device state, assigns a new household identity and requires fresh bootstrap. Back up before running it. Other members' already-approved devices can normally help enroll replacement devices without a reset.

## Canonical signatures and membership

All protocol metadata keys are ASCII and all numeric metadata are integer values. Canonical bytes are UTF-8 JSON with object keys recursively sorted, no insignificant whitespace, unescaped Unicode, and array order preserved. Base64 is standard padded Base64, not URL-safe Base64. IDs are 32 lowercase hexadecimal characters. Native clients must include nullable fields such as `replaces` explicitly. Sign the validated body, not raw HTTP bytes.

Registration signature body:

```json
{"domain":"family-stalker.device.v1","household":"<household-id>","id":"<device-id>","account_id":"<account-id>","signing_key":"<base64-32-bytes>","box_key":"<base64-32-bytes>"}
```

Roster body fields: `domain="family-stalker.roster.v1"`, household ID, consecutive `revision`, previous signed-envelope SHA256 `previous` (empty for genesis), `signer` device ID, integer UTC `issued_at` seconds, and the complete sorted `devices` array of exact IDs/account IDs/public keys. Sign that body and send `{body, signature, bootstrap_token}` (`bootstrap_token` only at genesis).

Clients verify every roster signature against the previous trusted roster, the pinned genesis key, consecutive revision/hash chain, sorted unique identities, and immutable keys for an existing device ID. They persist the latest revision/hash and reject rollback or a different chain at that revision. An actively malicious server can withhold updates or show isolated signed forks; cross-device gossip/freshness proofs are not implemented. Offline clients must synchronize before publication. Server-side refusal protects against obsolete recipient sets on an honest deployment.

## Encrypted records

HTTP upload is `{body, signature}`. Body fields:

| Field | Meaning |
| --- | --- |
| `domain` | Exactly `family-stalker.record.v1` |
| `household`, `revision` | Pinned household and current trusted roster revision |
| `id`, `sender`, `sequence` | Unique record ID, registered sender device and increasing device counter |
| `kind` | `location`, `event`, `place`, or `profile` |
| `entity_id` | Account ID for location/profile; opaque random ID for place/event |
| `operation` | `upsert`; persistent place/profile deletion uses `delete` |
| `replaces` | Current state record ID when editing place/profile; `null` for new state and history |
| `captured_at` | Original capture/edit time in UTC milliseconds, never upload time |
| `recipients` | Sorted `{device_id, box}` array for every currently approved device |

Encrypted plaintext contains `domain="family-stalker.payload.v1"`, all outer metadata except `domain`/`recipients`, and `data`. Clients must verify the outer signature using the roster valid at that revision, decrypt their sealed box, compare every inner context field to the outer body, then validate the data for its kind. The server cannot authenticate sealed-box contents without recipient private keys; syntactically valid Base64 is not proof that a malicious client encrypted it correctly.

Reference `data` examples:

- Location: `{lat, lon, accuracy}`. The client validates finite values/ranges, labels fixes older than five minutes stale, and displays original capture time.
- Place: `{name, lat, lon, radius}`. Names/coordinates/radius are encrypted; the opaque ID is server-visible.
- Profile: `{name, photo}`; `photo` is a small JPEG data URL or null. The browser resizes uploads to 96×96 before encryption.
- Event: `{type, place_id, message}`. The reference browser has an explicitly synthetic arrival button. Actual geofence detection/debounce belongs in native clients.

Same ID/same envelope is idempotent. A changed envelope at that ID or a reused/lower sequence is rejected. Device sequence high-water marks persist after history deletion. Older queued locations remain history but never replace a newer latest fix. Place/profile writes use compare-and-swap through `replaces`, preventing an offline edit silently overwriting newer state. Persistent deletion keeps an encrypted tombstone until replaced.

## Retention, quotas and privacy

Default history retention is 14 days, configurable downward to 1–14 days. Location/event expiry is measured from **capture**, including offline uploads. Future timestamps beyond five minutes and captures outside retention are rejected. Reads hide expired records immediately, even before cleanup. A healthy worker runs physical cleanup periodically (five-minute cadence; provider/network delays or outages can postpone the sweep); startup/restored data receive the same read-time expiry rules. Manual cleanup is available in the UI/CLI.

Current places/profiles persist until changed/deleted. Old replaced ciphertext is deleted. Signing/device/roster metadata remain to validate retained records and prevent replay. Security activity is retained for 14 days. Expired sessions are cleaned. Separate Docker/PostgreSQL backups, replicas, browser memory and previously downloaded recipient copies have separate retention; deleting database rows does not securely erase disk blocks or PostgreSQL WAL. Operators must configure and test backup expiry.

Default ciphertext quota is 512 MiB (`STALKER_STORAGE_QUOTA_MIB`); it is a payload quota, not total PostgreSQL disk usage. Limits: 32 approved devices, 8 non-revoked devices per account, 64 pending/approved devices total, 64 current place/profile entities, 120 history updates per device/minute, 1 MiB HTTP upload, sealed payload at most 2 KiB for location/event/place and 16 KiB for profile per recipient. These bound response/memory/storage use; they are prototype household limits.

A member can delete their own stored GPS/event history. This preserves saved places/profiles and other members' history. Clients must clear unsent queues when deleting history or pausing sharing. Account/device revocation cannot retract previously downloaded data. The server still sees accounts, device identities, routing, sizes and timestamps. No coordinates/place names are written to application access logs; access logging is disabled.

## API surface

| Endpoint | Access and purpose |
| --- | --- |
| `POST /api/login` | Account login. Native body adds `native:true` and header `X-Stalker-Client:native`; response includes a 12-hour account bearer token. Browser uses HttpOnly cookie/CSRF. |
| `/api/enrollment/request`, `/api/enrollment/verify` | Invited account confirmation/replacement link; native header supported. |
| `GET /api/household`, `GET /api/devices` | Active account; public household/device identities. Unverified accounts see only their own devices. |
| `POST /api/devices/register` | Verified account, registration signature; returns one-time device credential. |
| `GET /api/device`, `GET /api/roster?after=N` | Device bearer token; pending devices can inspect public pairing state. Roster chain pages hold at most 100 revisions. |
| `POST /api/roster` | Device bearer token plus trusted signature/local genesis token. |
| `POST /api/records`, `GET /api/state` | Approved device bearer token; upload or current recipient-authorized ciphertext. |
| `GET /api/records?kind=location&limit=100&cursor=...` | Approved device; paged history. Event history uses `kind=event`. Compound cursor handles equal capture timestamps. |
| `GET /api/records/{id}` | Approved recipient device; missing/expired/not-addressed records return 404. |
| `DELETE /api/records/mine` | Approved device; delete its account's location/event history. |
| `PUT /api/sharing` | Approved device; `{enabled:false}` pauses publication and hides that device's latest location. |
| `/api/push/subscription` | Approved device PUT/DELETE; encrypted-at-rest provider token. |
| `/api/storage`, `/api/storage/retention`, `/api/storage/cleanup`, `/api/audit` | Owner account session/token only. |
| `/api/push/config`, `POST /api/push/test` | Owner configures provider credentials or tests only their own registered native devices. |

All browser mutations require exact configured Origin, JSON, size limits and session CSRF. Native bearer mutations accept absent Origin; a supplied wrong Origin is rejected. No CORS sharing is enabled. Native account and device bearer tokens are distinct. There is no plaintext GPS endpoint and no MQTT broker in this milestone. HTTPS polling uses the same authenticated store; a future MQTT adapter must enforce identical signatures, recipient rules and expiry, not write around them.

## Push and maps

APNs uses provider-token ES256 authentication and HTTP/2. FCM uses Google's maintained service-account OAuth library and HTTP v1. Endpoints are fixed to Apple/Google; custom credential token URLs are rejected. Generic push contains an opaque record ID, never coordinates, profile names or places. A native client fetches/decrypts the event and chooses the presentation. Durable deliveries retry with backoff, expire after at most one hour, and are removed on recipient revocation or provider-reported invalid registration. Delivery can still duplicate across a crash; clients must deduplicate record IDs. OS delivery is not guaranteed.

The browser map uses locally bundled Leaflet. OpenStreetMap tiles are **opt-in**, with visible attribution, browser caching and an origin-only tile Referer. Tile requests reveal viewed regions and deployment origin to that provider. No tile prefetch/offline scraping is implemented. Tile policy: https://operations.osmfoundation.org/policies/tiles/.

Real APNs/FCM/email delivery, iOS signing/background behavior, independent security review and native cross-platform integration remain acceptance work. The automated suite uses synthetic data and mock push/email delivery only.

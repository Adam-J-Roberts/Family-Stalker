# Architecture direction

## Trust boundaries

The native client collects location and handles cryptography. The backend authenticates accounts and devices, enforces authorization, stores ciphertext, and routes updates. The setup website configures the deployment; it does not decrypt household data.

A household administrator's app is a trusted recipient. The server process is not. Account roles and group encryption membership are distinct mechanisms.

## Components

| Component | Responsibilities | Sensitive material |
| --- | --- | --- |
| iOS client | UI, collection, geofences, offline queue, encryption, decryption | Device secrets and authorized plaintext |
| Android client (later) | Same protocol with native platform location handling | Device secrets and authorized plaintext |
| API service | Account/device authentication, invitations, authorization, ciphertext routing | Email, device public identities, routing metadata |
| Database | Account state, devices, encrypted records, delivery state | No household private encryption keys or plaintext location payloads |
| Push worker | Send authorized notifications through APNs/FCM | Provider credentials, device tokens, encrypted or generic payloads |
| Setup website | Initial setup, mail/provider settings, operational status | Admin session; no household decryption keys |

## Data flow

1. The OS supplies a location observation or region event to the phone.
2. The client applies accuracy, freshness, sharing-state, and event rules.
3. The client constructs a versioned payload, authenticates it, and encrypts for the approved household devices using the selected protocol.
4. It uploads over HTTPS using its device session.
5. The backend checks device status, household routing permission, size limits, and idempotency before storing ciphertext.
6. Recipient apps retrieve and authenticate/decrypt the record and update their local map/state.
7. For remote alerts, the backend routes an encrypted event or generic notification through push. Reliable presentation while locked must be tested; silent pushes must not be assumed guaranteed.

APNs/FCM are delivery dependencies, not location databases. Provider secrets remain server-side. Never place coordinates or place names in plaintext push payloads.

## Conceptual records

- Household: deployment identity and membership policy.
- Account: stable ID, email, role, pending/active/revoked state.
- Device: public identity, account association, pending/approved/revoked status, notification registration.
- Invitation/verification challenge: account/request binding, hashed secret, expiry, attempt state.
- Encrypted record: opaque payload, protocol version, authorized routing metadata and receipt time.
- Client-local profile/location/place/event: encrypted before upload where sensitive.

Actual wire fields, signatures, replay protections, key epochs, and membership transitions must be specified after the protocol/library selection. Do not write custom group cryptography based on these conceptual records.

## Deployment

The setup milestone implements one FastAPI/Uvicorn API with a background email worker, PostgreSQL and separate database/server-secret volumes, behind HTTPS. Only one application replica/worker is supported. Location routing remains gated. Prefer compatibility with an existing reverse proxy while documenting a simple standalone option. The database must not be exposed publicly.

Email and push configuration need guided setup and diagnostics. Docker packaging alone does not eliminate those external setup requirements. TLS, backups, schema migrations, health checks, and upgrades are deliverables, not assumed behavior.

## Browser map

A browser map requires a member's keys and authorization. JavaScript supplied by a compromised server can steal keys or plaintext when used, even if the database stores only ciphertext. Keep it out of the first prototype and resolve that threat explicitly before implementation.

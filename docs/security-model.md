# Security model (draft)

For the implemented server/browser prototype, read [protocol and explicit limits](server-protocol.md). The browser cannot meet the actively malicious-server target while using JavaScript delivered by that server. Native clients and independent review remain prerequisites for that stronger claim.

## Target claim

A network observer or attacker who obtains the server database should not be able to decrypt location contents. An actively malicious server should not be able to silently enroll a new decrypting device. These are requirements to validate, not current guarantees.

An approved recipient, compromised phone, or malicious client release can expose plaintext available to that device. Previously received information cannot be remotely taken back. Metadata, availability, and content confidentiality need separate treatment.

## Assets

Coordinates, history, named places, arrival/departure events, profile photos, device private keys, recovery material, account sessions, provider credentials, and membership decisions.

## Threats and required controls

| Threat | Required control | Verification |
| --- | --- | --- |
| Network interception | HTTPS with normal certificate validation; end-to-end authenticated encryption | Reject invalid certificates; inspect traffic for plaintext |
| Stolen database/backups | Household payloads encrypted on clients; no private household keys on server | Inspect representative DB, logs, and backups |
| Server substitutes keys/adds member | Trusted device approval bound to exact device identity and household, authenticated enrollment, optional QR verification | Simulate key substitution and unauthorized enrollment |
| Removed member receives future data | Revoke sessions/routing and change encryption membership/keys | Former keys cannot decrypt subsequent records |
| Forged/replayed location | Protocol sender authentication and replay handling | Tamper, duplicate, reorder, and cross-household tests |
| API access-control bug | Deny by default; validate object and operation access on every request | Pending/revoked/wrong-account authorization matrix |
| Stolen email account | Email verifies account only; it cannot independently obtain household keys | Recovery cannot bypass device approval |
| Invitation abuse | Strong single-use expiring secrets, hashing, rate/attempt limits | Reuse, expiry, guessing, account/request mismatch tests |
| Device secret theft | Platform-protected key storage with deliberate background accessibility | Locked-device/reboot tests and backup review |
| Logs, pushes, telemetry leakage | Redaction; generic/encrypted pushes; no tracking SDKs | Inspect all outbound services and error paths |
| Compromised release/dependency | Reviewed releases, constrained CI permissions, pinned dependencies where practical | Release provenance and dependency review |

## Cryptographic selection gate

Use an established protocol with a maintained implementation supporting iOS and future Android. Evaluate MLS as a candidate; its suitability is not settled. Review library maintenance, audits, licensing, platform build support, offline synchronization, authenticated device membership, key updates, replay behavior, and recovery.

Do not build a custom ratchet, casually distribute one permanent shared AES key, or treat an account password as a household encryption key. Signing a record proves origin under the key assumptions; it does not prove the reported GPS position is truthful.

Document the chosen protocol, supported versions, identity verification, initial household bootstrap, device approval, removal, recovery, and key deletion before connecting real location data. Separate encryption keys from login credentials and push credentials.

Forward secrecy and retained history interact: retaining decryption capability for history changes what a later device compromise can expose. Define the retention/decryption policy explicitly rather than making blanket claims.

## Initial owner and recovery

Initial setup needs a one-time bootstrap authorization and a verifiable binding between the household and the first device. Prevent an attacker racing setup. Subsequent enrollment requires existing trusted approval.

Choose and test one recovery policy: another trusted device, user-held recovery material, or loss of encrypted history. Email resets alone must not reveal old ciphertext. If every trusted device is lost, restoration behavior must be documented.

## Metadata and external services

The backend can see IP addresses, emails, device/routing identities, timing, and payload sizes even with encryption. Map/tile providers can infer viewed regions. Push providers see delivery metadata. Minimize retention and disclose dependencies accurately.

No claim of zero metadata or protection from an approved viewer recording locations. Revocation protects future correctly encrypted records after the membership change; disconnected clients must synchronize membership before publishing queued data under obsolete keys.

## Release gate

Before public real-world use: complete the threat model, negative authorization and crypto lifecycle tests, data-leak checks, real-device validation, dependency review, signed release process, recovery/revocation exercises, and independent security assessment. Publish limitations and remediation status.

References for future design review:
- https://www.rfc-editor.org/rfc/rfc9420.html
- https://www.rfc-editor.org/rfc/rfc9750.html
- https://owasp.org/API-Security/
- https://developer.apple.com/documentation/security/using-the-keychain-to-manage-user-secrets

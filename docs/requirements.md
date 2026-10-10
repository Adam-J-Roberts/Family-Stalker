# Product requirements

## Agreed scope

- iOS first, tested on the owner's iPhone and spare iPhone; Android compatibility is a design requirement for later implementation.
- Self-hosted backend packaged for Docker Compose, with a first-run website.
- One deployment is one household. Every approved member can see all actively shared household locations and shared places.
- Enrollment requires an invited email. Knowing the hostname or verifying an uninvited email does not grant membership.
- A pending account survives loss of the original invitation email: the member can enter the server URL and email and request fresh verification.
- Profiles include stable internal ID, email, username, display name, photo, role, account status, and registered devices.
- Normal household use happens in the mobile app: map, invitations, place creation, alerts, and sharing controls.
- The map displays photo markers, capture time, accuracy, and stale/offline state. An old fix must never be represented as current.
- Phones detect arrival/departure events and send them to the backend for authorized delivery.
- End-to-end encryption is required for coordinates, location history, places, events, and sensitive profile content.
- No advertising, tracking analytics, or plaintext coordinates in logs and crash reports.

## Location behavior

- Explicit consent and a visible pause-sharing control on each device.
- Adaptive updates: reduce sampling when stationary; increase while moving. Final intervals require battery and reliability measurements on actual phones.
- Temporarily enable higher-frequency sharing only through an explicit user action.
- Queue encrypted observations while offline with original capture times. Reconnection must not overwrite a newer fix with an older queued one.
- Apply hysteresis/debounce to reduce geofence boundary noise. Store capture time separately from server receipt time.
- Pause stops new location capture/publication by the app and clears unsent location updates. Revocation has defined behavior for offline devices; it is not instantaneous while disconnected.
- Background behavior depends on OS permissions and lifecycle. Test reboot, force-quit, low power, denied/revoked permissions, and airplane mode; document observed limitations.

## Enrollment and accounts

- Owner creates a pending member through the app; backend sends an expiring verification link/code through administrator-configured email delivery.
- Verification is single-use, attempt-limited, stored hashed, and bound to the intended account and enrollment request.
- Respond generically to email lookup requests to avoid exposing household membership.
- Device enrollment is distinct from account activation. Existing trusted devices approve new devices and exchange encryption access through the selected protocol.
- A role gives administrative privileges, not an ability to bypass key approval.
- Account and device revocation are separate. Removing a member revokes all their devices and updates group keys for future data.
- Account recovery must not silently recover decryption access through email alone.

## Deferred scope

Native Android app, expiring friend links, multiple households per client, public store distribution, and third-party bridges follow the two-iPhone prototype.

Life360 publishing support is unverified. No core feature depends on an unofficial API. An eventual bridge requires a separate design and explicit disclosure that the recipient service gets the shared location.

## Decisions still open

Independent review of the prototype cryptographic format and native interoperability; native map provider; key recovery; license; and treatment of sensitive versus public profile fields.

Swift/SwiftUI for iOS, Kotlin/Compose for Android, PostgreSQL, and Docker Compose are starting directions. FastAPI/PostgreSQL and a libsodium sealed-box/Ed25519 reference format now implement the server prototype; see server-protocol.md. Native implementation and independent security review remain required.

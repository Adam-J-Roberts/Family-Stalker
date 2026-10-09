# Milestones and acceptance criteria

## 0 — Repository foundation (this change)

Requirements, component boundaries, security draft, folder ownership, and collaboration instructions. No runnable software is claimed.

## 1 — Encryption and two-device pairing spike

- Select the backend stack and maintained cross-platform cryptographic implementation.
- Bootstrap the first iPhone and approve the second using authenticated device pairing.
- Send synthetic encrypted records through a minimal Docker backend.
- Prove approved recipients can decrypt, and the server cannot decrypt content.
- Test key substitution, forgery, replay, removal, and offline membership changes.
- Record design decisions and remaining risks before enabling GPS data.

## 2 — Two-iPhone map prototype

- Install from Xcode on the owner's iPhone and spare.
- Upload encrypted observations; show photo/name markers, accuracy and original capture time.
- Pause sharing; expire/label stale fixes; reconnect without regressing latest state.
- Inspect database, logs, and network requests for plaintext leaks.

## 3 — Background location validation

- Walk/drive with screen locked and app backgrounded; measure accuracy, delays and battery impact.
- Exercise reboot, force-quit, low-power mode, permission changes, and connectivity loss.
- Record measured behavior and limitations rather than promising continuous execution.

## 4 — Places and alerts

- Create encrypted Home/School definitions and synchronize to approved phones.
- Detect entry/exit on the tracked phone, debounce, encrypt and route events.
- Test local notifications first; then full remote APNs flow with paid developer capabilities.
- Suppress duplicates; label delayed offline events with original event time.

## 5 — Adoption and deployment

- Docker Compose, migration/backup/restore instructions, guided HTTPS/email/push setup.
- Email pending accounts, fresh verification without original invite, device approval.
- Profiles, device management, removal, account deletion and chosen recovery policy.
- A new household completes onboarding without editing application code.

## 6 — Wider distribution

Independent security review and remediation, TestFlight, App Store readiness, license selection, and Android implementation. Friend links, browser map, and integrations get separate security designs.

## Owner environment checklist

- Mac with Xcode and physical iPhone(s) for build/sign/install and native behavior testing.
- NJServer development deployment with durable storage and HTTPS when exposed externally.
- Development email delivery configuration for the onboarding milestone.
- Paid Apple Developer membership when remote push/TestFlight capabilities are needed.
- No production locations or private signing keys in GitHub.

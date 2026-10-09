# Family-Stalker

An iOS-first, self-hosted household location-sharing project, with Android planned. One Docker deployment represents one household. Approved members see each other's shared locations and household places.

## Status

The server provides setup/admin and household-map web UIs, invitations, trusted-device enrollment, encrypted data receiving/storage, history, saved places/profiles, and generic APNs/FCM push routing. GPS and event history default to **14 days**; current saved places/profiles persist until changed or deleted.

See [deployment](deploy/README.md) and the [server/client protocol and security limits](docs/server-protocol.md). The reference browser generates and stores its own encrypted device keys; Docker cannot collect GPS itself. **Native iOS/Android background-tracking clients are not implemented yet.** This is a runnable prototype, with synthetic tests, not an independently audited production security claim.

## Intended experience

1. Deploy the backend with Docker Compose and complete a browser setup wizard.
2. Invite household members by email, creating pending accounts.
3. Members open an invitation or enter the server URL and their invited email in the app.
4. Email verification establishes account ownership. A trusted household device separately approves device access to encrypted data.
5. Members choose a display name, username, and map-marker photo, grant location permissions, and manage sharing in the app.

The server stores encrypted location payloads. Approved devices decrypt them. Operating the server does not automatically give access to household encryption keys.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `apps/ios/` | Swift/SwiftUI client and native background location |
| `apps/android/` | Future Kotlin/Compose client |
| `services/backend/` | Accounts, device registration, encrypted data routing, email and push |
| `services/backend/static/` | Served first-run administration website |
| `deploy/` | Docker Compose and publishing/deployment instructions |
| `docs/` | Requirements, architecture, security model, milestones |

Start with [requirements](docs/requirements.md), [architecture](docs/architecture.md), [security](docs/security-model.md), and [milestones](docs/milestones.md).

## Collaboration

Changes land through branches and pull requests for owner review. Fetch the latest repository before starting work; preserve changes made by other contributors. See [CONTRIBUTING.md](CONTRIBUTING.md).

This is intended to become open source. A license still needs to be selected; public visibility alone does not grant an open-source license.

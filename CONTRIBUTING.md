# Contributing

Fetch the latest remote state before making changes. Use a branch and a pull request; the repository owner reviews and merges. Keep changes focused and state what changed, why, and what was actually validated.

Never commit live coordinates, household emails/photos, database exports, real device identifiers, signing assets, private keys, certificates, tokens, or populated environment files. Use synthetic fixtures. Update examples when configuration changes.

For security-sensitive changes, include negative tests: wrong user/device, pending and revoked devices, expired/reused challenges, and modified/replayed encrypted records as applicable. Never replace security mechanisms with plaintext fallbacks to make a demo work.

Document native iOS tests separately from server checks. A successful server test or simulator build does not establish locked-phone reliability or battery performance.

The current foundation has no runnable application or CI. Add meaningful checks alongside the implementation rather than publishing a green check that only verifies placeholders.

Select a license before accepting third-party contributions. Until then, public source availability does not establish an open-source permission grant.

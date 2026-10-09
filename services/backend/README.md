# Backend

Reserved for account/device authentication, invitation email, ciphertext storage/routing, and push delivery. Backend language/framework is not selected yet. PostgreSQL and a combined application/worker Docker image are initial directions.

The server must not hold household private decryption keys. It still enforces authorization and protects metadata and service credentials.

# Backend

`server.py` is a standard-library Python health-only scaffold used to validate container publishing and deployment. `GET /healthz` returns a scaffold status; other paths return 404 and write methods return 405. It does not collect, persist, or relay location data. It is not the production API, and does not settle the backend framework decision.

The server must not hold household private decryption keys. It still enforces authorization and protects metadata and service credentials.

Run scaffold checks from the repository root:

```bash
python3 -m unittest discover -s services/backend -v
```

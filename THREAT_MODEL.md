# VYRNEXIS Threat Model (Current Local Implementation)

## Protected assets

- User passwords and account state.
- Access/refresh tokens and server-side session state.
- Tenant-owned incidents, intelligence entities and relationships, evidence metadata, workflows, graph bookmarks, and audit events.
- Uploaded evidence content while it is being hashed (the current database stores hashes and metadata, not the original bytes).

## Trust boundaries

1. The browser is untrusted. It receives no API tokens through JavaScript; same-origin Next.js routes manage HTTP-only cookies.
2. Next.js is a backend-for-frontend and forwards access tokens to FastAPI.
3. FastAPI is the authorization boundary. It validates token type/signature/expiry, reloads active user/session records, and applies role and organization checks.
4. SQLite is local development storage. The demo database is isolated from the original project database.

## Threats and current mitigations

| Threat | Current mitigation | Remaining work |
| --- | --- | --- |
| Anonymous access to domain data | Protected routes require bearer access tokens | Add automated endpoint inventory and rate controls |
| Caller changes tenant ID | API derives organization from the active database user; mismatched IDs return not found | Add tests for every future endpoint and object type |
| Cross-tenant relationship/object injection | Relationship endpoints validate both entity IDs in the caller's tenant; evidence case IDs are tenant-checked | Extend object-level checks as new references and mutations are added |
| Stolen/expired access token | Short access-token lifetime; session row is checked on every request | Add key rotation and operational monitoring |
| Refresh-token replay | Refresh JTI hash is single-use and replaced atomically | Add concurrent client/session lifecycle tests and user-facing session management |
| User role changed or account disabled | Current role and active state are read from the database on each request | Add a full role/permission matrix and administration workflows |
| Unsafe evidence execution | Uploaded evidence is read only for hashing and is never executed | Add isolated object storage, malware scanning, and chain-of-custody workflow |
| Oversized evidence upload | 25 MiB application read limit | Add reverse-proxy/request-body limits and streaming storage |
| Weak or missing production signing key | Production refuses absent, placeholder, or short secrets | Add secret-manager integration and key rotation procedures |

## Out of scope / not yet verified

Login rate limiting, MFA, recovery flows, CSP/security headers, SSRF controls for future connectors, PostgreSQL isolation, cloud/object storage, background workers, external provider security, penetration testing, accessibility/security review, and production deployment are incomplete. The current local setup is not a security certification or production-readiness claim.

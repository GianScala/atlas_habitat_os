# Deploying for a trusted crew

The repository can be public; the live operational workspace should be private.
ATLAS has shared state and administrative APIs. It is not a multi-tenant service.
Use one backend process, an authenticated HTTPS gateway, and a trusted crew.

1. Install Python 3.11+ and Node 22.12+. Create a new Python virtual environment
   on the destination machine; virtual environments cannot be moved between paths.
   Install `atlas_backend/requirements.txt`, then run `npm ci` and `npm run build`
   in `atlas_frontend`. Serve only `atlas_frontend/dist`, never the repository root.
2. Keep `.env`, habitat profiles, the state database and uploaded documents outside
   the served directory. Set absolute `DATABASE_PATH`, `KNOWLEDGE_DIR` and
   `HABITAT_CONFIG` paths, owned by a dedicated service user. Restrict permissions
   on these files and their backups. Use read-only habitat database credentials.
3. Set `ALLOWED_HOSTS=atlas.example.org` and
   `CORS_ORIGINS=https://atlas.example.org` using your actual private hostname.
   Run from `atlas_backend` under a process manager:

   ```sh
   .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
   ```

   Do not use `--reload`, Vite's development server or `vite preview` as a
   production server. Do not expose ports 8000 or 11434 through a firewall.
4. Use [deploy/Caddyfile](../deploy/Caddyfile) with Caddy 2.8+ as a starting
   configuration. Set `ATLAS_DOMAIN`, `ATLAS_USER`, `ATLAS_PASSWORD_HASH` and
   `ATLAS_DIST` in the Caddy service environment. Generate the password hash with
   interactive `caddy hash-password`; do not put passwords in shell command
   arguments. ATLAS_DIST is the absolute path to the built frontend.
   Authentication covers static files, API endpoints and API documentation.
   A managed identity-aware proxy is preferable when users need individual access
   revocation; all admitted users still share ATLAS privileges.
5. Validate the actual configuration with `caddy validate --config deploy/Caddyfile`
   and supervise both services. Configure resource limits, disk monitoring, private
   backups and an actual restore test. The example caps bodies at 26 MiB (25 MiB
   files plus multipart overhead); keep it aligned with `MAX_UPLOAD_MB`.

Before inviting a crew, confirm unauthenticated requests to `/`, `/api/health`,
`/api/conversations` and `/api/models` return 401. Authenticate and exercise chat
streaming, document upload, mission edits and a restart. Confirm direct access to
8000 and 11434 is blocked from another host and that the backup restores correctly.
Run load tests with synthetic data at the expected crew concurrency. A syntax
check and unit tests alone do not establish production capacity.

This deployment template has to be validated in your target environment; it is
not an already-deployed or load-tested service.

Upstream references: [Caddy authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth),
[body limits](https://caddyserver.com/docs/caddyfile/directives/request_body), and
[streaming proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

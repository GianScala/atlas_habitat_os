# Security and private data

ATLAS is a shared workspace for one trusted crew. It has no built-in user
accounts, per-user authorization or tenant isolation. Anyone who can reach its
API can read shared conversations and telemetry, edit mission records, upload
or delete documents, and install or remove local models.

Keep the API and Ollama bound to loopback. For remote access, authenticate the
entire site through a TLS gateway; see [deployment](docs/deployment.md). CORS,
Host validation and browser-origin checks are defense in depth, not access
control. All authenticated crew members have the same privileges.

Use database credentials that independently permit only reads. Query validation
is not a substitute for database permissions. Uploaded files, parsing and model
inference consume resources: accept uploads only from trusted users and apply
process memory, disk and concurrency limits in the deployment environment.

## Data handling

Never contribute real habitat data, derived private habitat profiles, credentials,
mission records, crew information, real chat transcripts or operational
screenshots. Use synthetic reproductions. Put private profiles in
`atlas_backend/config/private/`; keep runtime state outside your public checkout
where practical. An ignored file can still be force-added, and `.gitignore`
cannot erase past commits. The release guard inspects tracked content and history,
but pattern scanning cannot prove that numbers or renamed fixtures are synthetic.

Documents and indexes are stored on the ATLAS server. Chat history, retrieved
telemetry and document passages go to the selected model. Anthropic sends these
to a cloud API; use Ollama on a trusted local host for private-only inference.
A remote OLLAMA_HOST also sends data off the ATLAS server. Backups, logs and
browser storage need the same protection as the original data.

Model answers are fallible, including when they cite sources. Independently
verify operational decisions; ATLAS is not a certified safety or control system.

## Reporting a vulnerability

Do not open a public issue with exploit details or sensitive records. Use this
repository's **Security → Report a vulnerability** option when enabled. If it is
unavailable, ask a maintainer for a private channel without including details.
Maintainers should enable private vulnerability reporting before public launch.
Security fixes target the current main branch; there is no support SLA.

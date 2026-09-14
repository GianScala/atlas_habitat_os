# Contributing to ATLAS

Use an issue to describe a substantial proposal, or submit a focused pull
request for a bug fix. Explain the resulting behavior and provide a small
synthetic reproduction. Be respectful; discuss the code and evidence.

The project is maintained by [**GianScala**](https://github.com/GianScala), its
creator and main contributor. Additional contributors are credited through Git history.

## Development

Use Python 3.11+ and Node 22.12+. Follow the root README to install dependencies.
From `atlas_backend`, run `python -m pytest` and `python -m ruff check .` with
your virtual environment active. From `atlas_frontend`, run `npm ci` and
`npm test` and `npm run build`. The tests isolate storage and block outbound socket connections.
Never use real habitat credentials for tests.

Core telemetry logic accesses data through `app.datasource`; adapters belong in
`app/datasource/`. Keep habitat-specific rules in profiles. Add regression tests
for meaningful behavior changes and keep frontend API types aligned with backend
schemas. New network database adapters need independent read-only credentials.

## What belongs in a contribution

Code, documentation, original assets and independently synthetic fixtures belong
here. Real habitat records and configurations, private calibration values, renamed
mission exports, screenshots of actual operations and credentials do not.
Keep local profiles under `atlas_backend/config/private/`, not `config/examples/`.
The public examples are intentionally synthetic or generic templates.

Before publishing, inspect `git diff --cached` and run:

```sh
python3 scripts/check_release.py --staged --history
```

Local AI/editor directories (including `.claude/`, `.codex/` and `.cursor/`)
are excluded from the public source. Keep `.github/` and `.githooks/`: these
contain shared CI and release safeguards. Inspect `git diff --cached` even
after using `git add .`; ignore rules cannot detect secrets pasted into code.

The script is a guardrail, not proof of provenance. CI also runs it, but CI on a
public repository happens after publication, so local inspection is mandatory.
If data was accidentally committed, stop before pushing. If it was already
published, revoke credentials and coordinate incident response privately.

## Licensing

By submitting a contribution, you agree to license it under the project's
Apache-2.0 license and confirm you have the right to contribute it. Preserve
third-party notices. Do not submit assets whose redistribution rights are unclear.

Enable the optional local commit guard with `git config core.hooksPath .githooks`.
It is not installed automatically by cloning; review hooks before enabling them.

# Release readiness review

A snapshot of the engineering review performed on 2026-09-14, immediately before
the first public commit. It is kept as a record of what was and was not checked
at that point. It is not a guarantee of security, privacy provenance or
production capacity, and it does not describe commits made after that date.

## Assessment at the time of review

The source was judged a candidate for an open-source release once the
publication gates below were met. It is not certified production-ready or a
10/10 security assessment. The supported deployment is one backend process for a
trusted crew behind an authenticated gateway, not an anonymous public API.

This pass inspected repository structure, API/security boundaries, data adapters,
storage, document handling, voice processing, frontend transport, tests, CI,
dependency advisories and release exclusions. It does not prove every code path
correct. Existing uncommitted voice and visual changes were preserved.

## Changes made in this review

- Fixed the voice test harness's cross-context Error constructor and portable
  file URL handling. Added `npm test` and made CI execute frontend tests.
- Restricted FFmpeg recording inputs to browser audio containers and the file
  protocol; playlists are rejected. A regression test exercises the real decoder
  when FFmpeg is installed. See [FFmpeg protocol restrictions](https://ffmpeg.org/ffmpeg-protocols.html).
- Corrected SSE handling of CRLF delimiters, truncated frames and early consumer
  cancellation, with regression tests.
- Removed tool arguments from informational logs to avoid recording question
  content supplied to knowledge searches.
- Excluded speech session artifacts from Git and added recordings, model weights
  and model-directory metadata to release guard checks. Local files were retained.
- Extended the CI dependency audit to optional voice requirements.
- Replaced absolute answer-accuracy claims in the README and API description
  with the actual grounding goal and verification requirement.

Earlier hardening includes upload-size and origin guards, read-only query checks,
synthetic fixtures, bundled font notices and the authenticated Caddy template.

## Follow-up cleanup and attribution

- Added GianScala as creator, main contributor and maintainer in the README,
  NOTICE, contribution guide and project metadata. The application copyright
  notice names that handle alongside ATLAS contributors; third-party notices are
  preserved.
- Removed three unused `_full.png` logo backups, the obsolete logo generator and
  a local speech session artifact. Removed the deleted SVG from the index and
  fixed its stale favicon reference. Current logo assets remain in use.

## Verified on 2026-09-14

- 511 backend tests and Ruff pass, including in a fresh Python 3.14 environment
  made from the non-ignored source candidate. Two upstream TestClient/AnyIO
  deprecation warnings remain in that fresh environment.
- All eight frontend tests and the production build pass. A clean `npm ci`
  succeeds; tests/build also run with supported Node 24.19.0. The default shell
  uses Node 20 and produces an engine warning; contributors should use Node 22.12+.
- npm audit and pip-audit (base plus optional voice requirements) report no known
  vulnerabilities. This is a point-in-time advisory check, not an exploit audit.
- The worktree and refreshed exact-index release guards pass for the cleaned
  release candidate. The repository had no commits at that point, so the
  history scan had no history to inspect. Commits made since then are covered
  only by the guard runs performed on them.
- No ignored `.env`, local database, uploaded document or speech session file was
  copied into the clean source candidate.
- No commit, push or deployment was performed in this review. Live browser,
  microphone, model-provider and production-gateway behavior was not re-tested.

## Publication gates

These were the conditions set for the first public commit. Gate 1 remains
standing practice for every later change.

1. Review the staged release and run
   `python3 scripts/check_release.py --staged --history` before committing. The
   index was refreshed after cleanup; subsequent edits must be staged and checked
   again.
2. Finalize any ongoing logo edits and review their provenance. The newly added
   `NASALIZA.TTF` was removed from public assets at the maintainer's request;
   the application uses the already bundled OFL-licensed Michroma font instead.
   A private backup of the unused font was kept outside the repository.
3. Confirm all retained fixtures, numerical examples and original artwork are
   independently shareable. No private habitat name or common credential
   pattern was found in the original index. Renamed or unlabeled private data
   cannot be ruled out by pattern scanning; this review cannot establish
   historical authorship.
4. Enable GitHub private vulnerability reporting and secret scanning/push protection
   where available, and require CI before merging. CI on a public repository runs
   after publication, so it cannot replace local pre-publication checks.

## Deployment gates

Use the authenticated deployment guide. The application shares conversations,
settings, documents and model administration across all admitted users; it has
no tenant isolation or per-user roles. Do not expose the bare API or Ollama.
Validate real TLS, firewall rules, backup restoration and expected concurrency in
the target environment. Live Anthropic/Ollama answers and network Postgres/MySQL/
Grafana/InfluxDB integration were not exercised against real services. The suite
uses synthetic data and mocked transports. Two upstream TestClient/AnyIO
warnings remain; tests pass without suppressing them.

Additional production work: test simultaneous writes/turns to the same conversation
(the repository does not serialize full turns), interrupted streams and deletion
during inference. Load-test SQL result sizes and document extraction: row fetching
and decompression can consume much more memory than request-body limits imply.
Speech CLI calls have timeouts, but in-process Piper inference does not have a
hard execution deadline. Apply process limits and measure these paths before
claiming service-level guarantees. Frontend coverage is currently eight focused
transport/playback tests, not an end-to-end browser or accessibility suite.

The current font vendor distinguishes finished artwork from font redistribution;
the license supplied with the exact font copy controls. See
[Typodermic licensing](https://typodermicfonts.com/license/) before adding it.

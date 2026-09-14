# Third-party notices

ATLAS application code uses Apache-2.0. Bundled fonts retain their own licenses;
the project's license does not replace them.

| Font | Upstream source | Included license |
| --- | --- | --- |
| DM Mono | https://github.com/google/fonts/tree/main/ofl/dmmono | [OFL](atlas_frontend/public/fonts/dmmono-OFL.txt) |
| Inter | https://github.com/google/fonts/tree/main/ofl/inter | [OFL](atlas_frontend/public/fonts/inter-OFL.txt) |
| Michroma | https://github.com/google/fonts/tree/main/ofl/michroma | [OFL](atlas_frontend/public/fonts/michroma-OFL.txt) |
| Public Sans | https://github.com/google/fonts/tree/main/ofl/publicsans | [OFL](atlas_frontend/public/fonts/publicsans-OFL.txt) |

These SIL Open Font License texts, including copyright notices, travel with the
font files in the frontend build. Other dependencies retain the licenses in their
published distributions. Review new dependencies and assets before redistribution.

The application wordmark uses the bundled Michroma font. The unlicensed local
Nasalization font is not included in the public project.

Optional voice support uses separately installed whisper.cpp (MIT), ffmpeg,
and Piper (GPL-3.0). The optional Python Piper dependency stays loaded for fast
synthesis, with a CLI fallback. Their executables and speech model files are not
bundled with ATLAS. Piper retains its GPL-3.0 terms; review those terms when
redistributing a combined installation. Operators must also review each model's
own license and model card. Local model downloads are excluded from Git.

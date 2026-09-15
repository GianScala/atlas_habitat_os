# ATLAS frontend

React, TypeScript, Vite, and Recharts. The frontend provides chat, telemetry
charts, mission tracking, manual meter entry, and settings.

For a walkthrough with screenshots, see the
[consumption guide](../docs/consumption-guide.md).

## Run locally

Requires Node.js 22.12+ and the backend running on port 8000.

```bash
npm install
npm run dev
```

Open [localhost:5173](http://localhost:5173). Vite proxies `/api` to the backend.
To use another port:

```bash
VITE_API_TARGET=http://127.0.0.1:8001 npm run dev
```

`VITE_API_TARGET` is read from the shell, not `.env.local`.
`VITE_API_BASE_URL` sets a separate API origin at build time; leave it empty
for same-origin hosting. Never put secrets in frontend environment variables.

## Commands

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start Vite with hot reload |
| `npm run typecheck` | Check TypeScript |
| `npm test` | Run the frontend regression tests |
| `npm run build` | Type-check and build `dist/` |
| `npm run preview` | Preview the production bundle locally |

## Routes and source map

| Route | Implementation |
| --- | --- |
| `/`, `/c/:conversationId` | `pages/ChatPage.tsx` |
| `/dashboard` | `pages/dashboard/`; includes Mission plan and Crew meter log |
| `/settings/:tab` | `pages/settings/` |
| `/models`, `/naming` | Redirects to the corresponding settings tabs |

Dashboard and settings are loaded lazily. `App.tsx` owns routing; page hooks
own data and interaction state.

| Directory | What belongs here |
| --- | --- |
| `pages/mission/` | Setup, budget cards, daily chart/table, and planned extras |
| `pages/logbook/` | Meter entry, consumption breakdowns, and telemetry comparison |
| `hooks/` | API state, refreshes, persistence coordination, and chat streams |
| `lib/` | API client, types, cache, dates, formatting, and chart transforms |
| `components/` | Shared controls, messages, source details, and charts |
| `styles/` | Tokens, base styles, layouts, components, charts, and pages |
| `theme/`, `icons/` | Theme preferences and shared SVG icons |

## Keep the numbers understandable

- Habitat consumption uses whole-habitat sensors. The room filter applies only
  to Room analysis.
- Mission plan compares telemetry with saved budgets. Crew meter log calculates
  consumption from manual readings. Keep those sources distinct.
- Show the unit and reading time. Preserve missing values as gaps.
- A full manual day needs morning, evening, and the next morning's readings.
  Keep entered dial values separate from calculated usage.
- The daily plan chart has an equivalent table in `DayPlanTable.tsx`.
- Bars start at zero; line charts fit their data. Use separate panels for
  different units. Room colours stay stable when the selection changes.
- Pair status colours with text. After eight room colours, use dashed strokes
  from `lib/palette.ts` to distinguish additional series.

## Data flow and caching

`lib/api.ts` owns backend calls. Hooks initialise from the in-memory cache in
`lib/cache.ts`, then refresh when needed. The cache survives route changes but
not page reloads. View, range, room selection, and theme preferences use
`localStorage`.

Keep the last successful response visible after a refresh error, with its
reading time and the error. When filters change, label the pending range and
visually mark the old data until the matching response arrives. Saving a plan
invalidates tracking calculated against the previous budgets.

Chat arrives as server-sent events. `useChat` and the live-turn helpers assemble
messages; components render the answer, tool activity, and sources. Keep
`lib/types.ts` aligned with the backend schemas whenever the API changes.

## Presenting the AI conversation

The chat UI shows the crew question, the streamed model answer, and its evidence
as separate elements:

- `ToolTrace` shows what was requested and whether it returned data. It opens
  during the turn and can be expanded after the answer.
- `SourceFooter` lists the source references returned by the backend. Preserve
  the adapter's text: this may be a query summary rather than executable SQL.
- `ThinkingTrace` presents optional model-provided thinking separately from
  tool activity; it is not a data source.
- The live start event identifies the provider and model used for that turn.
  Settings controls which provider handles subsequent questions.

Do not imply that every answer came from a sensor query. Manual-log results and
document passages carry different provenance. The transcript should let a crew
member distinguish an interpretation from the records that support it.

See the [AI assistant guide](../docs/assistant-guide.md) for the user workflow
and the [backend README](../atlas_backend/README.md#the-ai-assistant) for the tool loop.

## Styling

Start at `styles/index.css` for cascade order. Shared sizes and spacing live in
`tokens/scales.css`; light and dark palettes use the same token names. Keep the
system-dark and explicit-dark rules in sync. Chart colours live in
`tokens/series.css`.

Use the existing type, spacing, and colour tokens. Icons share the 16px grid and
`currentColor`; export new icons from `icons/index.ts`.

## Deploy

`npm run build` creates `dist/`. Serve it with an SPA fallback to `index.html`
so direct links and reloads work. If the API uses another origin, set
`VITE_API_BASE_URL` before building and configure backend CORS.
Follow the [deployment guide](../docs/deployment.md) for authentication and hosting.

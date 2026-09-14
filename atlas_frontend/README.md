# ATLAS - frontend

A React + TypeScript chat interface for the habitat telemetry assistant.
Answers stream in as they are produced, formatted as Markdown, with the
queries behind them shown alongside.

## Why it looks the way it does

The interface has one job beyond rendering text: make it obvious where a
number came from. Three things follow from that.

- **The trace opens while an answer is being produced.** It is the only sign
  anything is happening, and it names the sensor being read. Once the answer
  arrives it collapses to a one-line summary.
- **Sources are separate from the trace.** The trace is the narrative of what
  was tried; the source footer is the citation. Anyone doubting a figure can
  copy a line into Grafana and get the same result.
- **The data link has its own indicator.** "The app is running" and "the
  sensors are readable" are different claims. When the second is false, every
  answer will be an apology - better to say so up front than let someone
  discover it one question at a time.

Numeric table cells right-align so a per-day consumption column lines up on the
decimal point; text cells stay flush left.

## Routes

| Path | Page |
| --- | --- |
| `/` | a new conversation |
| `/c/:conversationId` | a stored one - linkable, bookmarkable |
| `/dashboard` | the charts |

The dashboard is loaded on demand: its charting library is most of the bundle,
and someone who only ever asks questions should not pay for it.

## Layout

```
src/
├── main.tsx           entry point
├── App.tsx            routing, and nothing else
├── pages/
│   ├── ChatPage       sidebar · transcript · composer
│   ├── dashboard/     view · range · room selector · panels
│   │   ├── DashboardPage      the arrangement, and nothing else
│   │   ├── DashboardControls  the control strip above the charts
│   │   ├── DashboardReadout   resolution · feeds · read-at
│   │   ├── PanelGrid          the charts, under their group headings
│   │   ├── drawable.ts        panels -> what a chart needs, pure
│   │   ├── useDashboardPrefs  the window and the view, persisted
│   │   └── useRoomSelection   which rooms are drawn, and their colours
│   ├── mission/       the third view, which is not made of panels
│   │   ├── MissionView   the whole page, per resource
│   │   ├── MissionSetup  declare the mission: start, length, ceilings
│   │   ├── BudgetCard    one resource against one window
│   │   ├── BudgetRing    used vs allowed, with a tick at what was due by now
│   │   ├── DayPlanChart  a bar per mission day, against planned and revised
│   │   ├── DayPlanTable  the same figures, as the chart's accessible twin
│   │   └── ExtrasPanel   book, edit and drop the extras
│   └── settings/
│       ├── AppearanceSection  light, dark, or follow the machine
│       └── AssistantSection   the register answers are written in
├── hooks/
│   ├── useChat.ts          events (or a stored thread) -> messages
│   ├── useConversations.ts the sidebar's list
│   ├── useDashboard.ts     panel data for a range
│   ├── useMission.ts       the plan, and consumption measured against it
│   └── useHealth.ts        backend and datasource health, polled
├── lib/
│   ├── api.ts         every call to the backend
│   ├── cache.ts       what has been fetched, kept across route changes
│   ├── sse.ts         server-sent events over fetch
│   ├── types.ts       the wire contract, mirroring the backend
│   ├── palette.ts     series colour and stroke assignment
│   ├── views.ts       habitat-level · per-room · the mission plan
│   ├── mission.ts     reading a plan out loud
│   ├── missionDates.ts calendar arithmetic that survives a timezone
│   ├── rooms.ts       one room per place, whatever the tag spells
│   ├── chartData.ts   reshaping panel data for the chart library
│   └── format.ts      presentation helpers
├── components/
│   ├── Sidebar        collapsible chat history
│   ├── AppHeader      identity, status, dashboard, new conversation
│   ├── MessageList    the scrolling transcript
│   ├── MessageBubble  one turn
│   ├── Markdown       answer rendering, tables included
│   ├── ToolTrace      the queries, live
│   ├── SourceFooter   the InfluxQL, as citation
│   ├── ThinkingTrace  summarised reasoning, collapsed
│   ├── ErrorBanner    a failure someone can act on
│   ├── Composer       the question box
│   ├── EmptyState     opening screen and starter questions
│   ├── StatusBadge    the data link
│   ├── RangePicker    the shared time window
│   ├── ViewSwitch     habitat consumption · room analysis · mission plan
│   ├── RoomSelect     which rooms are charted, as a dropdown
│   └── charts/        PanelCard · PanelChart · legend · tooltip
├── icons/             one file per icon, on a shared 16px grid
│   ├── icon.tsx       the contract: size, viewBox, currentColor
│   └── index.ts       the barrel - `import { Send } from '@/icons'`
├── theme/
│   ├── theme.ts       light · dark · system, stored and applied
│   ├── useTheme.ts    the setting, and what it resolves to now
│   └── ThemeToggle    one button, cycling the three
└── styles/
    ├── index.css      the import list, in cascade order
    ├── tokens/        scales · theme-light · theme-dark · series · breakpoints
    ├── base/          reset · type roles · motion
    ├── layout/        app · sidebar
    ├── components/    one file per piece of interface
    ├── charts/        card (the box) · chart (the plot) · tooltip
    └── pages/         chat · dashboard · mission · plan-editor
```

Components are presentational. `useChat` is the only place that knows how a
stream of events becomes a list of messages.

## What survives a route change

Navigating unmounts a page and everything its hooks were holding, so without
somewhere outside the tree to keep it, a trip to the dashboard and back would
refetch the conversation list, the open transcript, and the health badge, and
a trip the other way would refetch every panel - each starting from a blank
screen. `lib/cache.ts` is a module-scoped store the hooks read on mount and
write when a fetch lands. A cached page draws immediately and revalidates
behind itself; the reader never sees a spinner where an answer already was.

| Kept | Revalidated after | Because |
| --- | --- | --- |
| dashboard panels, per range | 30s | readings bucket at minutes; seconds of drift are invisible |
| mission tracking | 30s | a day's allowance moves at the pace of a day |
| conversation list | 15s | a finished turn changes a thread's title and its place in the order |
| datasource health | 60s | the poll interval - a route change should not outpace it |
| a thread's transcript | 5 min | only this tab writes it; another tab is the reason to look again |
| range presets, starter questions | never | fixed for the session |

Two things it deliberately does not do. It holds nothing across a reload -
a hard refresh should mean fresh numbers - and nothing subscribes to it, so
an entry is a starting value for a hook's state rather than a second source
of truth competing with it.

## Which window is on screen

Keeping the drawn charts up while a request runs is right when the same
window is being refreshed and wrong when it is not. Change the range and, for
as long as the request takes, every chart is the OLD window under the NEW
window's heading - the page looks like it ignored the click, and a reader who
does not wait reads figures for the wrong hours.

So the payload states the window it was built for, and the hooks compare it
against the filter now selected rather than trusting a flag they set
themselves - `dashboard.range` against the picker in `useDashboard`,
`tracking.history_days` against the day buttons in `useMission`. When they
disagree, the page says so: the range that is loading, what is still drawn
underneath, and the charts held back at reduced opacity and out of the tab
order until they are the answer to the question being asked.

The charts are not blanked. Emptying the page loses the reader's place and
tells them nothing they did not know. What it must never do is present the
old window as the new one. The same rule covers a failed refresh: the last
good reading stays on screen with the failure stated above it and its age
attached, rather than being deleted by a request that did not arrive.

A "Read at" figure sits in the control strip for the same reason - a cached
payload is drawn the instant a window is re-selected, which is what makes the
page quick, and would make it quietly dishonest without a timestamp, since a
chart from four minutes ago looks exactly like one from now.

A transcript is cached only once a turn has settled. A turn that was stopped
or that failed leaves a transcript only this tab believes in, so the entry is
dropped instead and the next visit asks the backend what it actually kept.

Saving a mission plan drops its tracking entry rather than refreshing it: the
drawn figures were measured against the old budgets, and a card showing 80% of
yesterday's budget after the crew raised it would be wrong in the most quietly
convincing way available.

## Chart decisions

The form follows what the number is, not preference:

| Mark | For | Why |
| --- | --- | --- |
| line | a level or rate over time | position carries the value |
| area | a tank level | the fill reads as "how full" |
| bar | a quantity per interval | discrete intervals deserve discrete marks |

**Where the value axis starts is a correctness question, not a style one.**
Bars start at zero because bar *length* encodes magnitude - a truncated bar
misstates the ratio between two bars. Lines do not: room temperature lives
between 19 °C and 27 °C, and anchoring that axis at zero spends four fifths of
the height on a range the data never visits, flattening every difference worth
seeing. So lines fit their data and bars do not.

There is exactly **one y-axis**, ever. Two measures of different scale get two
panels - a second axis lets whoever drew it place the crossing point wherever
they like, which draws a conclusion rather than showing data.

**Eight series colours, never invented.** The eight were checked against this
app's own chart surfaces for lightness, chroma, colourblind separation, and
normal-vision separation, in both themes. A ninth hue generated at runtime
would have been checked against nothing, so there isn't one: past the eighth
room the palette starts a second lap and those rooms are drawn **dashed**. A
series is the colour and the stroke together, which is what lets every room be
on at once without two of them looking like one. The same device already
separated a room reported under two tag spellings, and the two cases share one
list of strokes so they cannot collide - see `lib/palette.ts`.

Colour follows the room, not its position in a filtered list, so a room stays
the same colour when another is toggled off and across every panel it appears
on.

A gap in a line is a sensor that reported nothing. It is never bridged and
never drawn as zero.

**No database words in the interface.** Each card's footer says
`WATER.LITRES · 1 POINT PER 2 MIN`, not `2 MIN BUCKETS`. A "bucket" is what
InfluxQL calls the interval it groups readings into; outside a database nobody
calls it that, and beside `LITRES` it reads as a pail while on the power charts
it reads as a mistake. The sensors report faster than any chart can draw, so
readings are grouped into equal intervals and each interval becomes one point -
which is true of every panel, and is why the note appears on all of them.

## Three views, because there are three kinds of question

Water drawn and mains power are properties of the habitat - one tank, one
meter on the wall, and no room owns a share of either. Temperature, humidity,
CO₂ and submetered power draw are properties of a room and mean nothing until
you say which room.

Shown together under a single room filter, the filter looked like it applied to
both: narrowing to the dormitory left the whole-habitat water chart unchanged,
which reads as a bug. So the dashboard has two views, switched top right of the
control strip, and only Room analysis carries a room selector.

Which view a panel belongs to is a contract with the backend catalogue: a panel
whose series are rooms is named `room_*`. Add one to `PANELS` in
`atlas_backend/app/services/dashboard.py` and it appears under Room analysis
with nothing to change here. Both views come from one request, so switching
between them costs no fetch.

**Mission plan is the third, and it is not made of panels.** The first two
report what the habitat did; this one reports it against what the crew said
they would do, which is the only place in this interface carrying a number no
sensor produced. It draws from `/api/mission` and brings its own controls, so
the shared window and the room filter - which would govern nothing on it - are
hidden while it is open. `isPanelView` in `lib/views.ts` is that gate.

Everything on it is arranged around keeping the two kinds of number apart. A
ceiling the crew has not set is a figure this repository shipped, and it is
labelled as one on the card and in a banner at the top until they replace it.
With no mission declared at all there is nothing to measure against, and the
page says so and shows the setup form instead of drawing empty rings.

**The ring is a part-to-whole with one part and a hero number in the middle** -
what a ring is actually good for. It is not a pie: there are no slices, and
nothing is ever split into categories. Two marks share the track: the arc is
how much of the allowance is gone, the tick is what the **plan expected by
now**. That tick is not the elapsed share of the window - it is the day plan
summed to this moment, with each extra on its own day, because a 200-litre
experiment booked for the last day of a cycle is not two-thirds spent on the
second day.

"80% of today's water" is alarming at breakfast and a good day at midnight, so
neither figure is ever shown alone, and the three statuses come from the pace
rather than the percentage - `On plan`, `Running hot`, `Over plan`, each a word
as well as a colour.

**The day-by-day chart is three series on one axis**, all in the same unit:
bars for what was drawn, a line for what was planned at the start, and a dashed
line for what is allowed from here. That third series is the point - overspend
in week one is a lower line for every day after it, and that consequence is a
shape no single window can show. It borrows the **status** palette for bars that
went over: on a chart whose only question is which days cleared their
allowance, that is the data. Today is drawn hollow, because a day four hours
old is not a low day. The legend names all four marks in words, and
`DayPlanTable` carries the same figures as text.

The view, the window, and the room selection are each
remembered in `localStorage`, so a reload comes back to the page you left.

## Setup

```bash
npm install
npm run dev
```

Opens on `http://localhost:5173`. **The backend must be running on port 8000** -
the dev server proxies `/api` to it, so the browser sees a single origin and
CORS never applies.

## Scripts

| Command             | Does                                     |
| ------------------- | ---------------------------------------- |
| `npm run dev`       | Dev server with hot reload               |
| `npm run build`     | Type-check, then bundle to `dist/`       |
| `npm run typecheck` | Type-check only                          |
| `npm run preview`   | Serve the built bundle locally           |

## Configuration

Everything is optional; the defaults work for local development. See
`.env.example` and the [configuration guide](../docs/configuration.md).

| Variable            | Purpose |
| ------------------- | ------- |
| `VITE_API_TARGET`   | Shell variable for the dev-server proxy (not read from `.env.local`). Default `http://127.0.0.1:8000`. |
| `VITE_API_BASE_URL` | Where the backend lives. Set only when serving the built bundle from a different origin than the API - then add that origin to the backend's `CORS_ORIGINS`. |

## Deploying the built bundle

`npm run build` produces a static `dist/`. Serve it from any static host. If it
is not on the same origin as the API, set `VITE_API_BASE_URL` at build time and
add the frontend's origin to `CORS_ORIGINS` in the backend's `.env`.

**This is a single-page app, so the host must rewrite unknown paths to
`index.html`.** Without that, `/dashboard` and `/c/<id>` return 404 on a hard
reload - they are client-side routes, not files. The dev server and
`npm run preview` both do this already.

## Styling and themes

Every rule in the app is in exactly one file under `src/styles/`, and the file
it is in is named after the thing it styles. `index.css` is the import list and
the only place cascade order is decided; open it first.

```
tokens/     values, no selectors beyond :root
base/       the unstyled document
layout/     the frame the pages sit in
components/ one file per reusable piece
charts/     the plot surface
pages/      what is true on one route only
```

**The two themes are two files.** `tokens/scales.css` holds everything that
does NOT change between them - type, space, shape, layout. `theme-light.css`
is the base palette on `:root`; `theme-dark.css` redefines the same token names
and nothing else. So adding a theme means writing one file of colours, not
copying ninety tokens and hoping.

Dark is reached two ways, and both are in `theme-dark.css`: a
`prefers-color-scheme` block for "the OS asked", and a `[data-theme="dark"]`
block for "the reader asked". They carry the same values and must stay in
sync - plain CSS cannot share one block across a media query and a selector.

The reader's choice is a real control: `src/theme/` stores it in
`localStorage` and `index.html` applies it before first paint, so an override
that disagrees with the OS does not flash the wrong palette on load. Three
settings, not two - `system` keeps following the OS when it changes at sunset.

**Colour means something here.** The chrome is monochrome, so the only two
places colour appears are load-bearing: the three instrument colours
(`--ok`, `--warn`, `--danger`) in `theme-light.css`, and the eight chart series
in `tokens/series.css`. That last file is the one to open to restyle every
chart in the app; both themes' series live there together because the eight
were validated as a set. Never add a ninth by generating a hue -
`lib/palette.ts` starts a second lap with dashed strokes instead.

**Boxes and plots are separate.** `charts/card.css` is the box a chart sits in
 -  frame, heading, and the states it shows when there is nothing to draw.
`charts/chart.css` is the plot itself, and `charts/tooltip.css` the readout
over it. Restyling the container does not touch the graph.

Breakpoints live with their components, so grepping `max-width: 640px` finds
every rule at that width. `tokens/breakpoints.css` documents the four and holds
only the global re-stepping of `--gutter` and `--header-height`.

## Icons

One file per icon in `src/icons/`, all drawn on the same 16px grid against the
contract in `icon.tsx`, stroked in `currentColor` so an icon takes the colour
of the control it sits in. To add one: copy the smallest file, draw on the 16
grid, export it from `index.ts`. The barrel is re-exports only, so the bundler
still drops the icons a page never uses.

## The wire contract

`src/lib/types.ts` mirrors `atlas_backend/app/schemas/chat.py`. The backend is
the source of truth; when an event gains a field, change it there first and
update the TypeScript to match.

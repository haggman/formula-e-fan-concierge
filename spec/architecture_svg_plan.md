# Plan to rebuild `docs/architecture.svg`

The vendored `docs/architecture.svg` is the Ch2 diagram ("Formula E Race Engineer — what's
running in your project", 1400×830, Google palette, single "The Agent" box + an A–F tier ladder
along the bottom). Rebuild it for the Race-Day Companion. Keep the visual language; change the
content.

## Keep (unchanged boxes + style)

- Canvas/style: 1400×830 (likely grow to ~1400×950 for the third agent + CX), Helvetica, the
  Google palette (`#aecbfa`/`#174ea6` blues, `#5f6368` arrows, the `arr` marker), the
  GIVEN/YOU-BUILD chips.
- **GCS → BigQuery** (top): keep; relabel BigQuery to note **R10 + 10-season career/results**.
- **Simulator (Cloud Run · fe-simulator) → Pub/Sub**: keep.
- **MCP Toolbox (Cloud Run · fe-toolbox)**: keep.
- **Firestore (live race state + events)**: keep — now consumed by *two* readers (commentator +
  subagent), so it becomes a shared hub; redraw arrows accordingly.

## Change

- **Pub/Sub → State Writer** edge label: `push (OIDC)` → **`pull`**; State Writer box subtitle
  `Cloud Run · fe-state-writer` → **`Cloud Run Worker Pool · fe-state-writer`**.
- **Title/subtitle**: "Formula E Race Engineer…" → **"Formula E Race-Day Companion — what's
  running in your project"**; subtitle to mention the second-screen fan UI + two voices.
- **"The Agent" single box** → replace with the **three-agent** layout (below).
- **A–F tier ladder**: replace the single sequential ladder with **three short per-team
  ladders** (commentator A–D; CX concierge E–F; subagent as the shared dependency), or a
  compact legend noting parallel build.

## Add

1. **GIVEN Fan UI** panel (top-right or spanning the top): track map · car list · click-to-select
   · live stats panel · **CX chat widget**. Mark **GIVEN**. Two websocket edges to the
   commentator: `{select}` in, `{radio}` out.
2. **Commentator · ADK** box (YOU BUILD): subtitle `*/commentator/` · field-wide frame_tools +
   scorer (selected-car boost) + TTS. Edge: reads Firestore "now"; websocket to UI.
3. **Race-Data Subagent · ADK** box (YOU BUILD): subtitle `*/race_data_subagent/` · now_tools +
   ToolboxToolset · **MCP server (Cloud Run)** · time-honest. Edges: reads Firestore "now";
   `→ MCP Toolbox → BigQuery`.
4. **CX Concierge** box (YOU BUILD, low-code chip): subtitle `*/cx_concierge/` · orchestrator.
   Edges: **MCP `/mcp`** → Race-Data Subagent; **Data store / File search** (profiles, rules) +
   **Google Search**; embedded in the UI chat widget.
5. A small **time-honesty** annotation on the subagent→BigQuery edge: "bound by
   race_wall_time_ns from 'now'".

## Suggested layout (left→right, top→bottom)

- Row 1: GCS → BigQuery (left-center); GIVEN Fan UI panel (right).
- Row 2: Simulator → Pub/Sub → **State Writer (Worker Pool, pull)** → **Firestore "now"** (the
  hub, center).
- Row 3 (consumers of "now"): **Commentator** (left, → UI) and **Race-Data Subagent** (right).
- Row 4: **CX Concierge** (bottom-left) → MCP → Subagent; Subagent → MCP Toolbox → BigQuery
  (close the loop up to Row 1).

## How to produce it

Hand-author the SVG (as Ch2's was) for crisp control, reusing the existing `<defs>`, palette,
and box/chip helpers from the vendored file. Validate by rendering (`.svg` previews inline) and
eyeball against `spec/architecture.md`. Keep it a single self-contained SVG in `docs/`.

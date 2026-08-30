# Decision Log — Skylark BI Agent

## Key assumptions

- **Two boards, read-only.** Deals and Work Orders are imported as separate monday.com boards;
  the agent only ever reads them (GraphQL `boards`/`items_page` queries), never writes back.
- **Column layout is environment-specific.** Since monday.com assigns opaque column IDs
  (`text9`, `status`, `date4`...) that depend on how each board was built, the app doesn't
  hardcode them. A `column_mapping.json` translates logical fields (`client`, `sector`,
  `stage`, `value`...) to real column IDs, filled in once after import via a small CLI helper
  (`discover_columns.py`) that lists a board's columns and IDs.
- **A cross-board link between a deal and its work order may not exist as a native
  Connect-Boards column.** The agent currently joins on `client` (+ optional SQL date
  proximity) when a question needs both boards, via the `run_sql_query` fallback, rather than
  assuming a guaranteed foreign key. This is best-effort, not exact — documented, not silently
  trusted.
- **Missing data is common and shouldn't block an answer.** Nulls, "N/A", "-", blank cells, and
  inconsistent date formats are normalized (`normalize.py`) rather than dropped or treated as
  zero. The agent is instructed to check `get_data_quality_report` and mention a caveat when a
  field it relied on has meaningful missingness — not on every answer, only when it's material.
- **"This quarter" / relative time phrasing is resolved by the agent, not the user.** The agent
  defaults reasonably (current calendar quarter, etc.) and states its assumption in the answer
  rather than always stopping to ask — it only asks a clarifying question when the request is
  genuinely ambiguous (e.g. which board a term refers to, or an unspecified sector when several
  are similar).

## Trade-offs chosen, and why

1. **Tool-use ReAct loop over a hand-rolled router.** Rather than writing a custom
   intent-classifier + regex-based answer verifier, the orchestrator gives Claude native
   tool-calling access to `compute_metric`, `run_sql_query`, `search_notes`, and
   `get_data_quality_report`, with a system prompt that forbids stating any number not backed
   by a tool result in the same turn. This is less code, more robust to phrasing variation, and
   still keeps the actual arithmetic outside the LLM — the trade-off is a lighter, prompt-based
   verification instead of a separate hard-blocking numeric-match verifier step. With more time
   I'd add that second pass back in as a non-LLM safety net.
2. **Deterministic metrics layer in front of generated SQL.** Nine common founder metrics
   (pipeline by sector, weighted pipeline, win rate, cycle time, completion rate, on-time
   delivery, overdue work orders, revenue vs. cost, stalled deals) are plain, hand-verified
   pandas functions the agent is told to prefer. Only genuinely novel questions fall through to
   LLM-generated SQL against DuckDB — and even then it's SQL, not arbitrary `exec()`'d Python,
   which is both safer and easier to sanity-check (`_is_safe_select` blocks anything but a
   single read-only `SELECT`/`WITH`).
3. **Keyword/fuzzy search over notes instead of embeddings-based RAG.** A full
   `chromadb` + sentence-transformer pipeline is the natural upgrade for "which deals mentioned
   pricing concerns" style questions, but it adds a dependency, an indexing step, and another
   thing that can silently return wrong context. Given the timeline, `rapidfuzz` keyword/partial
   matching over the notes column covers the same demo cases without that risk. This was a
   scope cut, not an architecture decision I'd defend as final.
4. **In-memory session state, no database.** Chat history and the data cache live in the
   backend process. Simple to run and deploy in the time available; it means history resets on
   redeploy and won't scale past one server instance. Fine for a graded prototype, not for
   production.
5. **Text canonicalization kept simple.** Sector/stage/status values are cleaned (whitespace,
   case, null-token collapsing) and mapped through a small hand-written synonym table
   (`STAGE_SYNONYMS`, `STATUS_SYNONYMS` in `data_sync.py`) rather than fuzzy-clustered against a
   discovered taxonomy. Good enough for a handful of known variants; a messier real dataset with
   many spelling variants would need the fuzzier approach the original design sketch called for.
6. **Python/FastAPI throughout, DuckDB for query fallback.** One runtime for the monday.com
   client, pandas normalization, and the LLM/tool layer, rather than splitting frontend
   (React/Node) and backend (Flask/Spring) toolchains — the vanilla-JS single-file frontend
   trades some polish for zero build step, which mattered directly against the time limit.

## What I'd do differently with more time

- Add the hard-blocking numeric verifier (extract numbers from the draft answer, diff against
  tool outputs, force a strict re-narration on mismatch) as a second line of defense behind the
  prompt-level instruction.
- Replace keyword notes search with real embeddings (Voyage/OpenAI/local
  sentence-transformers) and add a verified few-shot example store for SQL generation that
  grows every time a generated query is confirmed correct — both were in the original design,
  cut here for time.
- Persist sessions and the data cache in a real store (SQLite/Postgres + Redis) instead of
  process memory, and add a real Connect-Boards-aware cross-board link resolver with a
  confidence score instead of a best-effort client-name join.
- Build out an eval set (10-15 hand-verified founder questions) and run it after every prompt
  or logic change, rather than the manual spot-checks used to build this in the time available.
- Sandbox the SQL fallback further (query cost/row limits, timeout) for a multi-user production
  deployment; the current guard is sufficient for a single-user demo but not hardened.

## How I interpreted "prepare data for leadership updates"

The agent treats this as a **conversational request it can already fulfill**, not a separate
scheduled/export feature: asking it to "prepare a leadership update" or "give me an exec summary
of pipeline and delivery" triggers a system-prompt-level instruction to produce a short,
structured brief — pipeline health, notable wins/risks, operational status, and any data-quality
gaps worth flagging — phrased so it can be pasted directly into an update email or Slack post.
This reuses the same tool-calling path (so the numbers are still grounded), rather than building
a separate templated "report generator" — with more time, the natural extension is a
scheduled/exportable version (e.g. a weekly digest job that renders the same brief to
Markdown/PDF and emails or posts it automatically).

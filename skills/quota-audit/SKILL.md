---
name: quota-audit
description: >
  Analyze which project/repo and which command/skill is actually consuming
  Claude Code's 5h/session and 7d/week quota, with real per-session token
  cost estimates (not a guess from file size or session count), the actual
  timeline of when a rate limit was hit and which repo was blocked, plus an
  anomaly check for polling/monitoring loops that inflate session counts
  without real cost. Use whenever the user asks "who/what is eating my
  quota", "why did my quota suddenly spike", "where are my tokens going",
  "quota analysis" (or the Chinese equivalents "為什麼 quota 突然爆量",
  "token 都花在哪", "額度都被誰用掉"), wants to optimize Claude Code usage
  across multiple projects, or can't tell which repo/automation caused a
  5h or 7d quota spike.
allowed-tools: Bash(python3:*), Bash(claude:*), Bash(date:*), Write
---

# quota-audit — real per-project, per-command quota breakdown

`claude -p "/usage"` reports account-wide 5h/7d percentages with some
tags (top skills/subagents/MCP servers, ">150k context" flag, "4+
parallel sessions" flag) — but it never says **which project** drove the
number, and its percentages aren't independently checkable dollar
figures. This skill fills that gap by reading the per-message token
usage Claude Code already writes into every local session transcript
(`~/.claude/projects/*/*.jsonl`).

## Language

The report renders in Traditional Chinese or English depending on the
shell's locale (`LC_ALL` / `LC_MESSAGES` / `LANG` — first one set wins; a
value starting with `zh` renders Chinese, anything else renders English).
Override with `QUOTA_AUDIT_LANG=zh` or `QUOTA_AUDIT_LANG=en` if the
system locale doesn't reflect what you want. Write your own interpretation
(the prose after the report) in whichever language the user is writing to
you in — that's independent of the report's own language.

## Files

| File | Role |
|---|---|
| `usage_lib.py` | Shared transcript reader + cost model. **All dedup and pricing rules live here** — the two scripts previously copy-pasted this logic and were wrong in both copies. Change it here, never in a caller. |
| `analyze.py` | One time window → per-project / per-skill / per-command ranking, rate-limit hits, anomalies (JSON) |
| `daily.py` | All history → per-calendar-day totals, streaks, all-time rate-limit hits (JSON) |
| `render.py` | Both of the above → the plain-text console report (bilingual, see above) |

## What's real data vs. what's inferred (say this in the report)

- **Real, exact**:
  - token counts (`input`/`output`/`cache_creation`/`cache_read`)
  - which project a session ran in (the transcript's `cwd` field)
  - **which skill each message belongs to** — the `attributionSkill`
    field, present on assistant messages. This is per-message, so it
    catches a skill invoked mid-session, which the session-entry
    `<command-name>` tag cannot.
  - **when a rate limit was actually hit** — the `quotaLimits` field
    (`rateLimitType` `five_hour`/`seven_day`, `status`, `resetsAt`),
    recorded on the assistant message that got rejected, along with the
    `cwd` of the session that was blocked. This is the only
    non-estimated answer to "when did I actually run out".
  - the cache-write TTL split — `usage.cache_creation.{ephemeral_5m,
    ephemeral_1h}_input_tokens`
- **Estimated, not Anthropic's real billing number**: dollar cost, from
  the pricing table in `usage_lib.py` — a snapshot of published rates,
  re-verify before relying on it for anything precise. **Ratios between
  projects are much more trustworthy than the total.** Cross-check the
  total against a fresh `claude -p "/usage"`; if they diverge a lot,
  trust `/usage`.
- **Heuristic, from real token counts**: cache rebuilds. A response that
  wrote at least half of its own context (≥20k tokens) to the cache is
  counted as a rebuild; it is classed "expired" when the gap since the
  session's previous response exceeds that response's recorded cache TTL
  (5m or 1h), otherwise "other" (something invalidated the prefix:
  compaction, a model switch, changed tools or system prompt). The
  token counts and gaps are exact; the cause label is an inference.
- **Not available at all — say so, don't guess**: per-project subagent
  cost. `isSidechain` looked like the right signal but was checked
  against every session file on the machine this was built on
  (`grep -rc '"isSidechain":true' ~/.claude/projects/*/*.jsonl`) and was
  never once `true`. `/usage`'s own coarse "N% of usage came from
  subagent-heavy sessions" is the only number for that dimension.
- **Scope limit**: local machine only, same as `/usage` itself ("does
  not include other devices or claude.ai").

## Three counting rules that must not regress

Each one is a fix for a measured bug; `usage_lib.py`'s docstring holds
the details and the numbers. If a future change makes the totals jump,
suspect these first.

1. **Deduplicate assistant messages by `message.id`.** Claude Code
   writes one line per *content block*, all sharing one `usage` object —
   a response with 19 parallel tool calls becomes 19 identical usage
   records. Naive summing inflated the total by ~2x.
2. **Filter by each message's own `timestamp`, never file mtime.** File
   mtime put a two-week `--resume`d session's entire cost inside a "last
   5 hours" window. mtime is still a safe *prefilter* for skipping whole
   files, and only that.
3. **Price cache writes at their recorded TTL** (5m = 1.25x, 1h = 2x
   base input). A flat 1.25x undercounts whenever most cache writes are
   actually 1h TTL.

## Steps

1. Generate the data and render it. `${CLAUDE_PLUGIN_ROOT}` resolves to
   this plugin's install directory:
   ```bash
   cd /tmp
   python3 "${CLAUDE_PLUGIN_ROOT}"/skills/quota-audit/daily.py             > qa-daily.json
   python3 "${CLAUDE_PLUGIN_ROOT}"/skills/quota-audit/analyze.py --hours 5   > qa-5h.json
   python3 "${CLAUDE_PLUGIN_ROOT}"/skills/quota-audit/analyze.py --hours 24  > qa-24h.json
   python3 "${CLAUDE_PLUGIN_ROOT}"/skills/quota-audit/analyze.py --hours 168 > qa-7d.json
   python3 "${CLAUDE_PLUGIN_ROOT}"/skills/quota-audit/render.py --daily qa-daily.json \
     --window 5h=qa-5h.json --window 24h=qa-24h.json --window 7d=qa-7d.json
   ```
   The calendar's shading uses absolute dollar cutoffs (default
   `1,5,20,60`). If nearly every day renders as `··` or as `██`, re-run
   `render.py` with `--thresholds` scaled to this user's actual spend
   rather than reporting a flat-looking calendar.

   The default report is deliberately short: key findings first, one
   detail block for the longest window only (shorter windows are subsets
   of it), rate-limit hits aggregated with the most recent few, history
   last. Add `--full` to `render.py` only when the user asks for the
   per-window detail of every window, every individual rate-limit hit,
   or the extra all-time stats.
2. Cross-check: run `claude -p "/usage" --output-format json` fresh and
   read `.result` for the live 5h/7d percentages and its own tags. Don't
   force an exact reconciliation — the two measure different things (a
   rolling quota percentage vs. an estimated dollar sum). Its **top
   skills percentages** are the most directly comparable line: they
   should land near this skill's own skill ranking as a share of window
   cost. Flag it only if something is wildly off (e.g. this script sees
   near-zero cost but `/usage` reports heavy use — that means sessions
   are missing locally: another machine or account).
3. Read the report and write the interpretation — **short**. The report
   already opens with its own key-findings block and prints every number,
   so do not restate them. After the pasted report, write at most ~5
   bullets, one line each, leading with the single most useful action.
   No section headings, no recap of the tables, no methodology unless the
   `/usage` cross-check in step 2 turned up a real discrepancy. What to
   look for:
   - **Which project** dominates the 7d window, and whether its cost is
     concentrated in one automation skill or spread across interactive work
   - **The rate-limit hits** — look for a repo that the "most blocked"
     line names far more often than its cost share would predict: that
     is a scheduling collision (several repos' automation firing into
     the same 5h window), not necessarily an expensive repo. The
     time-of-day line shows whether hits cluster.
   - **Anomalies** — state plainly that they do NOT consume quota.
4. **Recommendations — tailor to what was actually found, not a generic
   checklist**; only mention the cases below that the data shows:
   - cost dominated by a named automation skill (e.g. a scheduled agent
     or supervisor loop) → this is by-design automation cost; the lever
     is scheduling frequency/scope, not "a bug to fix"
   - high `>150k` count with few sessions → the lever is context hygiene
     in that workflow: compacting between unrelated tasks, not
     re-reading large files across a long session
   - many cache rebuilds marked "expired" → coming back to a long session
     after a break re-writes its whole context at the cache-write price.
     The lever is to start a new session (or `/compact`) after a long
     break instead of resuming a huge one
   - cache rebuilds marked "other" → something mid-session invalidated the
     cached prefix; look for compaction, model switches, or MCP/tool
     changes in that session
   - repeated 5h hits clustered at the same hour → stagger the
     automation schedules across repos
   - an anomaly entry → close the idle browser tab or kill the polling
     script; it is not a token cost issue
5. **Output goes in the conversation as plain text, never as a published
   Artifact, unless the user asks for one** — this report is meant to be
   read in the terminal. Paste the actual `render.py` output into the
   reply inside a fenced code block; don't just describe it, and don't
   rely on the Bash tool's output being shown to the user (it isn't
   reliably).

## Notes

- Read-only — never touches any project file, config, or schedule. Safe
  to run anytime, from any directory.
- A full scan of a few thousand transcripts takes a few seconds; there
  is no cache and no reason to add one.
- The 5h window approximates, but does not exactly reproduce, the
  account's rolling session-quota boundary — say so if it matters.
  `quota_limit_hits`' `resets_at` is the real boundary.
- Re-run when a spike is suspected rather than trusting one snapshot;
  the per-project ranking shifts a lot day to day.
- The anomaly detector's example wording ("a browser tab or script
  polling a status/dashboard endpoint on a timer") is generic — if the
  user has a specific always-open tool that matches the interval you
  find, name it in your write-up instead of the generic phrasing.

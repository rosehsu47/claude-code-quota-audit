#!/usr/bin/env python3
"""
quota-audit/usage_lib.py — shared transcript reader + cost model for
analyze.py and daily.py.

This module exists because the two scripts MUST agree on three things
that were previously copy-pasted (and were wrong in both copies, see
below). Any change to dedup or pricing belongs here, not in a caller.

Three rules this module enforces, each one a fix for a measured bug:

1. DEDUPLICATE BY `message.id`. Claude Code writes one assistant API
   response as one transcript line PER CONTENT BLOCK — a response with
   19 parallel tool_use blocks becomes 19 lines, each carrying an
   identical copy of the same `usage` object. Summing per line
   multiplies that call's cost by the block count. Measured on this
   machine: 14,380 of 18,895 assistant message ids were repeated, and
   48.1% of the naively-summed cost ($976 of $2,027) was duplicate.
   First occurrence wins; later lines with a seen id are skipped.

2. FILTER BY THE MESSAGE'S OWN `timestamp`, never by file mtime. A
   session file's mtime says when it was last appended to, so a
   `--resume`d session that ran for two weeks would put all fourteen
   days of cost inside a "last 5 hours" window. Measured: the 5h
   window read $345 by file mtime vs $116 by message timestamp.
   (File mtime is still used as a cheap PREFILTER — records are only
   ever appended, so a file whose mtime predates the cutoff cannot
   contain a record after it. That direction is safe; the reverse is
   not.)

3. PRICE CACHE WRITES AT THEIR ACTUAL TTL. The transcript records the
   split in `usage.cache_creation.{ephemeral_5m_input_tokens,
   ephemeral_1h_input_tokens}`. Earlier versions of this skill claimed
   the TTL "isn't recorded" and assumed a flat 1.25x; on this machine
   96.4% of cache-write tokens were 1h TTL, which is 2x, so the flat
   assumption undercounted by ~10%. The flat 1.25x remains only as a
   fallback for records that genuinely lack the breakdown, and those
   tokens are counted and reported so the fallback stays visible.

What is real vs. estimated (callers should repeat this in output):
- REAL: token counts, `cwd` project attribution, `attributionSkill`
  per-message skill attribution, `quotaLimits` rate-limit-hit events.
- ESTIMATED: dollar cost. Pricing below is a snapshot of Anthropic's
  published per-model rates at the time this was written; re-verify
  against current pricing before trusting the absolute number. Ratios
  between projects are far more reliable than the total.
- NOT AVAILABLE: per-project subagent attribution. `isSidechain` was
  checked across every session file on this machine and was never once
  true, so it cannot carry that dimension.
"""
import glob
import json
import os
from datetime import datetime, timezone

# $ per 1M tokens: (input, output, cache-read multiplier of input).
# Snapshot of https://platform.claude.com/docs/en/about-claude/pricing as of
# 2026-10-06 — re-verify before relying on it. Cache reads are 0.1x input
# except where the pricing page says otherwise (Opus 5.5: 0.05x; Fable 5.1
# and Mythos 5.1: 0.025x). Matched by LONGEST prefix, so "claude-opus-5-5"
# is not priced as "claude-opus-5".
PRICING = {
    "claude-fable-5-1": (10.00, 50.00, 0.025),
    "claude-mythos-5-1": (10.00, 50.00, 0.025),
    "claude-fable-5": (10.00, 50.00, 0.1),
    "claude-mythos-5": (10.00, 50.00, 0.1),
    "claude-opus-5-5": (4.00, 20.00, 0.05),
    "claude-opus-5": (5.00, 25.00, 0.1),
    "claude-opus-4-8": (5.00, 25.00, 0.1),
    "claude-opus-4-7": (5.00, 25.00, 0.1),
    "claude-opus-4-6": (5.00, 25.00, 0.1),
    "claude-opus-4-5": (5.00, 25.00, 0.1),
    "claude-sonnet-5-5": (2.00, 10.00, 0.1),
    "claude-sonnet-5": (2.00, 10.00, 0.1),
    "claude-sonnet-4-6": (3.00, 15.00, 0.1),
    "claude-sonnet-4-5": (3.00, 15.00, 0.1),
    "claude-haiku-4-5": (1.00, 5.00, 0.1),
}
DEFAULT_PRICE = PRICING["claude-sonnet-5"]  # fallback when the model string matches no row
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.00
CACHE_WRITE_FALLBACK_MULT = 1.25  # only when the TTL breakdown is absent — see rule 3
LARGE_CONTEXT_THRESHOLD = 150_000  # matches /usage's own ">150k context" flag

# Cache rebuild heuristic: a response that WRITES at least half of its own
# context to the cache re-sent most of the conversation cold, instead of
# reading it from cache. Normal turns write only the new tail. Small
# contexts are skipped — rebuilding them is cheap and noisy.
REBUILD_MIN_CONTEXT = 20_000
REBUILD_MIN_WRITE_SHARE = 0.5
CACHE_TTL_SECONDS = {"5m": 300, "1h": 3600}

TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def price_for(model):
    if not model:
        return DEFAULT_PRICE
    matches = [k for k in PRICING if model.startswith(k)]
    if not matches:
        return DEFAULT_PRICE
    return PRICING[max(matches, key=len)]


def message_cost(usage, model):
    """Returns (cost_usd, cache_write_tokens_priced_by_fallback,
    cache_write_cost_usd, cache_write_ttl). The TTL is "1h" or "5m" for
    whichever carried more of this response's cache writes, or None when
    the transcript has no TTL breakdown."""
    inp, outp, read_mult = price_for(model)
    it = usage.get("input_tokens", 0) or 0
    ot = usage.get("output_tokens", 0) or 0
    cr = usage.get("cache_read_input_tokens", 0) or 0
    cc = usage.get("cache_creation_input_tokens", 0) or 0

    breakdown = usage.get("cache_creation") or {}
    t5 = breakdown.get("ephemeral_5m_input_tokens")
    t1 = breakdown.get("ephemeral_1h_input_tokens")
    if t5 is None and t1 is None:
        write_units = cc * CACHE_WRITE_FALLBACK_MULT
        fallback_tokens = cc
        ttl = None
    else:
        write_units = (t5 or 0) * CACHE_WRITE_5M_MULT + (t1 or 0) * CACHE_WRITE_1H_MULT
        fallback_tokens = 0
        ttl = None if not (t5 or t1) else ("1h" if (t1 or 0) >= (t5 or 0) else "5m")

    write_cost = write_units * inp / 1_000_000
    cost = (it * inp + ot * outp + cr * inp * read_mult) / 1_000_000 + write_cost
    return cost, fallback_tokens, write_cost, ttl


def parse_ts(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def detect_command(text):
    """The slash command a session was STARTED with, from the first user
    message's <command-name> tag (written for both interactive use and
    headless `claude -p "/cmd"`). Session-level and coarse — for what a
    session actually spent its tokens on mid-flight, use the per-message
    `attributionSkill` field instead."""
    import re

    if not text:
        return None
    m = re.search(r"<command-name>([^<]*)</command-name>", text)
    if m:
        return m.group(1).strip() or None
    m = re.match(r"^/(\S+)", text.strip())
    if m:
        return "/" + m.group(1)
    return None


class ScanResult:
    def __init__(self):
        self.messages = []       # one entry per UNIQUE assistant API response
        self.sessions = {}       # transcript path -> session metadata
        self.quota_events = []   # real rate-limit-hit records
        self.stats = {
            "files_seen": 0,
            "files_read": 0,
            "files_skipped_by_mtime_prefilter": 0,
            "assistant_lines_read": 0,
            "duplicate_lines_skipped": 0,
            "cache_write_tokens_priced_by_ttl_fallback": 0,
        }


def scan(root, since=None):
    """Read every transcript under `root`, deduplicated and time-resolved.

    `since` (aware datetime) only prefilters whole files by mtime; callers
    still have to filter `messages` by each record's own `ts`.
    """
    result = ScanResult()
    seen_ids = set()

    for fp in sorted(glob.glob(os.path.join(root, "*", "*.jsonl"))):
        result.stats["files_seen"] += 1
        if since is not None:
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fp), tz=timezone.utc)
            except OSError:
                continue
            if mtime < since:
                result.stats["files_skipped_by_mtime_prefilter"] += 1
                continue
        result.stats["files_read"] += 1

        project = None
        entry_command = None
        first_user_seen = False
        first_ts = None
        last_ts = None
        title = None
        records = 0
        # where this file's own entries start, so the `cwd` backfill below
        # touches only them and stays O(records) rather than O(all records)
        msg_base = len(result.messages)
        quota_base = len(result.quota_events)

        try:
            fh = open(fp, "r", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                records += 1
                if project is None and d.get("cwd"):
                    project = d["cwd"]
                ts = parse_ts(d.get("timestamp"))
                if ts is not None:
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts

                if not first_user_seen and d.get("type") == "user":
                    c = (d.get("message") or {}).get("content")
                    text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                    entry_command = detect_command(text)
                    first_user_seen = True

                if d.get("type") == "ai-title" and d.get("aiTitle"):
                    title = d["aiTitle"]

                quota = d.get("quotaLimits")
                if quota:
                    result.quota_events.append(
                        {
                            "ts": ts,
                            "project": project,
                            "rate_limit_type": quota.get("rateLimitType"),
                            "status": quota.get("status"),
                            "resets_at": quota.get("resetsAt"),
                        }
                    )

                if d.get("type") != "assistant":
                    continue
                result.stats["assistant_lines_read"] += 1

                msg = d.get("message") or {}
                mid = msg.get("id")
                if mid:
                    if mid in seen_ids:
                        result.stats["duplicate_lines_skipped"] += 1
                        continue
                    seen_ids.add(mid)

                usage = msg.get("usage") or {}
                cost, fallback, write_cost, write_ttl = message_cost(usage, msg.get("model"))
                result.stats["cache_write_tokens_priced_by_ttl_fallback"] += fallback
                tokens = {k: (usage.get(k, 0) or 0) for k in TOKEN_KEYS}
                ctx = (
                    tokens["input_tokens"]
                    + tokens["cache_creation_input_tokens"]
                    + tokens["cache_read_input_tokens"]
                )
                result.messages.append(
                    {
                        "session": fp,
                        "project": project,
                        "ts": ts,
                        "cost": cost,
                        "cache_write_cost": write_cost,
                        "cache_write_ttl": write_ttl,
                        "tokens": tokens,
                        "context": ctx,
                        "model": msg.get("model"),
                        "skill": d.get("attributionSkill"),
                    }
                )

        if project is None:
            project = "(unknown cwd — " + os.path.basename(os.path.dirname(fp)) + ")"
        # backfill: `cwd` may only appear after this file's first few records
        for m in result.messages[msg_base:]:
            if m["project"] is None:
                m["project"] = project
        for q in result.quota_events[quota_base:]:
            if q["project"] is None:
                q["project"] = project

        result.sessions[fp] = {
            "project": project,
            "entry_command": entry_command,
            "title": title,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "records": records,
        }

    return result


def session_label(fp, meta):
    """Best available human-readable name for a session: Claude Code's
    auto-generated `ai-title` when the transcript has one (measured on one
    machine: ~62% of >150k-context sessions have it, vs 0.6% of all
    sessions — short-lived/automation sessions rarely live long enough to
    get titled), else the slash command it started with, else a short id
    from its filename."""
    title = meta.get("title")
    if title:
        return title
    cmd = meta.get("entry_command")
    if cmd:
        return cmd
    return "session " + os.path.basename(fp).rsplit(".", 1)[0][:8]


def default_root():
    return os.path.expanduser("~/.claude/projects")

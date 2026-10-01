#!/usr/bin/env python3
"""
quota-audit/analyze.py — per-project / per-command / per-skill Claude Code
cost breakdown for a time window, computed from local session transcripts
under ~/.claude/projects/*/*.jsonl.

Why this exists: `claude -p "/usage"` reports account-wide 5h/7d usage
percentages, but does NOT break them down by project. It does report top
skills as percentages; this script adds the project dimension, dollar
estimates, and the raw rate-limit-hit timeline.

All reading, dedup and pricing live in usage_lib.py — read that module's
docstring for the methodology and for the three measured bugs its rules
exist to prevent (per-content-block double counting, file-mtime
windowing, and flat cache-write pricing that ignored the recorded TTL).

Two attribution dimensions, deliberately kept separate:
- `top_commands_*` is SESSION-level: the slash command a session was
  started with. Coarse, but it answers "which entry point was this".
- `top_skills_*` is MESSAGE-level, from the transcript's own
  `attributionSkill` field. This is the accurate one — it attributes a
  skill used mid-session, which the session-level view cannot see.

Window semantics, stated plainly because the two columns measure
different slices:
- `estimated_cost_usd` counts only messages whose OWN timestamp falls in
  the window.
- `sessions` counts sessions with any activity in the window, including
  a long-running session that started before it. So a session can be
  counted while most of its cost is not.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import usage_lib  # noqa: E402


def rank(d, key="name", limit=None):
    out = sorted(
        ({key: k, "cost_usd": round(v, 4)} for k, v in d.items()),
        key=lambda x: -x["cost_usd"],
    )
    return out[:limit] if limit else out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=24, help="look-back window in hours (default 24)")
    ap.add_argument(
        "--project-root",
        default=usage_lib.default_root(),
        help="root of Claude Code's per-project session storage",
    )
    args = ap.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    scanned = usage_lib.scan(args.project_root, since=cutoff)

    project_cost = defaultdict(float)
    project_tokens = defaultdict(int)
    project_skill_cost = defaultdict(lambda: defaultdict(float))
    project_max_ctx = defaultdict(lambda: defaultdict(int))  # project -> session -> max ctx
    session_cost = defaultdict(float)
    skill_cost = defaultdict(float)
    model_cost = defaultdict(float)

    for m in scanned.messages:
        if m["ts"] is None or m["ts"] < cutoff:
            continue
        p = m["project"]
        project_cost[p] += m["cost"]
        project_tokens[p] += sum(m["tokens"].values())
        session_cost[m["session"]] += m["cost"]
        skill_name = m["skill"] or "(no skill attribution)"
        skill_cost[skill_name] += m["cost"]
        project_skill_cost[p][skill_name] += m["cost"]
        model_cost[m["model"] or "(unknown)"] += m["cost"]
        cur = project_max_ctx[p].get(m["session"], 0)
        if m["context"] > cur:
            project_max_ctx[p][m["session"]] = m["context"]

    # A session belongs to the window if it saw any activity in it. Records are
    # only appended, so last_ts >= cutoff is exactly that test.
    project_sessions = defaultdict(int)
    project_zero_sessions = defaultdict(int)
    project_command_cost = defaultdict(lambda: defaultdict(float))
    command_cost = defaultdict(float)
    session_starts = defaultdict(list)

    for path, s in scanned.sessions.items():
        if s["last_ts"] is None or s["last_ts"] < cutoff:
            continue
        p = s["project"]
        cost = session_cost.get(path, 0.0)
        project_sessions[p] += 1
        if cost <= 1e-7:
            project_zero_sessions[p] += 1
        if s["entry_command"]:
            command_cost[s["entry_command"]] += cost
            project_command_cost[p][s["entry_command"]] += cost
        if s["first_ts"] is not None:
            session_starts[p].append(s["first_ts"])
        project_cost.setdefault(p, 0.0)

    # anomaly detector: many sessions, almost all zero-cost, roughly regular
    # interval. This shape matches a browser tab or script left open polling
    # something (a local dashboard, a status page) that re-spawns a free
    # `claude -p "/usage"`-style call on a timer, forever. These sessions
    # contain no assistant messages at all — they are local command output, so
    # they cost nothing and do not touch the model.
    anomalies = []
    for proj, n in project_sessions.items():
        zero = project_zero_sessions.get(proj, 0)
        if n >= 20 and zero / n > 0.9:
            times = sorted(session_starts.get(proj, []))
            interval_sec = None
            if len(times) >= 3:
                diffs = sorted((b - a).total_seconds() for a, b in zip(times, times[1:]))
                interval_sec = round(diffs[len(diffs) // 2], 1)  # median, robust to gaps
            anomalies.append(
                {
                    "project": proj,
                    "sessions": n,
                    "zero_cost_sessions": zero,
                    "approx_interval_sec": interval_sec,
                    "note": "high session count, near-zero real cost — almost certainly a"
                    " polling/monitoring loop (e.g. a browser tab or script left open"
                    " calling a status/dashboard endpoint on a timer), not real quota"
                    " consumption",
                }
            )

    # Real rate-limit hits. Concurrent sessions each record the same hit, so
    # collapse on (type, resetsAt) — that pair identifies one quota window.
    grouped = {}
    for q in scanned.quota_events:
        if q["ts"] is None or q["ts"] < cutoff:
            continue
        key = (q["rate_limit_type"], q["resets_at"])
        g = grouped.setdefault(
            key,
            {
                "rate_limit_type": q["rate_limit_type"],
                "status": q["status"],
                "first_hit": q["ts"],
                "resets_at": q["resets_at"],
                "projects": set(),
                "records": 0,
            },
        )
        g["records"] += 1
        g["projects"].add(q["project"])
        if q["ts"] < g["first_hit"]:
            g["first_hit"] = q["ts"]
    quota_hits = sorted(
        (
            {
                "rate_limit_type": g["rate_limit_type"],
                "status": g["status"],
                "first_hit": g["first_hit"].isoformat(),
                "resets_at": (
                    datetime.fromtimestamp(g["resets_at"], tz=timezone.utc).isoformat()
                    if g["resets_at"]
                    else None
                ),
                "blocked_projects": sorted(x for x in g["projects"] if x),
                "records": g["records"],
            }
            for g in grouped.values()
        ),
        key=lambda x: x["first_hit"],
    )

    # The specific sessions behind the ">150k" count, named where possible —
    # a bare per-project count can't tell you which actual session blew the
    # context, so this pairs each one with usage_lib.session_label() and its
    # window cost, ranked by window cost: the report asks "what is eating the
    # quota", and the biggest context is not always the most expensive one.
    large_ctx_sessions = []
    for p, sessmap in project_max_ctx.items():
        for sess, ctx in sessmap.items():
            if ctx > usage_lib.LARGE_CONTEXT_THRESHOLD:
                meta = scanned.sessions.get(sess, {})
                large_ctx_sessions.append(
                    {
                        "project": p,
                        "session": usage_lib.session_label(sess, meta),
                        "context_tokens": ctx,
                        "cost_usd": round(session_cost.get(sess, 0.0), 4),
                    }
                )
    large_ctx_sessions.sort(key=lambda x: -x["cost_usd"])

    projects_out = []
    for p in project_cost:
        big = sum(
            1
            for v in project_max_ctx[p].values()
            if v > usage_lib.LARGE_CONTEXT_THRESHOLD
        )
        projects_out.append(
            {
                "project": p,
                "estimated_cost_usd": round(project_cost[p], 4),
                "total_tokens": project_tokens.get(p, 0),
                "sessions": project_sessions.get(p, 0),
                "zero_cost_sessions": project_zero_sessions.get(p, 0),
                "large_context_sessions": big,
                "top_commands": rank(project_command_cost[p], "command", 5),
                "top_skills": rank(project_skill_cost[p], "skill", 5),
            }
        )
    projects_out.sort(key=lambda x: -x["estimated_cost_usd"])

    result = {
        "window_hours": args.hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_start": cutoff.isoformat(),
        "total_estimated_cost_usd": round(sum(project_cost.values()), 4),
        "projects": projects_out,
        "top_commands_overall": rank(command_cost, "command", 15),
        "top_skills_overall": rank(skill_cost, "skill", 15),
        "cost_by_model": rank(model_cost, "model"),
        "large_context_sessions_detail": large_ctx_sessions[:15],
        # Totals over ALL such sessions — the detail list above is capped.
        "large_context_sessions_total": {
            "count": len(large_ctx_sessions),
            "cost_usd": round(sum(s["cost_usd"] for s in large_ctx_sessions), 4),
        },
        "quota_limit_hits": quota_hits,
        "anomalies_high_frequency_zero_cost": anomalies,
        "methodology": {
            "scan": scanned.stats,
            "dedup": "assistant messages deduplicated by message.id — Claude Code"
            " writes one line per content block, all sharing one usage object",
            "windowing": "each message filtered by its own timestamp; sessions"
            " counted if active in the window, so session count and cost measure"
            " different slices",
            "cache_write_pricing": "priced from usage.cache_creation's recorded"
            " 5m/1h TTL split (1.25x / 2x base input); the flat-1.25x fallback"
            " applied to the token count reported in scan stats",
            "cost_is_an_estimate": "cross-check against a live `claude -p /usage`;"
            " trust /usage's percentage over this dollar figure",
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

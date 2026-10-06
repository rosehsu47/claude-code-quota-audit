#!/usr/bin/env python3
"""
quota-audit/daily.py — per-calendar-day usage aggregation across ALL local
session history, for the activity calendar in render.py.

Methodology, dedup and pricing all live in usage_lib.py — see that
module's docstring.

Each message is bucketed by ITS OWN local calendar day. An earlier
version bucketed a whole session onto the day it started, which parked
weeks of a long `--resume`d session's cost on one day and invented
spikes that never happened (it reported 2026-08-28 as a $415 day; by
message timestamp that day was $85 and the real peak was 2026-08-19).

Sessions are still counted on the day they started — that is what a
session count means — so `cost_usd` and `real_sessions` on the same row
deliberately describe different things: the money spent that day, and
the sessions opened that day.

Zero-cost sessions are excluded from "activity" (active days, streaks,
most-active-day). A zero-cost session is real but is either a free local
command like /usage or a polling loop (see the anomaly detector in
analyze.py) re-spawning one every couple of minutes forever. Counting
those would make every day look active and make streaks meaningless.
`total_sessions` is still reported next to `real_sessions` so the gap
stays visible.
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import usage_lib  # noqa: E402


def local_day(ts):
    return ts.astimezone().date()


def main():
    scanned = usage_lib.scan(usage_lib.default_root())

    day_cost = defaultdict(float)
    day_tokens = defaultdict(lambda: defaultdict(int))
    day_started = defaultdict(int)
    day_started_real = defaultdict(int)
    session_cost = defaultdict(float)
    total_tokens = defaultdict(int)
    model_messages = defaultdict(int)
    model_cost = defaultdict(float)
    skill_cost = defaultdict(float)

    for m in scanned.messages:
        if m["ts"] is None:
            continue
        d = local_day(m["ts"]).isoformat()
        day_cost[d] += m["cost"]
        session_cost[m["session"]] += m["cost"]
        for k, v in m["tokens"].items():
            day_tokens[d][k] += v
            total_tokens[k] += v
        if m["model"]:
            model_messages[m["model"]] += 1
            model_cost[m["model"]] += m["cost"]
        skill_cost[m["skill"] or "(no skill attribution)"] += m["cost"]

    longest_session = {"seconds": 0, "date": None, "project": None}
    for path, s in scanned.sessions.items():
        if s["first_ts"] is None:
            continue
        d = local_day(s["first_ts"]).isoformat()
        day_started[d] += 1
        if session_cost.get(path, 0.0) > 1e-7:
            day_started_real[d] += 1
            if s["last_ts"] is not None:
                dur = (s["last_ts"] - s["first_ts"]).total_seconds()
                if dur > longest_session["seconds"]:
                    longest_session = {
                        "seconds": round(dur, 1),
                        "date": d,
                        "project": s["project"],
                    }

    all_days = sorted(set(day_cost) | set(day_started))
    if not all_days:
        print(json.dumps({"error": "no session data found"}))
        return

    active_dates = sorted(d for d, c in day_cost.items() if c > 1e-7)
    streaks = []
    cur_start = prev = None
    for ds in active_dates:
        d = datetime.fromisoformat(ds).date()
        if prev is None or (d - prev).days > 1:
            if cur_start is not None:
                streaks.append((cur_start, prev))
            cur_start = d
        prev = d
    if cur_start is not None:
        streaks.append((cur_start, prev))

    longest_streak = max(streaks, key=lambda s: (s[1] - s[0]).days) if streaks else None
    today = datetime.now().astimezone().date()
    current_streak = 0
    if streaks and (today - streaks[-1][1]).days <= 1:
        current_streak = (streaks[-1][1] - streaks[-1][0]).days + 1

    most_active_day = max(day_cost.items(), key=lambda kv: kv[1]) if day_cost else None
    favorite_model = max(model_cost.items(), key=lambda kv: kv[1])[0] if model_cost else None

    # all-time rate-limit hits, collapsed per quota window (concurrent sessions
    # each record the same hit)
    grouped = {}
    for q in scanned.quota_events:
        if q["ts"] is None:
            continue
        g = grouped.setdefault(
            (q["rate_limit_type"], q["resets_at"]),
            {"type": q["rate_limit_type"], "first_hit": q["ts"], "projects": set(), "sessions": set()},
        )
        g["projects"].add(q["project"])
        g["sessions"].add(q["session"])
        if q["ts"] < g["first_hit"]:
            g["first_hit"] = q["ts"]
    quota_hits = sorted(
        (
            {
                "rate_limit_type": g["type"],
                "first_hit": g["first_hit"].isoformat(),
                "local_date": local_day(g["first_hit"]).isoformat(),
                "blocked_projects": sorted(x for x in g["projects"] if x),
                "blocked_sessions": usage_lib.blocked_sessions(g["sessions"], scanned.sessions),
            }
            for g in grouped.values()
        ),
        key=lambda x: x["first_hit"],
    )

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": {
            d: {
                "date": d,
                "cost_usd": round(day_cost.get(d, 0.0), 4),
                "sessions_started": day_started.get(d, 0),
                "sessions_started_with_cost": day_started_real.get(d, 0),
                "tokens": dict(day_tokens.get(d, {})),
            }
            for d in all_days
        },
        "overall": {
            "span_start": all_days[0],
            "span_end": all_days[-1],
            "span_days": (
                datetime.fromisoformat(all_days[-1]).date()
                - datetime.fromisoformat(all_days[0]).date()
            ).days
            + 1,
            "active_days": len(active_dates),
            "total_sessions": sum(day_started.values()),
            "real_sessions": sum(day_started_real.values()),
            "total_cost_usd": round(sum(day_cost.values()), 4),
            "total_tokens": dict(total_tokens),
            "favorite_model": favorite_model,
            "model_message_counts": dict(model_messages),
            "model_cost_usd": {k: round(v, 4) for k, v in model_cost.items()},
            "top_skills": sorted(
                ({"skill": k, "cost_usd": round(v, 4)} for k, v in skill_cost.items()),
                key=lambda x: -x["cost_usd"],
            )[:15],
            "most_active_day": (
                {"date": most_active_day[0], "cost_usd": round(most_active_day[1], 4)}
                if most_active_day
                else None
            ),
            "longest_session": longest_session if longest_session["date"] else None,
            "longest_streak": (
                {
                    "days": (longest_streak[1] - longest_streak[0]).days + 1,
                    "start": longest_streak[0].isoformat(),
                    "end": longest_streak[1].isoformat(),
                }
                if longest_streak
                else None
            ),
            "current_streak_days": current_streak,
            "quota_limit_hits": quota_hits,
            "scan": scanned.stats,
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

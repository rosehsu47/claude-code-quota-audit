#!/usr/bin/env python3
"""
quota-audit/render.py — plain-text console report. Must stay readable
pasted inside a fenced code block, so: no ANSI colour, no box-drawing
that depends on font, and every column padded for East Asian width.

Calendar layout notes, since the previous one was unreadable:
- Weeks are ROWS, days are columns. A week row has space for a real
  `MM/DD` label; the old week-as-column layout could only fit ONE
  character above each column, so months were rendered as a bare "J",
  "A", "S" that nobody could decode.
- Density levels are ABSOLUTE dollar thresholds, not fractions of the
  period's maximum. Relative shading silently rescales every run, so
  the same block meant a different amount each time, and one outlier
  day flattened everything else to the bottom level.
- All five levels appear in the legend WITH their dollar ranges. The
  old legend printed four glyphs because level 0 was a space.
- `··` means "in range, under $1"; blank means "outside the recorded
  span". The old renderer drew both as a space.

Language: output is either Traditional Chinese or English, chosen by
reading LC_ALL / LC_MESSAGES / LANG (first one set wins) — a value
starting with "zh" renders Chinese, anything else (including unset)
renders English. Override with QUOTA_AUDIT_LANG=zh|en if the system
locale doesn't reflect what you want.

Usage:
  python3 render.py --daily daily.json \
      --window 5h=qa-5h.json --window 24h=qa-24h.json --window 7d=qa-7d.json
"""
import argparse
import json
import os
import unicodedata
from datetime import datetime, timedelta

LEVELS = ["··", "░░", "▒▒", "▓▓", "██"]
# Absolute USD thresholds: a cell shows level i when cost < THRESHOLDS[i].
# Absolute (not a fraction of the period max) so the same block means the same
# amount across runs — but that makes the scale spend-dependent, so it is
# overridable with --thresholds for a much smaller or larger daily spend.
DEFAULT_THRESHOLDS = [1.0, 5.0, 20.0, 60.0]

WEEKDAYS = {
    "zh": ["一", "二", "三", "四", "五", "六", "日"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}

RATE_LIMIT_LABEL = {
    "zh": {"five_hour": "5 小時", "seven_day": "7 天"},
    "en": {"five_hour": "5h", "seven_day": "7d"},
}


def detect_lang():
    override = os.environ.get("QUOTA_AUDIT_LANG", "").strip().lower()
    if override in ("zh", "en"):
        return override
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v.lower().startswith("zh"):
            return "zh"
        if v:
            return "en"
    return "en"


LANG = detect_lang()

# Every user-facing string lives here, keyed the same across both languages,
# so a missing translation fails loudly (KeyError) instead of silently
# falling back to the wrong language.
STR = {
    "title": {
        "zh": " QUOTA AUDIT    {start} ~ {end}({days} 天)",
        "en": " QUOTA AUDIT    {start} ~ {end} ({days} days)",
    },
    "calendar_intro": {
        "zh": "活動日曆  每格 = 當日估計成本(逐訊息時間戳歸日,已依 message.id 去重)",
        "en": "Activity calendar  each cell = that day's estimated cost (bucketed by each message's own timestamp, deduplicated by message.id)",
    },
    "week_start_col": {"zh": "週起始", "en": "week of"},
    "week_total_col": {"zh": "本週", "en": "week $"},
    "limit_col": {"zh": "撞限次數(!=1次)", "en": "limit hits (! = 1 hit)"},
    "limit_hit_count": {"zh": "({n}次)", "en": "({n} hits)"},
    "legend_label": {"zh": "圖例  ", "en": "Legend  "},
    "legend_blank": {"zh": "    空白 = 範圍外", "en": "    blank = outside the recorded span"},
    "legend_mark": {
        "zh": "        ! = 當天實際撞到用量上限(下方有明細)",
        "en": "        ! = an actual rate-limit hit that day (detail below)",
    },
    "top_days_header": {"zh": "  最貴的 {n} 天", "en": "  Top {n} most expensive days"},
    "top_days_line": {
        "zh": "    {date} ({wd})  {cost}   當天開啟 {sessions} 個 session",
        "en": "    {date} ({wd})  {cost}   {sessions} sessions opened that day",
    },
    "overall_header": {"zh": "全期間統計", "en": "All-time stats"},
    "overall_line1": {
        "zh": "  總估計成本 {total}    活躍 {active}/{span} 天    最長連續 {streak} 天(目前 {cur} 天)",
        "en": "  Total estimated cost {total}    active {active}/{span} days    longest streak {streak} days (current {cur} days)",
    },
    "overall_line2": {
        "zh": "  Session {real} 有成本 / {total_sess} 全部(差額是 /usage 之類的免費本機指令,見下方異常)",
        "en": "  Sessions: {real} with cost / {total_sess} total (the gap is free local commands like /usage — see Anomalies below)",
    },
    "overall_line3": {
        "zh": "  Token  input {inp} · output {outp} · cache 讀 {cr} · cache 寫 {cw}   合計 {tot}",
        "en": "  Tokens  input {inp} · output {outp} · cache read {cr} · cache write {cw}   total {tot}",
    },
    "overall_by_model": {"zh": "  依模型  ", "en": "  By model  "},
    "overall_longest_session": {
        "zh": "  最長 session {hrs:.1f} 小時({proj},起於 {date})——這是牆鐘跨度,含 --resume 中斷的時間",
        "en": "  Longest session {hrs:.1f}h ({proj}, started {date}) — wall-clock span, including --resume gaps",
    },
    "limit_hits_header": {
        "zh": "實際撞到用量上限的紀錄(全期間,來自 transcript 的 quotaLimits 欄位)",
        "en": "Actual rate-limit hits (all-time, from the transcript's quotaLimits field)",
    },
    "no_limit_hits": {"zh": "  (這段期間沒有撞到上限)", "en": "  (no rate limit hit in this period)"},
    "limit_line": {
        "zh": "    {time}  {label}額度用盡    當下被擋的 repo: {projects}",
        "en": "    {time}  {label} limit exhausted    repos blocked at the time: {projects}",
    },
    "sep": {"zh": "、", "en": ", "},
    "window_overview_header": {"zh": " 視窗總覽", "en": " WINDOW OVERVIEW"},
    "window_table_header": {
        "zh": {"window": "視窗", "cost": "估計成本", "sessions": "session", "top": "最大宗專案"},
        "en": {"window": "window", "cost": "est. cost", "sessions": "sessions", "top": "top project"},
    },
    "window_detail_header": {"zh": "── {label} ── 依專案", "en": "── {label} ── by project"},
    "window_detail_cols": {
        "zh": {"proj": "專案", "cost": "成本", "sessions": "session", "zero": "零成本", "big": ">150k", "skill": "主要 skill"},
        "en": {"proj": "project", "cost": "cost", "sessions": "sessions", "zero": "zero-cost", "big": ">150k", "skill": "top skill"},
    },
    "top_skill_project": {
        "zh": "{skill} {pct:.0f}%(佔該專案)",
        "en": "{skill} {pct:.0f}% of project",
    },
    "limit_bars_header": {
        "zh": "  這視窗額度花在哪(佔視窗總成本比例 —— 對照 /usage 的「What's using your limits?」)",
        "en": "  What's using this window's quota (share of window's total cost — compare with /usage's \"What's using your limits?\")",
    },
    "limit_bars_unattributed": {
        "zh": "(一般互動,無 skill 歸因)",
        "en": "(general use, no skill)",
    },
    "skill_attr_header": {
        "zh": "  skill 歸因(逐訊息,來自 transcript 的 attributionSkill 欄位)",
        "en": "  Skill attribution (per-message, from the transcript's attributionSkill field)",
    },
    "unattributed": {"zh": "(未歸因)", "en": "(unattributed)"},
    "unattributed_note": {
        "zh": "  ← 一般互動,不屬於任何 skill",
        "en": "  ← general interaction, not tied to any skill",
    },
    "commands_header": {
        "zh": "  session 起始指令(整個 session 的成本記在它的進入點)",
        "en": "  Session entry command (whole session's cost is credited to its entry point)",
    },
    "window_limit_hits_header": {"zh": "  此視窗內實際撞到上限", "en": "  Rate limit hit within this window"},
    "anomaly_line": {
        "zh": "  ⚠ {proj}:{n} 個 session,其中 {zero} 個零成本({interval})",
        "en": "  ⚠ {proj}: {n} sessions, {zero} of them zero-cost ({interval})",
    },
    "anomaly_interval": {"zh": "約每 {sec:.0f} 秒一次", "en": "~every {sec:.0f}s"},
    "anomaly_interval_irregular": {"zh": "頻率不固定", "en": "irregular interval"},
    "anomaly_explain1": {
        "zh": "    這些 session 完全沒有 assistant 訊息——是本機指令輸出(如 /usage),沒有打到模型,不消耗額度。",
        "en": "    These sessions have no assistant messages at all — they're local command output (like /usage), never hit the model, and consume no quota.",
    },
    "anomaly_explain2": {
        "zh": "    典型成因:瀏覽器分頁或腳本每隔數十秒輪詢某個 dashboard / 狀態頁。要處理的是關掉那個分頁或腳本,不是省 token。",
        "en": "    Typical cause: a browser tab or script left open polling a dashboard/status endpoint on a timer. The fix is closing that tab or script, not reducing token usage.",
    },
    "scan_summary": {
        "zh": "掃描:{files} 個 transcript,{lines} 行 assistant 訊息,略過 {dupes} 行重複(同一次 API 回應的多個 content block)",
        "en": "Scanned {files} transcripts, {lines} assistant message lines, skipped {dupes} duplicate lines (multiple content blocks from one API response)",
    },
    "cost_disclaimer": {
        "zh": "成本為估算值,非 Anthropic 實際帳單;cache 寫入依 transcript 記錄的 5m/1h TTL 分別計價",
        "en": "Cost is an estimate, not Anthropic's actual bill; cache writes are priced by the 5m/1h TTL recorded in the transcript",
    },
    "cache_fallback_note": {
        "zh": "({n} tokens 缺 TTL 欄位,退回 1.25x)",
        "en": "({n} tokens lacked the TTL field, fell back to 1.25x)",
    },
}


def t(key, **kw):
    tmpl = STR[key][LANG]
    return tmpl.format(**kw) if kw else tmpl


def cols(key):
    return STR[key][LANG]


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def pad(s, w, align="<"):
    s = str(s)
    fill = max(0, w - width(s))
    if align == ">":
        return " " * fill + s
    return s + " " * fill


def fmt_usd(v, digits=2):
    return f"${v:,.{digits}f}"


def fmt_tok(n):
    n = int(n)
    for unit, div in (("b", 1_000_000_000), ("m", 1_000_000), ("k", 1_000)):
        if n >= div:
            return f"{n/div:.1f}{unit}"
    return str(n)


def short(path, n=1):
    return str(path).rsplit("/", n)[-1]


def level(cost, thresholds):
    for i, th in enumerate(thresholds):
        if cost < th:
            return i
    return len(thresholds)


def legend(thresholds):
    parts = ["%s <%s" % (LEVELS[0], fmt_usd(thresholds[0], 0))]
    for i in range(1, len(thresholds)):
        parts.append(
            "%s %s–%s" % (LEVELS[i], fmt_usd(thresholds[i - 1], 0), fmt_usd(thresholds[i], 0))
        )
    parts.append("%s %s+" % (LEVELS[-1], fmt_usd(thresholds[-1], 0)))
    return "    ".join(parts)


def render_calendar(days, quota_hits, thresholds):
    dates = sorted(days)
    if not dates:
        return "(no data)"
    start = datetime.fromisoformat(dates[0]).date()
    end = datetime.fromisoformat(dates[-1]).date()
    grid_start = start - timedelta(days=start.weekday())

    hits_on = {}
    for h in quota_hits:
        d = h.get("local_date")
        if d:
            hits_on[d] = hits_on.get(d, 0) + 1

    weekdays = WEEKDAYS[LANG]
    lines = []
    head = "  " + pad(t("week_start_col"), 9) + "".join(pad(weekdays[i], 4) for i in range(7))
    lines.append(head + pad(t("week_total_col"), 10, ">") + "  " + t("limit_col"))
    w = grid_start
    while w <= end:
        cells = []
        total = 0.0
        hits = 0
        for i in range(7):
            d = w + timedelta(days=i)
            if d < start or d > end:
                cells.append(pad("", 4))
                continue
            c = days.get(d.isoformat(), {}).get("cost_usd", 0.0)
            total += c
            hits += hits_on.get(d.isoformat(), 0)
            cells.append(pad(LEVELS[level(c, thresholds)], 4))
        mark = ("!" * hits + " " + t("limit_hit_count", n=hits)) if hits else ""
        lines.append(
            "  " + pad(w.strftime("%m/%d"), 9) + "".join(cells)
            + pad(fmt_usd(total, 0), 10, ">") + "  " + mark
        )
        w += timedelta(days=7)
    lines.append("")
    lines.append("  " + t("legend_label") + legend(thresholds) + t("legend_blank"))
    lines.append(t("legend_mark"))
    return "\n".join(lines)


def render_top_days(days, n=5):
    ranked = sorted(days.values(), key=lambda d: -d.get("cost_usd", 0))[:n]
    weekdays = WEEKDAYS[LANG]
    lines = [t("top_days_header", n=n)]
    for d in ranked:
        dt = datetime.fromisoformat(d["date"]).date()
        lines.append(
            t(
                "top_days_line",
                date=dt.strftime("%m/%d"),
                wd=weekdays[dt.weekday()],
                cost=pad(fmt_usd(d["cost_usd"]), 9, ">"),
                sessions=d.get("sessions_started_with_cost", 0),
            )
        )
    return "\n".join(lines)


def render_overall(o):
    tt = o["total_tokens"]
    lines = []
    lines.append(
        t(
            "overall_line1",
            total=fmt_usd(o["total_cost_usd"]),
            active=o["active_days"],
            span=o["span_days"],
            streak=(o.get("longest_streak") or {}).get("days", 0),
            cur=o["current_streak_days"],
        )
    )
    lines.append(
        t(
            "overall_line2",
            real=f"{o['real_sessions']:,}",
            total_sess=f"{o['total_sessions']:,}",
        )
    )
    lines.append(
        t(
            "overall_line3",
            inp=fmt_tok(tt.get("input_tokens", 0)),
            outp=fmt_tok(tt.get("output_tokens", 0)),
            cr=fmt_tok(tt.get("cache_read_input_tokens", 0)),
            cw=fmt_tok(tt.get("cache_creation_input_tokens", 0)),
            tot=fmt_tok(sum(tt.values())),
        )
    )
    by_model = sorted(o.get("model_cost_usd", {}).items(), key=lambda kv: -kv[1])
    lines.append(
        t("overall_by_model") + " · ".join("%s %s" % (k, fmt_usd(v, 0)) for k, v in by_model if v > 0)
    )
    ls = o.get("longest_session")
    if ls:
        lines.append(
            t(
                "overall_longest_session",
                hrs=ls["seconds"] / 3600,
                proj=short(ls["project"]),
                date=ls["date"],
            )
        )
    return "\n".join(lines)


def render_limit_hits(hits):
    if not hits:
        return t("no_limit_hits")
    label = RATE_LIMIT_LABEL[LANG]
    sep = t("sep")
    lines = []
    for h in hits:
        ts = datetime.fromisoformat(h["first_hit"]).astimezone()
        lines.append(
            t(
                "limit_line",
                time=ts.strftime("%m/%d %H:%M"),
                label=label.get(h["rate_limit_type"], h["rate_limit_type"]),
                projects=sep.join(short(p) for p in h["blocked_projects"]) or "-",
            )
        )
    return "\n".join(lines)


def render_window_table(windows):
    labels = cols("window_table_header")
    w_lab, w_cost, w_sess = 8, 12, 10
    lines = [
        pad(labels["window"], w_lab) + pad(labels["cost"], w_cost, ">") + pad(labels["sessions"], w_sess, ">")
        + "   " + labels["top"]
    ]
    lines.append("-" * 62)
    for label, data in windows:
        projs = data.get("projects", [])
        top = projs[0] if projs else None
        n_sess = sum(p["sessions"] for p in projs)
        top_s = "%s (%s)" % (short(top["project"]), fmt_usd(top["estimated_cost_usd"])) if top else "-"
        lines.append(
            pad(label, w_lab)
            + pad(fmt_usd(data.get("total_estimated_cost_usd", 0.0)), w_cost, ">")
            + pad(f"{n_sess:,}", w_sess, ">")
            + "   " + top_s
        )
    return "\n".join(lines)


def render_limit_bars(data, top_n=6, bar_width=20):
    """% of this window's total estimated cost, per skill — the same cut as
    Claude Code's own `/usage` "What's using your limits?" panel, but
    per-project-scriptable and cross-checkable against real token counts.
    Percentage is of THIS SCRIPT's estimated window cost, not of the
    account's actual 5h/7d quota — cross-check against a live
    `claude -p "/usage"` before trusting the absolute split."""
    total = data.get("total_estimated_cost_usd", 0.0)
    if total <= 0:
        return ""
    skills = [s for s in data.get("top_skills_overall", []) if s["cost_usd"] > 0]
    if not skills:
        return ""
    lines = [t("limit_bars_header")]
    for s in skills[:top_n]:
        pct = s["cost_usd"] / total * 100
        filled = round(pct / 100 * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        name = t("limit_bars_unattributed") if s["skill"] == "(no skill attribution)" else s["skill"]
        lines.append("    %s %s %5.1f%%" % (pad(name, 28), bar, pct))
    return "\n".join(lines)


def render_window_detail(label, data):
    cols_lab = cols("window_detail_cols")
    lines = [t("window_detail_header", label=label)]
    w_p, w_c, w_s, w_z, w_b = 30, 11, 9, 11, 8
    lines.append(
        pad(cols_lab["proj"], w_p) + pad(cols_lab["cost"], w_c, ">") + pad(cols_lab["sessions"], w_s, ">")
        + pad(cols_lab["zero"], w_z, ">") + pad(cols_lab["big"], w_b, ">") + "   " + cols_lab["skill"]
    )
    lines.append("-" * 86)
    for p in data.get("projects", []):
        skills = [s for s in p.get("top_skills", []) if s["skill"] != "(no skill attribution)"]
        proj_cost = p["estimated_cost_usd"]
        top_skill = (
            t("top_skill_project", skill=skills[0]["skill"], pct=skills[0]["cost_usd"] / proj_cost * 100)
            if skills and proj_cost > 0
            else "-"
        )
        lines.append(
            pad(short(p["project"]), w_p)
            + pad(fmt_usd(p["estimated_cost_usd"]), w_c, ">")
            + pad(p["sessions"], w_s, ">")
            + pad(p["zero_cost_sessions"], w_z, ">")
            + pad(p["large_context_sessions"], w_b, ">")
            + "   " + top_skill
        )

    skills = [s for s in data.get("top_skills_overall", []) if s["cost_usd"] > 0]
    attributed = [s for s in skills if s["skill"] != "(no skill attribution)"]
    unattributed = sum(s["cost_usd"] for s in skills if s["skill"] == "(no skill attribution)")
    if attributed:
        lines.append("")
        lines.append(t("skill_attr_header"))
        for s in attributed[:6]:
            lines.append("    %s %s" % (pad(s["skill"], 28), pad(fmt_usd(s["cost_usd"]), 10, ">")))
        lines.append(
            "    %s %s%s"
            % (pad(t("unattributed"), 28), pad(fmt_usd(unattributed), 10, ">"), t("unattributed_note"))
        )

    bars = render_limit_bars(data)
    if bars:
        lines.append("")
        lines.append(bars)

    cmds = [c for c in data.get("top_commands_overall", []) if c["cost_usd"] > 0][:5]
    if cmds:
        lines.append("")
        lines.append(t("commands_header"))
        for c in cmds:
            lines.append("    %s %s" % (pad(c["command"], 28), pad(fmt_usd(c["cost_usd"]), 10, ">")))

    hits = data.get("quota_limit_hits", [])
    if hits:
        lines.append("")
        lines.append(t("window_limit_hits_header"))
        lines.append(render_limit_hits(hits))

    for a in data.get("anomalies_high_frequency_zero_cost", []):
        interval = (
            t("anomaly_interval", sec=a["approx_interval_sec"])
            if a.get("approx_interval_sec")
            else t("anomaly_interval_irregular")
        )
        lines.append("")
        lines.append(
            t(
                "anomaly_line",
                proj=short(a["project"]),
                n=a["sessions"],
                zero=a["zero_cost_sessions"],
                interval=interval,
            )
        )
        lines.append(t("anomaly_explain1"))
        lines.append(t("anomaly_explain2"))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", required=True)
    ap.add_argument("--window", action="append", default=[], help="label=path, repeatable")
    ap.add_argument(
        "--thresholds",
        default=",".join(str(th) for th in DEFAULT_THRESHOLDS),
        help="comma-separated ascending USD cutoffs for the calendar's four"
        " shading steps (default %(default)s)",
    )
    args = ap.parse_args()

    thresholds = sorted(float(x) for x in args.thresholds.split(","))
    if len(thresholds) != 4:
        raise SystemExit("--thresholds needs exactly 4 ascending values, got: " + args.thresholds)

    daily = json.load(open(args.daily))
    overall = daily["overall"]
    days = daily["days"]
    windows = []
    for w in args.window:
        label, path = w.split("=", 1)
        windows.append((label, json.load(open(path))))

    bar = "=" * 86
    print(bar)
    print(t("title", start=overall["span_start"], end=overall["span_end"], days=overall["span_days"]))
    print(bar)
    print()
    print(t("calendar_intro"))
    print()
    print(render_calendar(days, overall.get("quota_limit_hits", []), thresholds))
    print()
    print(render_top_days(days))
    print()
    print(t("overall_header"))
    print(render_overall(overall))
    print()
    print(t("limit_hits_header"))
    print(render_limit_hits(overall.get("quota_limit_hits", [])))
    print()
    print(bar)
    print(t("window_overview_header"))
    print(bar)
    print(render_window_table(windows))
    print()
    for label, data in windows:
        print(render_window_detail(label, data))
        print()
    st = overall.get("scan", {})
    print("-" * 86)
    print(
        t(
            "scan_summary",
            files=f"{st.get('files_read', 0):,}",
            lines=f"{st.get('assistant_lines_read', 0):,}",
            dupes=f"{st.get('duplicate_lines_skipped', 0):,}",
        )
    )
    fallback = st.get("cache_write_tokens_priced_by_ttl_fallback")
    print(
        t("cost_disclaimer")
        + ("" if not fallback else t("cache_fallback_note", n=f"{fallback:,}"))
    )


if __name__ == "__main__":
    main()

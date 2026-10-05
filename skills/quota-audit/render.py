#!/usr/bin/env python3
"""
quota-audit/render.py — plain-text console report. Must stay readable
pasted inside a fenced code block, so: no ANSI colour, no box-drawing
that depends on font, and every column padded for East Asian width.

Report layout — conclusion first, history last:
1. Key findings: a handful of computed one-liners for the longest window
   (who dominates, skill vs. general use, >150k sessions, limit hits).
2. Window overview: one row per window.
3. Detail for the LONGEST window only. Shorter windows are subsets of it,
   and repeating the same five sub-tables per window was most of the
   report's length while adding almost nothing. `--full` brings them back.
4. Rate-limit hits, aggregated (by repo, by time of day) plus the most
   recent few. `--full` lists every hit.
5. History: calendar and all-time totals.
The previous layout opened with ~60 lines of all-time history and printed
no conclusion at all, so the reader had to derive it from 150 lines.

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
  python3 render.py --full ...   # per-window detail for every window,
                                 # every rate-limit hit, extra all-time stats
"""
import argparse
import json
import os
import unicodedata
from collections import Counter
from datetime import datetime, timedelta

LEVELS = ["··", "░░", "▒▒", "▓▓", "██"]
# Absolute USD thresholds: a cell shows level i when cost < THRESHOLDS[i].
# Absolute (not a fraction of the period max) so the same block means the same
# amount across runs — but that makes the scale spend-dependent, so it is
# overridable with --thresholds for a much smaller or larger daily spend.
DEFAULT_THRESHOLDS = [1.0, 5.0, 20.0, 60.0]

# analyze.py's bucket name for messages with no attributionSkill.
UNATTRIBUTED = "(no skill attribution)"

RULE_W = 86
RECENT_HITS = 5
HOUR_BUCKETS = [(0, 6), (6, 12), (12, 18), (18, 24)]

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
        "zh": " QUOTA AUDIT    {start} ~ {end}（{days} 天）",
        "en": " QUOTA AUDIT    {start} ~ {end} ({days} days)",
    },
    "sep": {"zh": "、", "en": ", "},
    # --- key findings
    "headline_header": {"zh": "重點（{label} 視窗）", "en": "KEY FINDINGS ({label} window)"},
    "hl_no_cost": {"zh": "{label} 內沒有任何成本", "en": "No cost recorded in the {label} window"},
    "hl_project": {
        "zh": "估計成本 {cost}，其中 {pct:.0f}% 在 {proj}（{pcost}）",
        "en": "Estimated cost {cost}, {pct:.0f}% of it in {proj} ({pcost})",
    },
    "hl_skill_none": {
        "zh": "{pct:.0f}% 是一般互動，不屬於任何 skill",
        "en": "{pct:.0f}% is general interaction, not tied to any skill",
    },
    "hl_skill": {
        "zh": "最大宗 skill 是 {skill}，佔 {pct:.0f}%",
        "en": "Top skill is {skill} at {pct:.0f}%",
    },
    "hl_big": {
        "zh": "{n} 個 session 超過 150k context，合計 {cost}（佔視窗成本 {pct:.0f}%）",
        "en": "{n} sessions crossed 150k context, {cost} combined ({pct:.0f}% of window cost)",
    },
    "hl_rebuilds": {
        "zh": "快取重建 {n} 次，花了 {cost}（佔視窗成本 {pct:.0f}%），其中 {exp} 次是閒置超過快取時效後才回來",
        "en": "{n} cache rebuilds cost {cost} ({pct:.0f}% of window cost); {exp} came after idling past the cache TTL",
    },
    "hl_limits": {
        "zh": "{label} 內撞限 {n} 次；全期間 {total} 次，最常被擋的是 {proj}（{k} 次）",
        "en": "{n} rate-limit hits in {label}; {total} all-time, most often blocking {proj} ({k} times)",
    },
    "hl_no_limits": {"zh": "全期間沒有撞到用量上限", "en": "No rate limit hit all-time"},
    "hl_anomaly": {
        "zh": "{proj} 有 {zero} 個零成本 session 在輪詢——不消耗額度",
        "en": "{proj} has {zero} zero-cost polling sessions — they consume no quota",
    },
    # --- window overview
    "window_overview_header": {"zh": "視窗總覽", "en": "WINDOW OVERVIEW"},
    "window_table_header": {
        "zh": {"window": "視窗", "cost": "估計成本", "sessions": "session", "big": ">150k", "hits": "撞限", "top": "最大宗專案"},
        "en": {"window": "window", "cost": "est. cost", "sessions": "sessions", "big": ">150k", "hits": "hits", "top": "top project"},
    },
    # --- window detail
    "window_detail_header": {"zh": "{label} 明細", "en": "{label} DETAIL"},
    "window_detail_cols": {
        "zh": {"proj": "專案", "cost": "成本", "share": "佔比", "sessions": "session", "zero": "零成本", "big": ">150k", "skill": "主要 skill"},
        "en": {"proj": "project", "cost": "cost", "share": "share", "sessions": "sessions", "zero": "zero-cost", "big": ">150k", "skill": "top skill"},
    },
    "skills_header": {"zh": "  依 skill（逐訊息歸因）", "en": "  By skill (per-message attribution)"},
    "skill_unattributed": {"zh": "（一般互動，無 skill）", "en": "(general use, no skill)"},
    "large_ctx_header": {
        "zh": "  超過 150k context 的 session（依成本排序）",
        "en": "  Sessions that crossed 150k context (by cost)",
    },
    "large_ctx_more": {"zh": "    …另有 {n} 個", "en": "    …and {n} more"},
    "cache_header": {
        "zh": "  Cache 寫入（依 session，依寫入花費排序）\n"
        "    重建 = 單次回應把自己一半以上的 context 重新寫入快取；過期 = 距上一則超過快取時效",
        "en": "  Cache writes by session (by write cost)\n"
        "    rebuild = one response re-wrote over half its context; expired = idle past the cache TTL",
    },
    "cache_cols": {
        "zh": {"write": "寫入花費", "share": "佔比", "rebuilds": "重建（過期/其他）", "rebuild_cost": "重建花費"},
        "en": {"write": "write $", "share": "share", "rebuilds": "rebuilds (exp/other)", "rebuild_cost": "rebuild $"},
    },
    "commands_header": {
        "zh": "  依 session 起始指令（整個 session 的成本記在進入點）",
        "en": "  By session entry command (whole session credited to its entry point)",
    },
    "anomaly_line": {
        "zh": "  ⚠ {proj}：{n} 個 session，其中 {zero} 個零成本（{interval}）",
        "en": "  ⚠ {proj}: {n} sessions, {zero} of them zero-cost ({interval})",
    },
    "anomaly_interval": {"zh": "約每 {sec:.0f} 秒一次", "en": "~every {sec:.0f}s"},
    "anomaly_interval_irregular": {"zh": "頻率不固定", "en": "irregular interval"},
    "anomaly_explain": {
        "zh": "    本機指令輸出（如 /usage），沒打到模型、不耗額度。該處理的是輪詢它的分頁或腳本，不是省 token。",
        "en": "    Local command output (like /usage): never hits the model, costs no quota. Close the tab or script polling it; this is not a token problem.",
    },
    # --- rate-limit hits
    "limits_header": {
        "zh": "撞限紀錄  全期間 {total} 次（{breakdown}）",
        "en": "RATE-LIMIT HITS  {total} all-time ({breakdown})",
    },
    "no_limit_hits": {"zh": "撞限紀錄  全期間沒有撞到上限", "en": "RATE-LIMIT HITS  none all-time"},
    "limits_by_repo": {"zh": "  最常被擋  ", "en": "  Most blocked  "},
    "limits_by_hour": {"zh": "  時段分布  ", "en": "  Time of day   "},
    "limits_recent": {"zh": "  最近 {n} 次", "en": "  Most recent {n}"},
    "limits_all": {"zh": "  全部紀錄", "en": "  All hits"},
    # --- history
    "history_header": {"zh": "歷史  每格 = 當日估計成本", "en": "HISTORY  each cell = that day's estimated cost"},
    "week_start_col": {"zh": "週起始", "en": "week of"},
    "week_total_col": {"zh": "本週", "en": "week $"},
    "limit_col": {"zh": "撞限（!=1 次）", "en": "limit hits (! = 1 hit)"},
    "limit_hit_count": {"zh": "（{n} 次）", "en": "({n} hits)"},
    "legend_label": {"zh": "圖例  ", "en": "Legend  "},
    "legend_blank": {"zh": "    空白 = 範圍外", "en": "    blank = outside the recorded span"},
    "top_days": {"zh": "  最貴的 {n} 天  ", "en": "  Top {n} days  "},
    "overall_line1": {
        "zh": "  總估計成本 {total}    活躍 {active}/{span} 天    最長連續 {streak} 天（目前 {cur} 天）",
        "en": "  Total estimated cost {total}    active {active}/{span} days    longest streak {streak} days (current {cur} days)",
    },
    "overall_line2": {
        "zh": "  Session {real} 有成本 / {total_sess} 全部（差額是 /usage 之類的免費本機指令）",
        "en": "  Sessions: {real} with cost / {total_sess} total (the gap is free local commands like /usage)",
    },
    "overall_line3": {
        "zh": "  Token  input {inp} · output {outp} · cache 讀 {cr} · cache 寫 {cw}   合計 {tot}",
        "en": "  Tokens  input {inp} · output {outp} · cache read {cr} · cache write {cw}   total {tot}",
    },
    "overall_by_model": {"zh": "  依模型  ", "en": "  By model  "},
    "overall_longest_session": {
        "zh": "  最長 session {hrs:.1f} 小時（{proj}，起於 {date}）——這是牆鐘跨度，含 --resume 中斷的時間",
        "en": "  Longest session {hrs:.1f}h ({proj}, started {date}) — wall-clock span, including --resume gaps",
    },
    # --- footer
    "scan_summary": {
        "zh": "掃描 {files} 個 transcript、{lines} 行 assistant 訊息（已依 message.id 去重，略過 {dupes} 行）",
        "en": "Scanned {files} transcripts, {lines} assistant message lines (deduplicated by message.id, {dupes} skipped)",
    },
    "cost_disclaimer": {
        "zh": "成本為估算值，非 Anthropic 實際帳單；專案間的比例比總額可信。撞限時間來自 transcript 的 quotaLimits 欄位，是實際紀錄。",
        "en": "Cost is an estimate, not Anthropic's actual bill; ratios between projects are more reliable than totals. Rate-limit times come from the transcript's quotaLimits field and are exact.",
    },
    "cache_fallback_note": {
        "zh": "（{n} tokens 缺 TTL 欄位，cache 寫入退回 1.25x 計價）",
        "en": " ({n} tokens lacked the TTL field; cache writes fell back to 1.25x)",
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


def truncate(s, w):
    s = str(s)
    if width(s) <= w:
        return s
    out = ""
    for c in s:
        if width(out + c) > w - 1:
            break
        out += c
    return out + "…"


def cell(s, w, align="<"):
    """Truncate then pad — a long name must never push later columns out."""
    return pad(truncate(s, w), w, align)


def section(title):
    return "── " + title + " " + "─" * max(0, RULE_W - 4 - width(title))


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


def blocked_counts(hits):
    c = Counter()
    for h in hits:
        for p in h["blocked_projects"]:
            c[short(p)] += 1
    return c


def render_headline(label, data, overall):
    lines = []
    total = data["total_estimated_cost_usd"]
    projs = data["projects"]
    if total <= 0 or not projs:
        lines.append(t("hl_no_cost", label=label))
    else:
        top = projs[0]
        lines.append(
            t(
                "hl_project",
                cost=fmt_usd(total),
                pct=top["estimated_cost_usd"] / total * 100,
                proj=short(top["project"]),
                pcost=fmt_usd(top["estimated_cost_usd"]),
            )
        )
        skills = [s for s in data["top_skills_overall"] if s["cost_usd"] > 0]
        if skills:
            pct = skills[0]["cost_usd"] / total * 100
            if skills[0]["skill"] == UNATTRIBUTED:
                lines.append(t("hl_skill_none", pct=pct))
            else:
                lines.append(t("hl_skill", skill=skills[0]["skill"], pct=pct))
        big = data["large_context_sessions_total"]
        if big["count"]:
            lines.append(
                t("hl_big", n=big["count"], cost=fmt_usd(big["cost_usd"]), pct=big["cost_usd"] / total * 100)
            )
        rb = data["cache_rebuilds_total"]
        n_rb = rb["after_expiry"] + rb["without_expiry"] + rb["ttl_unknown"]
        if n_rb:
            lines.append(
                t(
                    "hl_rebuilds",
                    n=n_rb,
                    cost=fmt_usd(rb["cost_usd"]),
                    pct=rb["cost_usd"] / total * 100,
                    exp=rb["after_expiry"],
                )
            )

    all_hits = overall["quota_limit_hits"]
    if all_hits:
        proj, k = blocked_counts(all_hits).most_common(1)[0]
        lines.append(
            t("hl_limits", label=label, n=len(data["quota_limit_hits"]), total=len(all_hits), proj=proj, k=k)
        )
    else:
        lines.append(t("hl_no_limits"))

    for a in data["anomalies_high_frequency_zero_cost"]:
        lines.append(t("hl_anomaly", proj=short(a["project"]), zero=a["zero_cost_sessions"]))

    return "\n".join([t("headline_header", label=label)] + ["  • " + ln for ln in lines])


def render_window_table(windows):
    labels = cols("window_table_header")
    w_lab, w_cost, w_sess, w_big, w_hits = 8, 12, 10, 8, 7
    lines = [
        pad(labels["window"], w_lab) + pad(labels["cost"], w_cost, ">") + pad(labels["sessions"], w_sess, ">")
        + pad(labels["big"], w_big, ">") + pad(labels["hits"], w_hits, ">") + "   " + labels["top"]
    ]
    lines.append("-" * RULE_W)
    for label, data in windows:
        projs = data["projects"]
        total = data["total_estimated_cost_usd"]
        n_sess = sum(p["sessions"] for p in projs)
        top_s = "-"
        if projs and total > 0:
            top_s = "%s %.0f%%" % (short(projs[0]["project"]), projs[0]["estimated_cost_usd"] / total * 100)
        lines.append(
            pad(label, w_lab)
            + pad(fmt_usd(total), w_cost, ">")
            + pad(f"{n_sess:,}", w_sess, ">")
            + pad(data["large_context_sessions_total"]["count"], w_big, ">")
            + pad(len(data["quota_limit_hits"]), w_hits, ">")
            + "   " + top_s
        )
    return "\n".join(lines)


def render_projects(data):
    labels = cols("window_detail_cols")
    total = data["total_estimated_cost_usd"]
    w_p, w_c, w_sh, w_s, w_z, w_b = 28, 10, 7, 9, 10, 7
    lines = [
        pad(labels["proj"], w_p) + pad(labels["cost"], w_c, ">") + pad(labels["share"], w_sh, ">")
        + pad(labels["sessions"], w_s, ">") + pad(labels["zero"], w_z, ">") + pad(labels["big"], w_b, ">")
        + "   " + labels["skill"]
    ]
    lines.append("-" * RULE_W)
    for p in data["projects"]:
        skills = [s for s in p["top_skills"] if s["skill"] != UNATTRIBUTED]
        proj_cost = p["estimated_cost_usd"]
        top_skill = (
            "%s %.0f%%" % (skills[0]["skill"], skills[0]["cost_usd"] / proj_cost * 100)
            if skills and proj_cost > 0
            else "-"
        )
        share = "%.0f%%" % (proj_cost / total * 100) if total > 0 else "-"
        lines.append(
            cell(short(p["project"]), w_p)
            + pad(fmt_usd(proj_cost), w_c, ">")
            + pad(share, w_sh, ">")
            + pad(p["sessions"], w_s, ">")
            + pad(p["zero_cost_sessions"], w_z, ">")
            + pad(p["large_context_sessions"], w_b, ">")
            + "   " + top_skill
        )
    return "\n".join(lines)


def render_skills(data, top_n=6, bar_width=20):
    """Dollar cost and share of this window's total estimated cost, per skill
    — the same cut as Claude Code's own `/usage` "What's using your limits?"
    panel. The percentage is of THIS SCRIPT's estimated window cost, not of
    the account's actual 5h/7d quota."""
    total = data["total_estimated_cost_usd"]
    skills = [s for s in data["top_skills_overall"] if s["cost_usd"] > 0]
    if total <= 0 or not skills:
        return ""
    lines = [t("skills_header")]
    for s in skills[:top_n]:
        pct = s["cost_usd"] / total * 100
        filled = round(pct / 100 * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        name = t("skill_unattributed") if s["skill"] == UNATTRIBUTED else s["skill"]
        lines.append(
            "    %s %s %s %5.1f%%" % (cell(name, 26), bar, pad(fmt_usd(s["cost_usd"]), 10, ">"), pct)
        )
    return "\n".join(lines)


def render_large_context_sessions(data, top_n=8):
    sessions = data["large_context_sessions_detail"]
    if not sessions:
        return ""
    lines = [t("large_ctx_header")]
    for s in sessions[:top_n]:
        lines.append(
            "    %s %s %s %s"
            % (
                cell(s["session"], 40),
                cell(short(s["project"]), 18),
                pad(fmt_tok(s["context_tokens"]) + " tok", 11, ">"),
                pad(fmt_usd(s["cost_usd"]), 9, ">"),
            )
        )
    more = data["large_context_sessions_total"]["count"] - min(top_n, len(sessions))
    if more > 0:
        lines.append(t("large_ctx_more", n=more))
    return "\n".join(lines)


def render_cache_writes(data, top_n=8):
    sessions = [s for s in data["cache_write_sessions"] if s["cache_write_cost_usd"] > 0][:top_n]
    if not sessions:
        return ""
    c = cols("cache_cols")
    lines = [
        t("cache_header"),
        "    " + pad("", 34) + " " + pad("", 18) + pad(c["write"], 10, ">") + pad(c["share"], 7, ">")
        + pad(c["rebuilds"], 22, ">") + pad(c["rebuild_cost"], 11, ">"),
    ]
    for s in sessions:
        other = s["rebuilds_without_expiry"] + s["rebuilds_ttl_unknown"]
        n = s["rebuilds_after_expiry"] + other
        rebuilds = "%d (%d/%d)" % (n, s["rebuilds_after_expiry"], other) if n else "-"
        share = "%.0f%%" % (s["cache_write_cost_usd"] / s["cost_usd"] * 100)
        lines.append(
            "    %s %s%s%s%s%s"
            % (
                cell(s["session"], 34),
                cell(short(s["project"]), 18),
                pad(fmt_usd(s["cache_write_cost_usd"]), 10, ">"),
                pad(share, 7, ">"),
                pad(rebuilds, 22, ">"),
                pad(fmt_usd(s["rebuild_cost_usd"]) if n else "-", 11, ">"),
            )
        )
    return "\n".join(lines)


def render_commands(data, top_n=5):
    cmds = [c for c in data["top_commands_overall"] if c["cost_usd"] > 0][:top_n]
    if not cmds:
        return ""
    lines = [t("commands_header")]
    for c in cmds:
        lines.append("    %s %s" % (cell(c["command"], 47), pad(fmt_usd(c["cost_usd"]), 10, ">")))
    return "\n".join(lines)


def render_anomalies(data):
    lines = []
    for a in data["anomalies_high_frequency_zero_cost"]:
        interval = (
            t("anomaly_interval", sec=a["approx_interval_sec"])
            if a.get("approx_interval_sec")
            else t("anomaly_interval_irregular")
        )
        lines.append(
            t(
                "anomaly_line",
                proj=short(a["project"]),
                n=a["sessions"],
                zero=a["zero_cost_sessions"],
                interval=interval,
            )
        )
        lines.append(t("anomaly_explain"))
    return "\n".join(lines)


def render_window_detail(label, data):
    blocks = [
        render_projects(data),
        render_skills(data),
        render_large_context_sessions(data),
        render_cache_writes(data),
        render_commands(data),
        render_anomalies(data),
    ]
    return section(t("window_detail_header", label=label)) + "\n" + "\n\n".join(b for b in blocks if b)


def render_limit_hits(hits, full):
    if not hits:
        return section(t("no_limit_hits"))
    label = RATE_LIMIT_LABEL[LANG]
    sep = t("sep")
    by_type = Counter(h["rate_limit_type"] for h in hits)
    breakdown = " · ".join("%s %d" % (label.get(k, k), n) for k, n in by_type.most_common())
    lines = [section(t("limits_header", total=len(hits), breakdown=breakdown))]

    lines.append(
        t("limits_by_repo") + " · ".join("%s %d" % (p, n) for p, n in blocked_counts(hits).most_common(6))
    )
    hours = [datetime.fromisoformat(h["first_hit"]).astimezone().hour for h in hits]
    lines.append(
        t("limits_by_hour")
        + " · ".join(
            "%02d–%02d %d" % (lo, hi, sum(1 for x in hours if lo <= x < hi)) for lo, hi in HOUR_BUCKETS
        )
    )

    shown = hits if full else hits[-RECENT_HITS:]
    lines.append(t("limits_all") if full else t("limits_recent", n=len(shown)))
    w_label = max(width(v) for v in label.values())
    for h in shown:
        ts = datetime.fromisoformat(h["first_hit"]).astimezone()
        lines.append(
            "    %s  %s  %s"
            % (
                ts.strftime("%m/%d %H:%M"),
                pad(label.get(h["rate_limit_type"], h["rate_limit_type"]), w_label),
                sep.join(short(p) for p in h["blocked_projects"]) or "-",
            )
        )
    return "\n".join(lines)


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
    return "\n".join(lines)


def render_top_days(days, n=3):
    ranked = sorted(days.values(), key=lambda d: -d.get("cost_usd", 0))[:n]
    weekdays = WEEKDAYS[LANG]
    parts = []
    for d in ranked:
        dt = datetime.fromisoformat(d["date"]).date()
        parts.append("%s(%s) %s" % (dt.strftime("%m/%d"), weekdays[dt.weekday()], fmt_usd(d["cost_usd"], 0)))
    return t("top_days", n=len(ranked)) + " · ".join(parts)


def render_overall(o, full):
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
    by_model = sorted(o.get("model_cost_usd", {}).items(), key=lambda kv: -kv[1])
    lines.append(
        t("overall_by_model") + " · ".join("%s %s" % (k, fmt_usd(v, 0)) for k, v in by_model if v > 0)
    )
    if not full:
        return "\n".join(lines)
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
    ap.add_argument(
        "--full",
        action="store_true",
        help="print the detail block for every window (default: longest only),"
        " every rate-limit hit (default: most recent %d) and extra all-time stats" % RECENT_HITS,
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
    all_hits = overall["quota_limit_hits"]

    bar = "=" * RULE_W
    print(bar)
    print(t("title", start=overall["span_start"], end=overall["span_end"], days=overall["span_days"]))
    print(bar)
    print()
    if windows:
        longest = max(windows, key=lambda w: w[1]["window_hours"])
        print(render_headline(longest[0], longest[1], overall))
        print()
        print(section(t("window_overview_header")))
        print(render_window_table(windows))
        print()
        for label, data in windows if args.full else [longest]:
            print(render_window_detail(label, data))
            print()
    print(render_limit_hits(all_hits, args.full))
    print()
    print(section(t("history_header")))
    print(render_calendar(days, all_hits, thresholds))
    print()
    print(render_top_days(days, 5 if args.full else 3))
    print(render_overall(overall, args.full))
    print()
    st = overall.get("scan", {})
    print("-" * RULE_W)
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

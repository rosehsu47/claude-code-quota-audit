# claude-code-quota-audit

**Hit your Claude Code 5-hour or weekly limit and can't tell which project
caused it?** `/usage` only shows account-wide percentages. This plugin shows
Claude Code usage by project, by skill, and by session — and the exact times
you were rate-limited.

A [Claude Code](https://claude.com/claude-code) plugin that answers the
question `claude -p "/usage"` can't: **which project, and which
skill/automation, is actually eating your 5-hour and 7-day quota** — with
real per-session dollar estimates and the exact timeline of when you hit a
rate limit and which repo got blocked.

`/usage` reports account-wide percentages with a few tags (top skills,
">150k context", "4+ parallel sessions") but never breaks them down by
project, and its percentages aren't independently checkable numbers. This
plugin reads the per-message token usage Claude Code already writes to every
local session transcript (`~/.claude/projects/*/*.jsonl`) and turns it into
a per-project, per-skill, per-day breakdown — entirely on your machine.

```
======================================================================================
 QUOTA AUDIT    2026-07-29 ~ 2026-09-10 (44 days)
======================================================================================

KEY FINDINGS (7d window)
  • Estimated cost $147.31, 65% of it in my-app ($95.20)
  • Top skill is ai-work at 54%
  • 11 sessions crossed 150k context, $88.40 combined (60% of window cost)
  • 3 rate-limit hits in 7d; 14 all-time, most often blocking my-app (9 times)

── WINDOW OVERVIEW ───────────────────────────────────────────────────────────────────
window     est. cost  sessions   >150k   hits   top project
--------------------------------------------------------------------------------------
5h            $12.40         5       2      0   my-app 81%
24h           $38.75        21       4      1   my-app 70%
7d           $147.31        99      11      3   my-app 65%

── 7d DETAIL ─────────────────────────────────────────────────────────────────────────
project                           cost  share sessions zero-cost  >150k   top skill
--------------------------------------------------------------------------------------
my-app                          $95.20    65%        7         2      3   fix-tracker 45%
other-repo                      $52.11    35%       92        56       8   ai-work 84%

  By skill (per-message attribution)
    ai-work                    ███████████░░░░░░░░░     $79.55  54.0%
    fix-tracker                ██████░░░░░░░░░░░░░░     $42.84  29.1%
    (general use, no skill)    ███░░░░░░░░░░░░░░░░░     $24.92  16.9%

  Sessions that crossed 150k context (by cost)
    Migrate billing to the new pricer table  my-app              211.4k tok    $21.89
    /fix-tracker                             other-repo          178.2k tok    $11.37
    …and 9 more

── RATE-LIMIT HITS  14 all-time (5h 13 · 7d 1) ───────────────────────────────────────
  Most blocked  my-app 9 · other-repo 7
  Time of day   00–06 1 · 06–12 2 · 12–18 8 · 18–24 3
  Most recent 5
    09/08 16:38  5h  my-app
    09/09 20:49  5h  other-repo, my-app
    ...

── HISTORY  each cell = that day's estimated cost ────────────────────────────────────
  week of  Mon Tue Wed Thu Fri Sat Sun     week $  limit hits (! = 1 hit)
  08/17    ▒▒  ▓▓  ██  ▓▓  ██  ░░  ▓▓        $329  !!!!!! (6 hits)
  08/24    ▓▓  ▒▒  ▓▓  ▓▓  ██  ▓▓  ··        $284  !!!!! (5 hits)
  ...
```

The report leads with its conclusions and details only the longest window;
pass `--full` to `render.py` for every window's detail and every
individual rate-limit hit.

## Install

Inside an interactive Claude Code session:

```
/plugin marketplace add rosehsu47/claude-code-quota-audit
/plugin install quota-audit@rosehsu47
```

Or non-interactively:

```bash
claude plugin marketplace add rosehsu47/claude-code-quota-audit
claude plugin install quota-audit@rosehsu47
```

If the install summary says `Run /reload-plugins to activate`, run that.

## Questions this answers

**Why is my Claude Code usage so high?**
The report's first lines name the project that dominates the last 7 days and
how much of the cost came from sessions that grew past 150k context — usually
the single biggest lever.

**Which project is using my Claude Code quota?**
A per-project table with estimated cost, share of the window, session count
and the top skill in each project.

**When did I actually hit the 5-hour or 7-day rate limit?**
Every rate-limit hit recorded in your local transcripts, summarised by which
repos were blocked and what time of day, plus the most recent ones.

**Is a skill or automation burning my tokens, or is it me?**
Per-message skill attribution splits cost between named skills and general
interactive use.

**Does this send my data anywhere?**
No. It only reads `~/.claude/projects/*/*.jsonl` on your machine.

## Use

Just ask, in whichever language you're already talking to Claude in:

- "who's eating my quota"
- "why did my usage spike"
- "which repo is burning through my 5-hour limit"
- 「為什麼 quota 突然爆量」／「token 都花在哪」／「額度都被誰用掉」

Claude Code will match the `quota-audit` skill's description and run it. You
can also invoke it explicitly as `/quota-audit`.

Or call the skill yourself
```
/quota-audit:quota-audit
```

## What you get

- **Conclusions first**: the report opens with a few computed key
  findings (which project dominates, skill vs. general use, how much the
  >150k-context sessions cost, how often you hit a limit), then one
  overview row per window, then detail for the longest window. Rate-limit
  hits are summarised by repo and time of day. `--full` prints everything.
- **Real, exact**: token counts, which project/repo each session ran in,
  which skill each *message* belongs to (not just which command a session
  started with), and the exact moment a 5h or 7d rate limit was actually
  hit — with which repos were blocked at the time.
- **Estimated**: dollar cost, from a pricing snapshot baked into the
  plugin. Treat the ratios between projects as reliable; re-verify the
  absolute total against a live `claude -p "/usage"`.
- **Not available**: per-project subagent cost — `/usage`'s own coarse
  "N% from subagent-heavy sessions" is the only number for that.
- **An anomaly check** for polling/monitoring loops (a browser tab or
  script left open, calling something every minute or two) that inflate
  session counts without spending any real quota — so you don't chase a
  phantom cost.
- **A per-skill quota breakdown**: what share of the window's estimated
  cost each skill accounts for, in dollars and percent — the same cut as
  `/usage`'s own "What's using your limits?" panel, but cross-checkable
  against real token counts instead of an opaque percentage.
- **Named large-context sessions**: which specific sessions crossed the
  >150k-context threshold, not just a per-project count, most expensive
  first — named by Claude Code's own auto-generated session title where
  the transcript has one, else the entry command or a short session id.

## Language

The report table renders in Traditional Chinese or English, detected from
your shell's `LC_ALL` / `LC_MESSAGES` / `LANG`. Force it with
`QUOTA_AUDIT_LANG=zh` or `QUOTA_AUDIT_LANG=en`.

## Privacy / scope

Read-only. It only reads your local `~/.claude/projects/*/*.jsonl`
transcripts and never writes to them or anything else; nothing is sent
anywhere. Same scope limit as `/usage` itself: local machine only, not
other devices or claude.ai.

## License

MIT — see [LICENSE](LICENSE).

---

# claude-code-quota-audit（中文說明）

**Claude Code 的 5 小時或每週額度用完了，卻不知道是哪個專案造成的？**
`/usage` 只給帳號層級的百分比。這個小工具把 Claude Code 用量拆到專案、
skill、session，並列出你實際撞到額度上限的時間點。

一個 [Claude Code](https://claude.com/claude-code) skill，回答 `claude -p
"/usage"` 答不出來的問題：**到底是哪個專案、哪個 skill/自動化，在吃掉你的
5 小時 / 7 天額度**——附上每個 session 的實際估算花費，以及你真正撞到額度上限
的確切時間點、當下被擋的是哪個 repo。

`/usage` 只會給帳號層級的百分比，加一些標籤（常用 skill、「>150k context」、
「4+ 平行 session」），但從不拆分到專案層級，而且它的百分比也無法獨立驗證。
這個小工具讀取 Claude Code 本來就會寫進每個本機 session transcript
（`~/.claude/projects/*/*.jsonl`）裡的逐訊息 token 用量，把它整理成按專案、
按 skill、按日的明細——完全在你自己的機器上運算，不會把任何資料送出去。

## 安裝

在互動式 Claude Code session 裡：

```
/plugin marketplace add rosehsu47/claude-code-quota-audit
/plugin install quota-audit@rosehsu47
```

或非互動式：

```bash
claude plugin marketplace add rosehsu47/claude-code-quota-audit
claude plugin install quota-audit@rosehsu47
```

如果安裝結果顯示 `Run /reload-plugins to activate`，就執行那個指令。

## 這個小工具回答的問題

**為什麼我的 Claude Code 用量這麼高？**
報表開頭幾行就點名過去 7 天佔最大宗的專案，以及有多少成本來自超過
150k context 的 session——這通常是最大的槓桿。

**是哪個專案在吃我的 Claude Code 額度？**
依專案列出估算成本、佔視窗的比例、session 數，以及各專案最主要的 skill。

**我到底是什麼時候撞到 5 小時 / 7 天上限的？**
本機 transcript 裡記錄的每一次撞限，依被擋的 repo 和時段彙總，並列出
最近幾次。

**是 skill 或自動化在燒 token，還是我自己？**
逐訊息的 skill 歸因，把成本拆成具名 skill 和一般互動兩邊。

**資料會被傳出去嗎？**
不會。只讀取你機器上的 `~/.claude/projects/*/*.jsonl`。

## 使用方式

直接用你平常跟 Claude 對話的語言問就好：

- 「為什麼 quota 突然爆量」
- 「token 都花在哪」
- 「額度都被誰用掉」
- "who's eating my quota" / "why did my usage spike"

Claude Code 會依 `quota-audit` skill 的描述自動匹配並執行。也可以直接打
`/quota-audit` 明確呼叫。

## 拿到什麼

- **結論先講**：報表開頭就是幾行算出來的重點（哪個專案佔最大宗、是 skill
  還是一般互動、超過 150k context 的 session 花了多少、撞限幾次），接著每個
  視窗一列總覽，再來才是最長視窗的明細。撞限紀錄會依 repo 和時段彙總。
  要看每個視窗的明細和每一筆撞限紀錄，給 `render.py` 加 `--full`。
- **真實、精確的資料**：token 數量、每個 session 跑在哪個專案/repo、每則
  *訊息* 各自屬於哪個 skill（不只是 session 用什麼指令開頭）、以及真正撞到
  5 小時或 7 天額度上限的確切時刻——附上當下被擋的是哪些 repo。
- **估算值**：美金成本，來自工具內建的定價快照。專案之間的**比例**比總額
  可信得多；要驗證絕對數字，拿即時的 `claude -p "/usage"` 對照。
- **拿不到的**：每個專案的 subagent 花費——`/usage` 自己那個粗略的
  「N% 用量來自 subagent 密集的 session」是唯一有的數字。
- **異常偵測**：抓出輪詢/監控迴圈（瀏覽器分頁或腳本開著，每一兩分鐘打一次）
  造成 session 數暴增但實際不花錢的狀況，讓你不會追著一個不存在的成本跑。
- **skill 花費佔比**：視窗裡各 skill 各佔多少估算成本（金額與百分比並列）
  ——跟 `/usage` 自己的「What's using your limits?」面板是同一種
  切法，但可以拿真實 token 數字對照驗證，不是一個看不出算法的百分比。
- **具名的 large-context session**：不只是每個專案有幾個 session 超過
  150k context，而是哪幾個 session，依成本由高到低——優先用 Claude Code 自動產生的 session
  標題命名，沒有的話退回進入指令或 session id 短碼。

## 語言

報表本身用繁體中文還是英文顯示，取決於你 shell 的 `LC_ALL` /
`LC_MESSAGES` / `LANG` 設定自動偵測。想強制指定就設
`QUOTA_AUDIT_LANG=zh` 或 `QUOTA_AUDIT_LANG=en`。

## 隱私 / 範圍

唯讀。只會讀取你本機的 `~/.claude/projects/*/*.jsonl` transcript，不會寫入
它們或任何其他東西，也不會把任何資料傳到外部。範圍限制跟 `/usage` 本身一樣：
只看這台機器，不包含其他裝置或 claude.ai 上的用量。

## 授權

MIT——見 [LICENSE](LICENSE)。

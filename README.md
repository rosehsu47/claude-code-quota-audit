# claude-code-quota-audit

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

Activity calendar  each cell = that day's estimated cost ...

  week of  Mon Tue Wed Thu Fri Sat Sun     week $  limit hits (! = 1 hit)
  08/17    ▒▒  ▓▓  ██  ▓▓  ██  ░░  ▓▓        $329  !!!!!! (6 hits)
  08/24    ▓▓  ▒▒  ▓▓  ▓▓  ██  ▓▓  ··        $284  !!!!! (5 hits)
  ...

Actual rate-limit hits (all-time, from the transcript's quotaLimits field)
    08/19 16:38  5h limit exhausted    repos blocked at the time: my-app
    08/21 20:49  5h limit exhausted    repos blocked at the time: other-repo, my-app
    ...

── 7d ── by project
project                              cost sessions  zero-cost   >150k   top skill
--------------------------------------------------------------------------------------
my-app                             $95.20        7          2       3   fix-tracker 45% of project
other-repo                         $52.11       92         56       8   ai-work 84% of project

  What's using this window's quota (share of window's total cost — compare with /usage's "What's using your limits?")
    ai-work                     ████████████████░░░░  80.4%
    fix-tracker                 ████░░░░░░░░░░░░░░░░  18.5%
    (general use, no skill)     ░░░░░░░░░░░░░░░░░░░░   1.1%
```

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
- **A per-skill quota breakdown per window**: what share of a given 5h/7d
  window's estimated cost each skill accounts for — the same cut as
  `/usage`'s own "What's using your limits?" panel, but cross-checkable
  against real token counts instead of an opaque percentage.

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

# claude-code-quota-audit(中文說明)

一個 [Claude Code](https://claude.com/claude-code) 外掛,回答 `claude -p
"/usage"` 答不出來的問題:**到底是哪個專案、哪個 skill/自動化,在吃掉你的
5 小時 / 7 天額度**——附上每個 session 的實際估算花費,以及你真正撞到額度上限
的確切時間點、當下被擋的是哪個 repo。

`/usage` 只會給帳號層級的百分比,加一些標籤(常用 skill、">150k context"、
"4+ 平行 session"),但從不拆分到專案層級,而且它的百分比也無法獨立驗證。
這個外掛讀取 Claude Code 本來就會寫進每個本機 session transcript
(`~/.claude/projects/*/*.jsonl`)裡的逐訊息 token 用量,把它整理成按專案、
按 skill、按日的明細——完全在你自己的機器上運算,不會把任何資料送出去。

## 安裝

在互動式 Claude Code session 裡:

```
/plugin marketplace add rosehsu47/claude-code-quota-audit
/plugin install quota-audit@rosehsu47
```

或非互動式:

```bash
claude plugin marketplace add rosehsu47/claude-code-quota-audit
claude plugin install quota-audit@rosehsu47
```

如果安裝結果顯示 `Run /reload-plugins to activate`,就執行那個指令。

## 使用方式

直接用你平常跟 Claude 對話的語言問就好:

- 「為什麼 quota 突然爆量」
- 「token 都花在哪」
- 「額度都被誰用掉」
- "who's eating my quota" / "why did my usage spike"

Claude Code 會依 `quota-audit` skill 的描述自動匹配並執行。也可以直接打
`/quota-audit` 明確呼叫。

## 拿到什麼

- **真實、精確的資料**:token 數量、每個 session 跑在哪個專案/repo、每則
  *訊息* 各自屬於哪個 skill(不只是 session 用什麼指令開頭)、以及真正撞到
  5 小時或 7 天額度上限的確切時刻——附上當下被擋的是哪些 repo。
- **估算值**:美金成本,來自外掛內建的定價快照。專案之間的**比例**比總額
  可信得多;要驗證絕對數字,拿即時的 `claude -p "/usage"` 對照。
- **拿不到的**:每個專案的 subagent 花費——`/usage` 自己那個粗略的
  「N% 用量來自 subagent 密集的 session」是唯一有的數字。
- **異常偵測**:抓出輪詢/監控迴圈(瀏覽器分頁或腳本開著,每一兩分鐘打一次)
  造成 session 數暴增但實際不花錢的狀況,讓你不會追著一個不存在的成本跑。
- **每個視窗的 skill 花費佔比**:某個 5 小時/7 天視窗裡,各 skill 各佔多少
  估算成本——跟 `/usage` 自己的「What's using your limits?」面板是同一種
  切法,但可以拿真實 token 數字對照驗證,不是一個看不出算法的百分比。

## 語言

報表本身用繁體中文還是英文顯示,取決於你 shell 的 `LC_ALL` /
`LC_MESSAGES` / `LANG` 設定自動偵測。想強制指定就設
`QUOTA_AUDIT_LANG=zh` 或 `QUOTA_AUDIT_LANG=en`。

## 隱私 / 範圍

唯讀。只會讀取你本機的 `~/.claude/projects/*/*.jsonl` transcript,不會寫入
它們或任何其他東西,也不會把任何資料傳到外部。範圍限制跟 `/usage` 本身一樣:
只看這台機器,不包含其他裝置或 claude.ai 上的用量。

## 授權

MIT——見 [LICENSE](LICENSE)。

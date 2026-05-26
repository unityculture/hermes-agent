---
name: morning-briefing-push
description: "Compose and push the daily morning briefing to LINE. Fetches today's briefing.json from unityculture/My-twins, formats a 4-section text message, outputs it for Hermes LINE delivery. Triggered by Hermes cron at 08:00 Asia/Taipei."
version: 0.1.0
author: Nuway (Sheng Lin)
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Inbox, Knowledge-Base, Second-Brain, LINE, MyTWINS, Personal, Briefing]
    related_skills: [github-auth, inbox-collector]
---

# MyTWINS Morning Briefing Push

Daily 08:00 Asia/Taipei push. Compose a briefing from
`unityculture/My-twins`'s `inbox/digest/<TODAY>-briefing.json` and deliver via
LINE. Briefing structure is produced by the upstream `/digest` workflow
(`meta/workflow-raw消化.md` in MyTWINS), this skill is **read-only on the KB**
and **does not write back**.

## When to trigger

- Hermes cron `0 0 * * *` UTC (= 08:00 Asia/Taipei), `--deliver line`.
- Manual invocation by the user ("跑一次今天的晨報" / "show briefing").
- **Do NOT trigger** on arbitrary user messages.

## Prerequisites

- `GITHUB_TOKEN` (set in `/opt/data/.env`, repo scope on
  `unityculture/My-twins`)
- `MYTWINS_REPO` env, default `unityculture/My-twins`

## Steps

### 1. Compute today's Asia/Taipei date

```bash
TODAY=$(TZ=Asia/Taipei date +%Y-%m-%d)
WEEKDAY=$(TZ=Asia/Taipei date +%u)   # 1=Mon ... 7=Sun
# Map weekday to Chinese:  1→週一 2→週二 ... 7→週日
WEEKDAY_CH=$(TZ=Asia/Taipei date +%u | awk '{
  split("週一,週二,週三,週四,週五,週六,週日", a, ",");
  print a[$1]
}')
```

### 2. Fetch today's briefing.json

```bash
REPO="${MYTWINS_REPO:-unityculture/My-twins}"
BRIEFING_PATH="inbox/digest/${TODAY}-briefing.json"

RAW=$(curl -fsS \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${REPO}/contents/${BRIEFING_PATH}" \
  | jq -r '.content' | base64 -d 2>/dev/null)
```

If 404 / empty → send fallback (see §Failure modes) and stop.

### 3. Parse and format

Parse JSON with `jq`. Required fields (defined in MyTWINS
`meta/workflow-raw消化.md` §Step 5.5):

- `focus_projects: string[]`
- `top_picks: [{title, source, url, why_now, related_project, raw_path}]`
- `cross_pollination: [{old_item, current_work, suggestion}]`
- `new_arrivals: [{title, url, one_liner, raw_path}]`
- `todos: [{text, project, priority}]`

Build the LINE message using this template. **Skip sections with empty
arrays** — do not output empty headers.

```
☀️ 早安！今天是 <TODAY> (<WEEKDAY_CH>)

🔥 今天值得先讀 (<N> 篇)

<for each top_picks[i]>
<i+1>. <title>
   <why_now>
   → <basename(related_project)>
   <url>

</for>
🔗 跨領域連結

<for each cross_pollination[i]>
• <suggestion>
  舊：<basename(old_item)>
  新：<basename(current_work)>

</for>
📥 昨天新到 (<N> 篇)
<for each new_arrivals[i]>
• <title> — <one_liner>
</for>

📋 待辦 top <N>
<for each todos[i]>
• [<basename_without_ext(project)>] <text>
</for>
```

- `basename(path)` = strip directories; e.g. `projects/nuway/kinyo/顧問服務執行.md`
  → `顧問服務執行.md`. `basename_without_ext` further strips `.md`.
- Keep total message under 4500 chars (LINE per-bubble cap 5000).
- If empty after removing empty sections (all arrays empty): send
  `☀️ 早安！今天是 <TODAY>\n\n📦 庫存無待辦、無新到、無關聯。今天輕鬆過。`

### 4. Output

Print the composed message as the agent's final response. Hermes' `--deliver line`
on the cron job will push it to `LINE_HOME_CHANNEL`.

**Do NOT** wrap in code blocks, JSON, or markdown — output raw text only.
**Do NOT** add commentary like "Here is your briefing:" before/after.

## Failure modes

| Condition | Action |
|-----------|--------|
| `briefing.json` 404 (not produced yet) | Output: `☀️ 早安！今天是 <TODAY>\n\n⚠️ 今日晨報未產（檢查 /digest 排程是否跑完）。` |
| GitHub API auth error | Output: `☀️ 早安！\n\n❌ 無法讀取 MyTWINS（GitHub auth 失敗，檢查 GITHUB_TOKEN）。` |
| `jq` parse error / malformed JSON | Output: `☀️ 早安！\n\n⚠️ 晨報資料格式錯誤，請檢查 inbox/digest/<TODAY>-briefing.json。` |

In all failure modes, DO send a message — silent failure means user thinks
the bot is dead.

## Hard rules

- **Read-only on MyTWINS** — this skill does NOT commit to the repo
  (the inbox-collector skill is the only writer; the /digest workflow is
  the only KB compiler)
- **Output is the final LINE message** — no preamble, no JSON, no metadata
- **Skip empty sections** — don't output an empty header just to keep
  structure; the goal is signal, not template completeness
- **Honor 4500-char cap** — if content overflows, truncate
  `new_arrivals` then `todos` first (preserve top_picks + cross_pollination)
- **Date is Asia/Taipei** — the user wakes up in Taipei time;
  `TZ=Asia/Taipei date` everywhere

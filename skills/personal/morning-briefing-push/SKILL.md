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

Parse JSON with `jq`. Fields (briefing.json carries **human-ready** values —
the digest workflow already converted paths to labels and wrote plain-language
insight; your job is only layout, not translation):

- `top_picks: [{title, why_now, related_label, source, url}]`
- `cross_pollination: [{insight}]`  ← one plain sentence each
- `new_arrivals: [{title, one_liner}]`
- `todos: [{text, project_label}]`

Build the LINE message with this template. **Skip any section whose array is
empty** — no empty headers.

```
☀️ 早安！6/15（週一）

🔥 今天先讀
1. <title>（<related_label>）
   <why_now>
   <url — see URL rule>
2. <title>（<related_label>）
   <why_now>

🔗 可以串起來
• <insight>

📥 昨天新到
• <title> — <one_liner>

✅ 待辦
• <project_label>：<text>
```

### Formatting rules (these fix the past UX complaints — follow exactly)

1. **絕不輸出檔名或路徑**。用 `related_label` / `project_label`（已是人話，如「WrenAI 合約」「個人品牌」）。看到任何 `.md` 出現在你要送的訊息裡 = 錯誤，拿掉。
2. **URL 規則**：每篇 pick 的 `url` 放在 why_now 下一行，但**只在 url 長度 ≤ 80 字元時才放**；超過（多為 percent-encoded 的長 slug，像 LinkedIn 中文貼文）→ **整條省略**，不要貼那串 %E5%A5 亂碼。new_arrivals 與 todos **一律不放 url**。
3. **跨領域連結只送 `insight` 那一句人話**。不要「舊：/新：」、不要檔名、不要「backlink」「related_projects」這種 KB 維護術語。
4. 標題用換行分層，不要 markdown 符號（`#`、`*`、`-` bullet 用 `•`）。
5. 全文 ≤ 4500 字元；超過先砍 new_arrivals 再砍 todos，保住 top_picks + 跨領域連結。
6. 全空（所有 array 皆空）：送 `☀️ 早安！6/15（週一）\n\n📦 今天無新素材、無待辦。輕鬆過。`

### 4. Output

把組好的訊息當「最終回覆」直接輸出，cron 的 `--deliver line` 會推到 `LINE_HOME_CHANNEL`。

**禁止**：code block、JSON、markdown 語法、前言、結尾系統語。只送乾淨人話訊息本身。

⚠️ **你的回覆第一個字元必須是 `☀️`**。不准在前面加任何 meta 說明 —— 不要報字數、不要說「well within the limit」、不要「Here's the final message」、不要解釋你做了什麼。這些自述會被一字不漏推到使用者 LINE。組好訊息 = 直接吐訊息，第一個字就是 ☀️，最後一個字是待辦最後一項，中間沒有任何旁白。

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

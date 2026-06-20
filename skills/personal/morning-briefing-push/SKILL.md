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

Daily 08:00 Asia/Taipei push. This skill **produces** today's briefing and
delivers it via LINE — in one run:

1. Scan the MyTWINS KB for what matters today (recently digested items, open
   todos, steward suggestions).
2. Assemble `inbox/digest/<TODAY>-briefing.json` per `meta/briefing-schema.md`
   (human-ready values — labels not paths, plain-language insight).
3. Commit it to the KB, then format + deliver the LINE message.

This is the producer of `briefing.json` (the old cloud `/digest` that used to
produce it was retired 2026-06-19). The only KB file this skill writes is
`inbox/digest/<TODAY>-briefing.json` — it reads broadly but writes nothing else.

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

### 2. Assemble today's briefing.json from the KB

You build `briefing.json`. Read these sources via the GitHub API (use `kb-query`
skill's read helpers), then fill the schema in `meta/briefing-schema.md`. Every
value must be **human-ready** — labels not paths, plain sentences not KB jargon.

Sources → fields (best-effort; skip any section that comes up empty):

| Field | Where to look | How to fill |
|-------|---------------|-------------|
| `new_arrivals` | `inbox/raw/` files with `status: processed` whose `collected` is within the last ~24h | `title` + `one_liner` (= the file's `one_line_summary`) |
| `top_picks` | the 1-3 most worth-reading of those new arrivals (or recent high-value ones) | `title`, `why_now` (one plain reason to read it today), `related_label` (the bucket it touches, e.g.「WrenAI 合約」), `source`, `url` |
| `cross_pollination` | a new arrival whose `concept_tags` overlap an existing KB theme | one plain sentence each — no「舊/新」, no filenames, no「backlink」 |
| `todos` | open `- [ ]` lines in `**/TODO.md` | `text` + `project_label` (the folder's human name) |
| `steward` | `inbox/digest/steward-latest.md` | 0-3 plain sentences condensing steward's pending suggestions |

Keep the analysis lightweight — this runs at 08:00, not a deep graph pass. If a
source is hard to read or empty, leave that array empty rather than guessing.

Then commit it (this is the ONLY file this skill writes):

```bash
REPO="${MYTWINS_REPO:-unityculture/My-twins}"
BRIEFING_PATH="inbox/digest/${TODAY}-briefing.json"

# BRIEFING_JSON = the assembled JSON string (must validate against meta/briefing-schema.md)
B64_JSON=$(printf '%s' "$BRIEFING_JSON" | base64)
# include sha if the file already exists today (idempotent re-run)
SHA=$(curl -fsS -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${REPO}/contents/${BRIEFING_PATH}" | jq -r '.sha // empty')
curl -fsS -X PUT \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${REPO}/contents/${BRIEFING_PATH}" \
  -d "$(jq -nc --arg msg "briefing: ${TODAY} 晨報" --arg b64 "$B64_JSON" --arg sha "$SHA" \
    'if $sha == "" then {message:$msg, content:$b64, branch:"main"} else {message:$msg, content:$b64, sha:$sha, branch:"main"} end')"

RAW="$BRIEFING_JSON"   # feed straight into step 3 formatting, no re-fetch needed
```

If the KB scan yields nothing at all (no arrivals, no todos, no steward note) →
write an empty-but-valid briefing.json and send the all-empty greeting (step 3
rule 6).

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
| KB scan yields nothing (no arrivals / todos / steward note) | Write an empty-but-valid briefing.json, then output the all-empty greeting (step 3 rule 6) — this is normal, not an error |
| GitHub API auth error | Output: `☀️ 早安！\n\n❌ 無法讀取 MyTWINS（GitHub auth 失敗，檢查 GITHUB_TOKEN）。` |
| Commit of briefing.json fails (write error) | Still deliver the briefing you assembled from memory — a missed write beats a missed briefing. Output the formatted message anyway |

In all failure modes, DO send a message — silent failure means user thinks
the bot is dead.

## Hard rules

- **Writes exactly one file** — `inbox/digest/<TODAY>-briefing.json`, nothing
  else. You read across the KB to build it, but the only commit you make is that
  one briefing file. No edits to raw, notes, or any other path.
- **Output is the final LINE message** — no preamble, no JSON, no metadata
- **Skip empty sections** — don't output an empty header just to keep
  structure; the goal is signal, not template completeness
- **Honor 4500-char cap** — if content overflows, truncate
  `new_arrivals` then `todos` first (preserve top_picks + cross_pollination)
- **Date is Asia/Taipei** — the user wakes up in Taipei time;
  `TZ=Asia/Taipei date` everywhere

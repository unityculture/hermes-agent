---
name: inbox-collector
description: "Save a forwarded URL / pasted post / screenshot into the MyTWINS second brain (unityculture/My-twins repo) under inbox/raw/. Triggered when the user shares an article link, social post snippet, or screenshot they want stashed for later digestion."
version: 0.1.0
author: Nuway (Sheng Lin)
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Inbox, Knowledge-Base, Second-Brain, GitHub, MyTWINS, Personal]
    related_skills: [github-auth]
---

# MyTWINS Inbox Collector

Save a piece of forwarded content (URL, social post, screenshot) into the
MyTWINS knowledge base by committing a markdown file to `inbox/raw/` in
`unityculture/My-twins`. Bot's only job is to land the raw material; a separate
daily batch (`/digest` workflow in MyTWINS) does the actual ingestion.

## When to trigger

User sends a message that looks like they're saving content to read/digest later:
- A bare URL (YouTube, article, social post)
- A URL plus a few lines of pasted text (typical for X / Facebook posts where
  the URL alone hits a login wall)
- A screenshot attachment, with or without a URL/caption
- Phrases like "存起來", "save this", "幫我收一下", "for inbox", "看一下這篇"

**Do NOT trigger** if the user is asking a question about the content, wants a
summary now, or is using it inline for an active conversation. This skill is
only for "stash for later".

## Prerequisites

- `GITHUB_TOKEN` available (see `github-auth` skill — token needs `repo` scope
  on `unityculture/My-twins`)
- `MYTWINS_REPO` env var, default `unityculture/My-twins`

## Inputs to collect from the message

Extract these from the incoming message (and attachments):

| Field | How to get it |
|-------|---------------|
| `url` | First http(s) URL in the message; required if no screenshot |
| `pasted_text` | All non-URL text the user typed (verbatim, do NOT rewrite) |
| `image_path` | Local path of any image attachment Hermes received |
| `source` | Derived from URL host: `youtube.com` / `youtu.be` → `YouTube`; `x.com` / `twitter.com` → `X`; `facebook.com` / `fb.com` → `Facebook`; else the bare hostname |
| `title` | Best-effort: og:title via `curl + grep` for non-gated URLs; else empty |

## Steps

### 1. Build the filename and timestamp

```bash
TS=$(date -u +%Y-%m-%d-%H%M%S)
DATE=$(date -u +%Y-%m-%d)
STEM="inbox-${TS}"
FILENAME="${STEM}.md"
RAW_PATH="inbox/raw/${FILENAME}"
```

### 2. Handle screenshot (if present)

If the message includes an image attachment, upload it to
`inbox/raw/attachments/${STEM}.<ext>` in the repo via the Contents API
**before** writing the markdown file. Use the same commit message prefix.

```bash
# image_path is whatever Hermes hands you; assume PNG by default
EXT="${image_path##*.}"
ATTACH_PATH="inbox/raw/attachments/${STEM}.${EXT}"
B64=$(base64 -i "$image_path")
curl -fsS -X PUT \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${MYTWINS_REPO:-unityculture/My-twins}/contents/${ATTACH_PATH}" \
  -d "$(jq -nc --arg msg "inbox: attach ${STEM}" --arg b64 "$B64" \
    '{message:$msg, content:$b64, branch:"main"}')"
```

### 3. Best-effort fetch og:title for non-gated URLs

```bash
TITLE=""
if [ -n "$url" ]; then
  TITLE=$(curl -fsSL --max-time 5 -A "Mozilla/5.0" "$url" 2>/dev/null \
    | grep -oE '<meta[^>]+property="og:title"[^>]*>' \
    | grep -oE 'content="[^"]*"' | head -1 | sed 's/content="//; s/"$//')
fi
```

Skip title fetch entirely for X / Facebook URLs (login wall, wastes time).

### 4. Compose the markdown file

Use this exact frontmatter — it must conform to `meta/FRONTMATTER_SPEC.md`
in the MyTWINS repo (status enum = `unprocessed | processed` only):

```markdown
---
collected: <DATE>
status: unprocessed
source: <SOURCE>
url: <URL>
title: <TITLE or empty>
---

<PASTED_TEXT verbatim, blank if user only sent a URL>

<If image attached:>
![screenshot](attachments/<STEM>.<EXT>)
```

If the user sent multiple URLs in one message, create **one file per URL**
(same timestamp + suffix `-1`, `-2`, …) and split the pasted text by best
guess (or duplicate the whole pasted text into each file with a `note:` field).

### 5. Commit the markdown file

```bash
B64_MD=$(echo "$MARKDOWN_CONTENT" | base64)
curl -fsS -X PUT \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${MYTWINS_REPO:-unityculture/My-twins}/contents/${RAW_PATH}" \
  -d "$(jq -nc --arg msg "inbox: ${SOURCE} ${STEM}" --arg b64 "$B64_MD" \
    '{message:$msg, content:$b64, branch:"main"}')"
```

### 6. Reply to the user

Single LINE bubble, short. Examples:

- `已收 ✓  inbox/raw/inbox-2026-05-21-093215.md`
- `已收 ✓ （含截圖）  ${RAW_PATH}`
- `已收 ${N} 筆  最近一筆：${RAW_PATH}`

Do NOT summarize the content. Do NOT fetch the article body now. That's the
job of the `/digest` batch (runs daily 07:00 Asia/Taipei).

## Hard rules

- **Never rewrite** the user's pasted text. Save verbatim. The user may rely on
  exact wording (e.g., quoting a tweet).
- **status must be `unprocessed`** — `meta/FRONTMATTER_SPEC.md` enum is strict.
- **Don't fetch X / Facebook content** — they're login-walled. The user already
  attached text / screenshot if they want the content captured.
- **One file per URL** — if a message has 3 URLs, write 3 files.
- **Commit directly to `main`** — MyTWINS is a personal KB with no PR flow for
  inbox writes.

## Failure modes

- `GITHUB_TOKEN` missing or insufficient scope → tell the user, do NOT silently
  drop the message. Reply: `❌ GITHUB_TOKEN 沒設或權限不足，沒收成功`
- GitHub API 422 (file already exists, same timestamp collision) → append `-2`,
  `-3` to filename stem and retry
- Network error fetching og:title → continue with empty title (not a blocker)

## Reference: downstream digester

After this skill commits, the MyTWINS `/digest` workflow picks the file up on
its next 07:00 run, abstracts it, finds related KB items, and writes to
`inbox/digest/<date>.md`. Full chain documented in
`meta/workflow-raw消化.md` in the MyTWINS repo.

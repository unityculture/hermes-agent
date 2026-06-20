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
`unityculture/My-twins`, **then digest it inline if it's fetchable text**.

Two phases, by capability (地基原則 — capability decides completion):
- **Phase A (always): land the raw.** Commit `inbox/raw/inbox-<TS>.md` with
  `status: unprocessed`. This is the safety net — even if digestion fails, the
  raw material is saved.
- **Phase B (text only): digest inline.** If the content is fetchable text
  (article / blog / readable post), fetch it, write a two-layer summary, flip
  `status: processed`, and rename the file to its finished slug.
- **Video / un-fetchable → hand off.** YouTube etc. can't be fetched from the
  datacenter IP (proven blocked). Leave it `status: unprocessed`; the local
  Claude Code `/digest` (residential IP, runs every 3h) will pick it up. **Never
  fake `processed` on content you couldn't actually read.**

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

### 6. Digest inline if it's fetchable text (Phase B)

Decide whether you can actually read the content:

- **Video (YouTube etc.) → STOP here.** Datacenter IP can't pull the transcript
  (proven). Leave the file `status: unprocessed`, do NOT rename. Skip to step 7
  and tell the user the local side will digest it.
- **X / Facebook / login-walled → STOP here.** You only have the user's pasted
  text / screenshot, not the full piece. Leave `unprocessed`, skip to step 7.
- **Fetchable text (article / blog / readable post) → digest now.**

To digest:

1. **Fetch the body**: `curl -fsSL --max-time 15 -A "Mozilla/5.0" "$url"`, strip
   tags to readable text. If fetch fails or the body is too thin to summarize →
   treat as un-fetchable: leave `unprocessed`, skip to step 7.
2. **Write two layers** (per `meta/workflow-ingest.md` §兩層摘要 in the KB):
   - **提醒層 (reminder)**: one-line summary (`one_line_summary`) + 2-5 concept
     tags (`concept_tags`). This is what the briefing shows.
   - **完整層 (full)**: 引導式閱讀 — a guided read that **follows the piece's
     own narrative order**, not condensed themes. Someone who never opens the
     original should still understand it from this.
3. **Rewrite the file**: keep the original pasted text / screenshot, set
   frontmatter `status: processed`, add `one_line_summary` + `concept_tags`,
   append the 引導式閱讀 body. Then **rename** `inbox/raw/inbox-<TS>.md` →
   `inbox/raw/<DATE>-<slug>.md` (slug = short kebab-case topic). Renaming via
   GitHub API = PUT new path + DELETE old path.
4. **Stay in your lane**: do NOT build cross-file `related_*` backlinks, do NOT
   upgrade the file into `ideas/` or `references/`, do NOT touch any other file.
   That whole-graph work is local Claude Code's job. You digest the single file
   you collected — nothing else.

### 7. Reply to the user

Single LINE bubble, short. Examples:

- Digested text: `已收並消化 ✓  inbox/raw/2026-06-20-續約率-唯一-kpi.md`
- Video (handed off): `已收 ✓  ${RAW_PATH}（影片本地會消化）`
- Login-walled / un-fetchable: `已收 ✓  ${RAW_PATH}（抓不到內文，本地會處理）`
- Screenshot only: `已收 ✓ （含截圖）  ${RAW_PATH}`
- Multiple: `已收 ${N} 筆  最近一筆：${RAW_PATH}`

Do NOT paste the 引導式閱讀 body into the LINE reply — it lives in the file. The
reply is just confirmation.

## Hard rules

- **Never rewrite** the user's pasted text. Save it verbatim alongside any
  digest you add — the user may rely on exact wording (e.g. quoting a tweet).
- **`status: processed` only when you actually read and summarized the content.**
  Couldn't fetch it (video / login wall / fetch failed) → it stays `unprocessed`.
  This is the 地基原則: no real content, no `processed`.
- **Don't fetch X / Facebook content** — login-walled. They stay `unprocessed`.
- **One file per URL** — if a message has 3 URLs, write 3 files (digest each one
  that's fetchable text).
- **Stay in your lane** — you write only the raw file you collected (land +
  inline digest). No cross-file links, no upgrades to `ideas/` / `references/`,
  no edits elsewhere. That's local Claude Code's job.
- **Commit directly to `main`** — MyTWINS is a personal KB with no PR flow for
  inbox writes.

## Failure modes

- `GITHUB_TOKEN` missing or insufficient scope → tell the user, do NOT silently
  drop the message. Reply: `❌ GITHUB_TOKEN 沒設或權限不足，沒收成功`
- GitHub API 422 (file already exists, same timestamp collision) → append `-2`,
  `-3` to filename stem and retry
- Fetch / summarize fails on otherwise-text content → keep Phase A's
  `unprocessed` file (don't lose it), reply `已收 ✓ ${RAW_PATH}（抓不到內文，本地會處理）`

## Reference: the rest of the pipeline

You complete the single item you collected (land + inline digest of text). The
local Claude Code `/digest` (every 3h, residential IP) does what you can't:
video transcription, cross-file `related_*` backlinks, and upgrading raw into
`ideas/` / `references/`. The full per-item procedure (the single owner of
"complete one item") is `meta/workflow-ingest.md` in the MyTWINS repo.

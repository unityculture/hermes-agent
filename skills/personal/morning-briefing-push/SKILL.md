---
name: morning-briefing-push
description: "MyTWINS daily morning briefing. NOTE: production now runs as a no-agent cron script (scripts/morning_briefing_push.py), NOT as an agent skill. This file is reference/spec only — the cron does not load it."
version: 0.2.0
author: Nuway (Sheng Lin)
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Inbox, Knowledge-Base, Second-Brain, LINE, MyTWINS, Personal, Briefing]
    related_skills: [github-auth, inbox-collector]
---

# MyTWINS Morning Briefing — how it actually runs

The 08:00 Asia/Taipei briefing is **produced and delivered by a no-agent cron
script**, not by this skill:

- Cron job `Morning Briefing` (`0 0 * * *` UTC = 08:00 Taipei), mode
  `--no-agent --script`, runs `/opt/data/scripts/morning_briefing_push.py`
  (version-controlled in this fork at `scripts/morning_briefing_push.py`).
- That script, in one pass: reads the MyTWINS KB via GitHub API → assembles
  today's briefing (aggregating each item's `one_line_summary` / `concept_tags`,
  which were already written with an LLM at digest time) → writes
  `inbox/digest/<today>-briefing.json` back → formats the LINE message and
  prints it (delivered verbatim).
- Manual run: `hermes cron run 816e7e78ae2c`.

## Why a no-agent script and NOT an agent skill (the trap to never repeat)

An earlier version made this an **agent-mode** cron skill whose body contained
`curl -H "Authorization: Bearer ${GITHUB_TOKEN}"` to write the briefing back.
**Hermes cron prompt-threat scanning blocked it as `exfil_curl_auth_header`** —
the 08:00 job failed silently for days and fell back to a stale briefing.

Rule: **cron-triggered prompts / loaded skill bodies must not contain `curl` +
an auth header.** Any token-bearing I/O for a cron job goes inside a script
under `~/.hermes/scripts/` (or `/opt/data/scripts/`) — script files are executed,
not prompt-scanned — and the job runs `--no-agent`. (User-message-triggered
skills like `inbox-collector` are NOT scanned, so their token curls are fine.)

## Briefing content spec (what the script builds)

The message schema lives in MyTWINS `meta/briefing-schema.md`. Sections, each
skipped when empty:

- `☀️ 早安！M/D（週X）`
- `🔥 今天先讀` — top_picks: title（related_label）, why_now, url (only if ≤80
  chars and not a `.md` path)
- `🔗 可以串起來` — cross_pollination: one plain insight sentence each
- `📥 昨天新到` — new_arrivals: title — one_liner
- `✅ 待辦` — todos: project_label：text
- `🛠` — steward: 0-1 condensed line from steward-latest.md

Hard rules the script honors: human-ready values only (never file paths / `.md`
/ backlink jargon); first char of the message is `☀️`; ≤4500 chars (drop
new_arrivals then todos first); all-empty day → `☀️ 早安！…📦 今天無新素材、無待辦。輕鬆過。`

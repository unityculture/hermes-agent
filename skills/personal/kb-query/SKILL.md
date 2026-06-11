---
name: kb-query
description: "Answer questions about Sheng's life/work from the MyTWINS knowledge base (unityculture/My-twins): clients (KINYO / WrenAI / Yinyuan), projects, meetings, contracts, contacts, ideas, collected articles. Read-only retrieval over GitHub API. Trigger whenever Sheng asks about any of his own projects, clients, meetings, plans, or saved material."
version: 0.1.0
author: Nuway (Sheng Lin)
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Knowledge-Base, Second-Brain, MyTWINS, Retrieval, Personal]
    related_skills: [inbox-collector, morning-briefing-push]
---

# MyTWINS KB Query

Answer Sheng's questions from his second brain. **Read-only** — never commit.

## Prerequisites

`GITHUB_TOKEN` lives in `/opt/data/.env` (auto-seeded at boot). Load it first:

```bash
TOKEN=$(grep -E "^GITHUB_TOKEN=" /opt/data/.env | head -1 | cut -d= -f2-)
REPO="unityculture/My-twins"
read_file()  { curl -fsS -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github.raw" "https://api.github.com/repos/$REPO/contents/$1"; }
list_dir()   { curl -fsS -H "Authorization: Bearer $TOKEN" "https://api.github.com/repos/$REPO/contents/$1" | jq -r '.[] | .type + "  " + .name'; }
search_kb()  { curl -fsS -H "Authorization: Bearer $TOKEN" "https://api.github.com/search/code?q=repo:$REPO+$1" | jq -r '.items[].path' | head -10; }
```

## Retrieval protocol (three entrances, in order)

**1. README ladder (top-down) — default for client/project questions**

KB map:

| Topic | Entry point |
|-------|------------|
| KINYO 客戶（會議、顧問服務、簡報） | `nuway/clients/kinyo/README.md` |
| WrenAI 接案（合約、KB、影片） | `nuway/clients/wrenai/README.md` |
| 音圓 Yinyuan 客戶 | `nuway/clients/yinyuan/README.md` |
| 公司定位 / 方向 | `nuway/strategy/README.md` |
| 品牌 / 官網 / 社群 / 個人品牌 | `nuway/brand/README.md` |
| 行政 / 財務 / 報稅 / 補助 | `nuway/operations/README.md` |
| 求職 | `projects/career/` |
| 想法 / 文章草稿 | `ideas/` |
| 人脈 | `contacts/` |
| 收集的文章 | `inbox/raw/`, daily summaries in `inbox/digest/` |

Read the README first — it tells you which file holds what. Then read the
target file(s).

**2. Backlinks (lateral)** — any file's frontmatter `related_ideas` /
`related_projects` / `related_contacts` / `related_inbox` /
`related_references` lists related files by name. Follow them when the first
file doesn't fully answer.

**3. INDEX / code search (fallback)** — topic not in the map? Read top-level
`INDEX.md`, or `search_kb "關鍵詞"`.

## Answer rules

- Quote facts from the KB with the source path, e.g. `（來源：nuway/clients/kinyo/顧問服務執行.md）`
- Meetings/schedules live in client folders (agendas, prep docs, execution
  logs) — **never ask for Google Calendar access**
- KB says nothing → say exactly that («KB 裡沒有這項記錄»), don't invent
- LINE format: plain text, short, • bullets, no markdown

## Failure modes

| Condition | Action |
|-----------|--------|
| 401/403 from GitHub | Re-read token from `/opt/data/.env`; if still failing, tell Sheng the token may have expired — do NOT ask him to create one before checking |
| 404 on a path | The KB structure may have changed — fall back to `list_dir` on the parent, then `INDEX.md` |
| Search rate-limited | Use README ladder instead |

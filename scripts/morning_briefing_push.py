#!/usr/bin/env python3
"""Morning briefing — PRODUCER + deliverer (no-agent script).

Runs on Hermes cron (--no-agent --script). One pass:
  1. Read the MyTWINS KB via GitHub API (token lives here, NOT in any scanned
     prompt — that's the whole point of doing this in a script).
  2. Assemble today's briefing from already-digested material (each item's
     one_line_summary / concept_tags were written with an LLM at digest time,
     so this script only aggregates — no runtime LLM needed).
  3. Write inbox/digest/<today>-briefing.json back (audit trail).
  4. Format the LINE message and print it (delivered verbatim).

Falls back to the latest existing briefing.json if assembly turns up nothing,
so it can never silently break the morning push.
"""
import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

REPO_DEFAULT = 'unityculture/My-twins'
NEW_ARRIVAL_DAYS = 2   # "昨天新到" window (today + yesterday by `collected`)


def load_env(path='/opt/data/.env'):
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


def clean(s):
    if s is None:
        return ''
    s = str(s).replace('\r', ' ').strip()
    if '.md' in s:
        s = re.sub(r'\S*\.md\S*', '', s).strip()
        s = re.sub(r'\s{2,}', ' ', s)
    return s


def arr(data, key):
    v = data.get(key, [])
    return v if isinstance(v, list) else []


# ---------- GitHub helpers (token-bearing; script-only, never in a prompt) ----------

def _req(url, token, accept='application/vnd.github+json'):
    return urllib.request.Request(url, headers={
        'Authorization': f'Bearer {token}',
        'Accept': accept,
        'User-Agent': 'Hermes-Morning-Briefing',
    })


def fetch_json(url, token):
    with urllib.request.urlopen(_req(url, token), timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_text(path, repo, token):
    url = f'https://api.github.com/repos/{repo}/contents/{path}'
    payload = fetch_json(url, token)
    return base64.b64decode(payload.get('content', '')).decode('utf-8'), payload.get('sha')


def get_tree(repo, token):
    """Recursive repo tree → list of paths."""
    data = fetch_json(
        f'https://api.github.com/repos/{repo}/git/trees/main?recursive=1', token)
    return [it['path'] for it in data.get('tree', []) if it.get('type') == 'blob']


def put_file(path, repo, token, content_str, message, sha=None):
    body = {'message': message,
            'content': base64.b64encode(content_str.encode('utf-8')).decode('ascii'),
            'branch': 'main'}
    if sha:
        body['sha'] = sha
    req = urllib.request.Request(
        f'https://api.github.com/repos/{repo}/contents/{path}',
        data=json.dumps(body).encode('utf-8'), method='PUT',
        headers={'Authorization': f'Bearer {token}',
                 'Accept': 'application/vnd.github+json',
                 'User-Agent': 'Hermes-Morning-Briefing'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


# ---------- frontmatter (flat scalars + simple inline lists only) ----------

def parse_frontmatter(text):
    if not text.startswith('---'):
        return {}, text
    end = text.find('\n---', 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip('\n')
    body = text[end + 4:]
    fm = {}
    for line in block.split('\n'):
        m = re.match(r'^([a-zA-Z_]+):\s*(.*)$', line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if v.startswith('[') and v.endswith(']'):
            inner = v[1:-1].strip()
            fm[k] = [x.strip().strip('"').strip("'") for x in inner.split(',') if x.strip()]
        else:
            fm[k] = v.strip().strip('"').strip("'")
    return fm, body


# ---------- path → human label ----------

LABELS = [
    ('clients/kinyo', 'KINYO'),
    ('clients/wrenai', 'WrenAI'),
    ('clients/yinyuan', '音圓'),
    ('clients/valuex', 'ValueX'),
    ('strategy', '策略定位'),
    ('brand/personal-brand', '個人品牌'),
    ('brand', '品牌'),
    ('operations/government-funding', '政府補助'),
    ('operations', '營運'),
    ('website', '官網'),
    ('career', '求職'),
    ('ideas', '觀點'),
    ('references', '外部素材'),
]


def label_for(path):
    if not path:
        return ''
    for frag, lab in LABELS:
        if frag in path:
            return lab
    parts = [p for p in path.split('/') if p and p != 'nuway']
    return parts[0] if parts else ''


# ---------- assemble today's briefing from KB ----------

def assemble(repo, token, today):
    paths = get_tree(repo, token)
    raw_md = [p for p in paths if p.startswith('inbox/raw/') and p.endswith('.md')
              and '/attachments/' not in p]
    todo_paths = [p for p in paths if p.endswith('/TODO.md') and '/_archive/' not in p]
    cutoff = today - dt.timedelta(days=NEW_ARRIVAL_DAYS - 1)

    arrivals = []   # dicts: title, one_liner, url, source, label, tags
    for p in raw_md:
        try:
            text, _ = fetch_text(p, repo, token)
        except Exception:
            continue
        fm, _ = parse_frontmatter(text)
        if fm.get('status') != 'processed':
            continue
        ols = clean(fm.get('one_line_summary'))
        if not ols or '未取得' in ols or '登入牆' in ols:
            continue
        coll = str(fm.get('collected', ''))
        try:
            cdate = dt.date.fromisoformat(coll[:10])
        except ValueError:
            cdate = None
        if cdate is None or cdate < cutoff:
            continue
        rel = fm.get('related_projects') or []
        rel0 = rel[0] if isinstance(rel, list) and rel else ''
        title = clean(fm.get('title')) or ols[:24]
        arrivals.append({
            'title': title, 'one_liner': ols,
            'url': clean(fm.get('url')), 'source': clean(fm.get('source')),
            'label': label_for(rel0), 'tags': fm.get('concept_tags') or [],
            'collected': coll,
        })

    arrivals.sort(key=lambda a: a['collected'], reverse=True)

    new_arrivals = [{'title': a['title'], 'one_liner': a['one_liner']} for a in arrivals]
    top_picks = [{
        'title': a['title'], 'why_now': a['one_liner'],
        'related_label': a['label'], 'source': a['source'], 'url': a['url'],
    } for a in arrivals[:3]]

    # cross_pollination: two arrivals sharing a concept tag (best-effort, often empty)
    cross = []
    for i in range(len(arrivals)):
        for j in range(i + 1, len(arrivals)):
            shared = set(arrivals[i]['tags']) & set(arrivals[j]['tags'])
            shared = {t for t in shared if t}
            if shared:
                t = sorted(shared)[0]
                cross.append({'insight':
                    f"「{arrivals[i]['title']}」和「{arrivals[j]['title']}」都談到 {t}，可以一起看。"})
                break
        if cross:
            break

    # todos: open `- [ ]` lines, round-robin across projects, cap 5
    by_project = []
    for tp in sorted(todo_paths):
        try:
            text, _ = fetch_text(tp, repo, token)
        except Exception:
            continue
        items = []
        for line in text.split('\n'):
            m = re.match(r'^\s*-\s*\[\s*\]\s*(.+)$', line)
            if m:
                items.append(clean(m.group(1)))
        if items:
            by_project.append((label_for(tp), items))
    todos = []
    idx = 0
    while len(todos) < 5 and any(idx < len(it) for _, it in by_project):
        for label, items in by_project:
            if idx < len(items):
                todos.append({'text': items[idx], 'project_label': label})
                if len(todos) >= 5:
                    break
        idx += 1

    # steward: pull actionable suggestions from steward-latest.md
    steward = []
    try:
        text, _ = fetch_text('inbox/digest/steward-latest.md', repo, token)
        sug = []
        for line in text.split('\n'):
            m = re.match(r'^\s*(?:[-*]|\d+\.)\s+(.+)$', line)
            if m:
                s = clean(m.group(1))
                if 8 <= len(s) <= 120:
                    sug.append(s)
        if sug:
            steward = [{'text': f'steward 有 {len(sug)} 條建議，第一條：{sug[0]}'}]
    except Exception:
        pass

    return {
        'date': today.isoformat(),
        'generated_at': dt.datetime.now(ZoneInfo('Asia/Taipei')).isoformat(),
        'top_picks': top_picks,
        'cross_pollination': cross,
        'new_arrivals': new_arrivals,
        'todos': todos,
        'steward': steward,
    }


# ---------- format LINE message ----------

def build_message(data, today, weekday):
    sun = '☀️'; fire = '🔥'; link = '🔗'; inbox = '📥'; ok = '✅'; box = '📦'
    md = f'{today.month}/{today.day}'
    top = arr(data, 'top_picks'); cross = arr(data, 'cross_pollination')
    new = arr(data, 'new_arrivals'); todos = arr(data, 'todos')
    steward = arr(data, 'steward')

    def build(include_new=True, include_todos=True):
        lines = [f'{sun} 早安！{md}（{weekday}）']
        if not (top or cross or (new and include_new) or (todos and include_todos) or steward):
            return lines[0] + f'\n\n{box} 今天無新素材、無待辦。輕鬆過。'
        if top:
            lines += ['', f'{fire} 今天先讀']
            for i, it in enumerate(top, 1):
                title = clean(it.get('title')); lab = clean(it.get('related_label'))
                why = clean(it.get('why_now')); u = clean(it.get('url'))
                lines.append(f'{i}. {title}' + (f'（{lab}）' if lab else ''))
                if why:
                    lines.append('   ' + why)
                if u and len(u) <= 80 and '.md' not in u:
                    lines.append('   ' + u)
        if cross:
            lines += ['', f'{link} 可以串起來']
            for it in cross:
                insight = clean(it.get('insight'))
                if insight:
                    lines.append('• ' + insight)
        if include_new and new:
            lines += ['', f'{inbox} 昨天新到']
            for it in new:
                title = clean(it.get('title')); one = clean(it.get('one_liner'))
                if title and one:
                    lines.append(f'• {title} — {one}')
                elif title or one:
                    lines.append('• ' + (title or one))
        if include_todos and todos:
            lines += ['', f'{ok} 待辦']
            for it in todos:
                text = clean(it.get('text')); lab = clean(it.get('project_label'))
                if text and lab:
                    lines.append(f'• {lab}：{text}')
                elif text:
                    lines.append('• ' + text)
        if steward:
            for it in steward:
                t = clean(it.get('text'))
                if t:
                    lines += ['', '🛠 ' + t]
        return '\n'.join(lines)

    msg = build(True, True)
    if len(msg) > 4500:
        msg = build(False, True)
    if len(msg) > 4500:
        msg = build(False, False)
    return msg[:4500].rstrip()


def latest_existing(repo, token, today, weekday):
    """Fallback: deliver the most recent existing briefing.json."""
    listing = fetch_json(
        f'https://api.github.com/repos/{repo}/contents/inbox/digest', token)
    cands = []
    for item in listing:
        m = re.match(r'(\d{4}-\d{2}-\d{2})-briefing\.json$', item.get('name', ''))
        if m:
            cands.append((m.group(1), 'inbox/digest/' + item['name']))
    if not cands:
        return f'☀️ 早安！今天是 {today.isoformat()}\n\n⚠️ 今日晨報未產（檢查排程）。'
    date_s, path = sorted(cands)[-1]
    text, _ = fetch_text(path, repo, token)
    data = json.loads(text)
    bdate = dt.date.fromisoformat(date_s)
    bwd = ['週一', '週二', '週三', '週四', '週五', '週六', '週日'][bdate.weekday()]
    return build_message(data, bdate, bwd)


def main():
    load_env()
    token = os.environ.get('GITHUB_TOKEN')
    repo = os.environ.get('MYTWINS_REPO', REPO_DEFAULT)
    now = dt.datetime.now(ZoneInfo('Asia/Taipei'))
    today = now.date()
    weekday = ['週一', '週二', '週三', '週四', '週五', '週六', '週日'][today.weekday()]
    if not token:
        print('☀️ 早安！\n\n❌ 無法讀取 MyTWINS（GitHub auth 失敗，檢查 GITHUB_TOKEN）。')
        return

    try:
        data = assemble(repo, token, today)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print('☀️ 早安！\n\n❌ 無法讀取 MyTWINS（GitHub auth 失敗，檢查 GITHUB_TOKEN）。')
            return
        data = None
    except Exception:
        data = None

    # if assembly produced real content, persist it (audit) then deliver
    if data and (data['top_picks'] or data['new_arrivals'] or data['todos'] or data['steward']):
        path = f"inbox/digest/{today.isoformat()}-briefing.json"
        try:
            sha = None
            try:
                _, sha = fetch_text(path, repo, token)
            except Exception:
                sha = None
            put_file(path, repo, token, json.dumps(data, ensure_ascii=False, indent=2),
                     f'briefing: {today.isoformat()} 晨報', sha)
        except Exception:
            pass  # a missed write beats a missed briefing
        print(build_message(data, today, weekday))
        return

    # nothing assembled → fall back to the latest existing briefing
    try:
        print(latest_existing(repo, token, today, weekday))
    except Exception:
        print(f'☀️ 早安！\n\n⚠️ 晨報資料格式錯誤或讀取失敗。')


if __name__ == '__main__':
    main()

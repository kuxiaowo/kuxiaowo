"""Refresh public GitHub statistics and the README's star counts.

Run with Python (Conda recommended) and an authenticated GitHub CLI:
    python scripts/update_stats.py
Only reads GitHub; does not commit, push, or change any repository.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from html import escape
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import subprocess
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
USER = 'kuxiaowo'
QUERY = '''query { user(login:"kuxiaowo") {
 login createdAt followers { totalCount }
 repositories(first:100,ownerAffiliations:[OWNER],privacy:PUBLIC,orderBy:{field:NAME,direction:ASC}) {
 totalCount pageInfo {hasNextPage} nodes {name url isFork stargazerCount
 languages(first:100,orderBy:{field:SIZE,direction:DESC}) {
 totalSize pageInfo {hasNextPage} edges {size node {name color}} }
 } } } }'''


def validate_calendar_days(days):
    # GitHub aligns the rolling contribution grid to whole weeks. Extra days
    # are valid (including leap years); they must still form one complete span.
    if not 365 <= len(days) <= 372:
        raise ValueError('Expected 365-372 days in the week-aligned public calendar')
    for day in days:
        if not isinstance(day['count'], int) or day['count'] < 0 or not 0 <= day['level'] <= 4:
            raise ValueError('Invalid public calendar count or level')
        date.fromisoformat(day['date'])
    for a, b in zip(days, days[1:]):
        if date.fromisoformat(b['date']) - date.fromisoformat(a['date']) != timedelta(days=1):
            raise ValueError('Nonconsecutive calendar dates')


class PublicCalendar(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = {}
        self.tips = {}
        self.active = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'td' and 'data-date' in a:
            self.cells[a['id']] = {'date': a['data-date'], 'level': int(a['data-level'])}
        if tag == 'tool-tip' and a.get('for') in self.cells:
            self.active = a['for']
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'tool-tip' and self.active:
            m = re.match(r'(No|[\d,]+) contributions?\b', ''.join(self.parts).strip())
            if not m:
                raise ValueError('Unexpected GitHub contribution tooltip')
            self.tips[self.active] = 0 if m[1] == 'No' else int(m[1].replace(',', ''))
            self.active = None

    def days(self):
        if len(self.cells) != len(self.tips):
            raise ValueError('Missing public calendar counts')
        result = sorted([dict(cell, count=self.tips[key]) for key, cell in self.cells.items()], key=lambda d: d['date'])
        validate_calendar_days(result)
        return result


def collect(profile_json, calendar_html):
    if profile_json:
        payload = json.loads(Path(profile_json).read_text(encoding='utf-8-sig'))
    else:
        result = subprocess.run(['gh', 'api', 'graphql', '--input', '-'],
            input=json.dumps({'query': QUERY}), text=True, encoding='utf-8', capture_output=True, check=True)
        payload = json.loads(result.stdout)
    if payload.get('errors'):
        raise ValueError('GitHub GraphQL returned errors')
    user = payload['data']['user']
    if user['repositories']['pageInfo']['hasNextPage']:
        raise ValueError('Repository pagination is required; refusing an incomplete total')
    repos = user['repositories']['nodes']
    owned = [r for r in repos if not r['isFork']]
    languages = Counter()
    colors = {}
    for repo in owned:
        if repo['languages']['pageInfo']['hasNextPage']:
            raise ValueError('Language pagination is required')
        for edge in repo['languages']['edges']:
            name = edge['node']['name']
            languages[name] += edge['size']
            colors[name] = edge['node']['color'] or '#8b949e'
    if calendar_html:
        calendar = Path(calendar_html).read_text(encoding='utf-8-sig')
    else:
        # Anonymous public page, so no private repository details enter the artifact.
        request = Request(f'https://github.com/users/{USER}/contributions', headers={'User-Agent': 'github-profile-stats', 'Accept-Language': 'en-US'})
        with urlopen(request, timeout=40) as response:
            calendar = response.read().decode('utf-8')
    parser = PublicCalendar()
    parser.feed(calendar)
    days = parser.days()
    counts = [day['count'] for day in days]
    total = sum(counts)
    shown = re.search(r'([\d,]+)\s+contributions\s+in the last year', calendar)
    if not shown:
        raise ValueError('Missing public GitHub contribution total')
    headline_total = int(shown[1].replace(',', ''))
    if headline_total != total:
        # The "last year" headline may cover a different range from the
        # week-aligned calendar. The validated daily cells drive our chart.
        print(
            f'::warning::GitHub contribution headline ({headline_total}) differs from '
            f'the public calendar sum ({total}) for '
            f'{days[0]["date"]} through {days[-1]["date"]}; using validated daily counts.',
            flush=True,
        )
    run = longest = 0
    for count in counts:
        run = run + 1 if count else 0
        longest = max(longest, run)
    # Current streak is measured strictly through the final date shown, including today.
    return {
        'username': user['login'], 'updated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
        'joined': user['createdAt'][:10], 'followers': user['followers']['totalCount'],
        'public_repositories': user['repositories']['totalCount'], 'nonfork_repositories': len(owned),
        'total_stars': sum(r['stargazerCount'] for r in owned),
        'nonfork_repository_stars': {r['name']: r['stargazerCount'] for r in owned},
        'repository_stars': {r['name']: r['stargazerCount'] for r in repos},
        'language_bytes': dict(languages.most_common()), 'language_colors': colors,
        'contributions': {'total': total, 'start': days[0]['date'], 'end': days[-1]['date'],
            'current_streak': run, 'longest_streak': longest, 'highest_day': max(counts),
            'average_day': total / len(days), 'days': days},
        'sources': [f'https://github.com/{USER}', f'https://api.github.com/users/{USER}/repos',
            'https://docs.github.com/en/graphql/reference/objects#language', f'https://github.com/users/{USER}/contributions'],
        'scope': {'stars': 'All owned public non-fork repositories; not a unique-person count.',
            'languages': 'GitHub language bytes across owned public non-fork repositories, including generated code and documentation.',
            'calendar': 'Anonymous public profile calendar, including any anonymized contributions visible on that profile.',
            'streaks': 'Consecutive nonzero days in the displayed date range; current streak ends on its final date.'}
    }


def render_svg(data, compact=False):
    w, h = (440, 960) if compact else (880, 835)
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title desc">',
        '<title id="title">kuxiaowo GitHub statistics</title>',
        f'<desc id="desc">{data["total_stars"]} stars across public non-fork repositories; {data["followers"]} followers; '
        f'{data["contributions"]["total"]} contributions in the displayed year. Language share uses GitHub code bytes. Dated snapshot.</desc>',
        '<style>:root{--bg:#ffffff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--link:#0969da;--zero:#ebedf0}'
        '@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#919ba6;--line:#30363d;--link:#79b8ff;--zero:#d6ddd8}}'
        'text{font-family:Segoe UI,Arial,sans-serif;fill:var(--fg)}.muted{fill:var(--muted)}.accent{fill:var(--link)}.empty{fill:var(--zero)}</style>',
        f'<rect width="{w}" height="{h}" fill="var(--bg)" rx="10"/>']

    def text(x, y, value, size=17, cls='', weight='400', anchor='start'):
        pieces.append(f'<text x="{x}" y="{y}" font-size="{size}" class="{cls}" font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>')

    def line(y):
        pieces.append(f'<path d="M24 {y}H{w-24}" stroke="var(--line)"/>')

    c = data['contributions']
    joined = date.fromisoformat(data['joined']).strftime('%b %Y')
    text(24, 42, 'kuxiaowo', 30, 'accent', '600')
    text(24, 70, f'Joined {joined} · {data["followers"]} followers · {data["public_repositories"]} public repos', 14 if compact else 17, 'muted')
    text(24, 116, f'★ {data["total_stars"]}', 28, '', '600')
    text(24, 139, f'Stars · {data["nonfork_repositories"]} public non-fork repos', 12 if compact else 15, 'muted')
    text(244 if compact else 495, 116, f'{c["total"]:,}', 28, '', '600')
    text(244 if compact else 495, 139, 'Contributions · last year', 12 if compact else 15, 'muted')
    line(160)
    langs = list(data['language_bytes'].items())
    total_bytes = sum(n for _, n in langs)
    selected = langs[:6] + [('Other', sum(n for _, n in langs[6:]))]
    text(24, 193, f'Most used languages · {len(langs)} detected', 18 if compact else 21, 'accent', '600')
    text(24, 217, 'By code size in public non-fork repositories', 13 if compact else 15, 'muted')
    x = 24
    for name, count in selected:
        width = (w-48) * count / total_bytes
        color = data['language_colors'].get(name, '#8b949e')
        pieces.append(f'<rect x="{x:.2f}" y="235" width="{width:.2f}" height="11" fill="{color}"><title>{escape(name)}: {count/total_bytes*100:.2f}%</title></rect>')
        x += width
    for i, (name, count) in enumerate(selected):
        col, row = i % 2, i // 2
        x, y = 24 + col * ((w-48)/2+7), 275 + row * 29
        color = data['language_colors'].get(name, '#8b949e')
        pieces.append(f'<circle cx="{x+5}" cy="{y-6}" r="5" fill="{color}"/>')
        text(x+19, y, name, 15 if compact else 17)
        text(x + (w-48)/2 - 12, y, f'{count/total_bytes*100:.2f}%', 14 if compact else 17, 'muted', anchor='end')
    line(383)
    text(24, 417, 'Contributions calendar', 21, 'accent', '600')
    text(24, 442, f'{c["start"]} → {c["end"]}', 14 if compact else 16, 'muted')
    if compact:
        specs = [(24,480,'Current streak',f'{c["current_streak"]} days'),(235,480,'Best in this period',f'{c["longest_streak"]} days'),
            (24,548,'Highest in one day',str(c['highest_day'])),(235,548,'Average per day',f'{c["average_day"]:.2f}')]
        dx, dy, ox, oy, rise = 6.0, 3.0, 69, 646, 36
    else:
        specs = [(520,484,'Current streak',f'{c["current_streak"]} days'),(700,484,'Best in this period',f'{c["longest_streak"]} days'),
            (520,553,'Highest in one day',str(c['highest_day'])),(700,553,'Average per day',f'{c["average_day"]:.2f}')]
        dx, dy, ox, oy, rise = 12.0, 5.0, 114, 476, 52
    for x, y, label, value in specs:
        text(x,y,label,14,'muted')
        text(x,y+27,value,22,'','600')
    start = date.fromisoformat(c['start'])
    sunday = start - timedelta(days=(start.weekday()+1)%7)
    greens = ['#ebedf0','#9be9a8','#40c463','#30a14e','#216e39']
    def depth(day):
        delta = (date.fromisoformat(day['date'])-sunday).days
        week, weekday = divmod(delta,7)
        return week+weekday, week-weekday
    for day in sorted(c['days'], key=depth):
        current = date.fromisoformat(day['date'])
        offset = (current-sunday).days
        week, weekday = divmod(offset,7)
        x, y = ox + week*dx - weekday*dx, oy + week*dy + weekday*dy
        height = 0 if day['count']==0 else 2 + rise*math.sqrt(day['count']/c['highest_day'])
        bw, bd = dx*.88, dy*.88
        color = greens[day['level']]
        title = escape(f'{day["date"]}: {day["count"]} contributions')
        pieces.append(f'<g><title>{title}</title>')
        if height:
            pieces.append(f'<path d="M{x},{y-height+bd}l{bw},-{bd}v{height}l-{bw},{bd}Z" fill="{color}"/>')
            pieces.append(f'<path d="M{x},{y-height+bd}l-{bw},-{bd}v{height}l{bw},{bd}Z" fill="{color}"/>')
            pieces.append(f'<path d="M{x},{y-height+bd}l-{bw},-{bd}v{height}l{bw},{bd}Z" fill="#000" opacity=".22"/>')
        pieces.append(f'<path d="M{x},{y-height-bd}l{bw},{bd}l-{bw},{bd}l-{bw},-{bd}Z" '
            + (f'fill="{color}"' if height else 'class="empty"') + '/></g>')
    baseline = 862 if compact else 794
    text(24,baseline,'Less',12,'muted')
    for i, color in enumerate(greens):
        pieces.append(f'<rect x="{58+i*16}" y="{baseline-10}" width="12" height="12" rx="2" '+(f'fill="{color}"' if i else 'class="empty"')+'/>')
    text(145,baseline,'More',12,'muted')
    text(w-24,baseline,'Height follows daily contributions',11 if compact else 13,'muted',anchor='end')
    if compact:
        text(24,900,'Contributions include more than commits.',13,'muted')
        text(24,924,f'Snapshot · {data["updated_at"][:10]}',13,'muted')
    else:
        text(24,821,'Contributions include commits, issues, pull requests and reviews.',13,'muted')
        text(w-24,821,f'Snapshot · {data["updated_at"][:10]}',13,'muted',anchor='end')
    pieces.append('</svg>')
    return '\n'.join(pieces)


def update_readme(data):
    path = ROOT / 'README.md'
    lines = path.read_text(encoding='utf-8').splitlines()
    result = []
    for line in lines:
        if line.startswith('| Project |'):
            line = '| Project | What it does | Stars |'
        elif line.startswith('| :--- |'):
            line = '| :--- | :--- | ---: |'
        elif line.startswith('| **['):
            columns = line.split('|')
            repo = re.search(r'https://github.com/kuxiaowo/([^/)]+)', columns[1])[1]
            stars = data['repository_stars'][repo]
            line = f'| {columns[1].strip()} | {columns[2].strip()} | [★\u00a0{stars}](https://github.com/kuxiaowo/{repo}/stargazers) |'
        result.append(line)
    source = '\n'.join(result) + '\n'
    source = re.sub(r'<!-- stats-date:start -->.*?<!-- stats-date:end -->',
        f'<!-- stats-date:start -->\n<sub>Star counts as of {data["updated_at"][:10]}; each count refers to the linked repository.</sub>\n<!-- stats-date:end -->',source,flags=re.S)
    path.write_text(source,encoding='utf-8')
    preview = ROOT / 'preview.html'
    if preview.exists():
        page = preview.read_text(encoding='utf-8')
        page = re.sub(r'(<a href="https://github.com/kuxiaowo/([^/]+)/stargazers">)★\s+\d+(</a>)',
            lambda m: m[1] + '★\u00a0' + str(data['repository_stars'][m[2]]) + m[3], page)
        page = re.sub(r'Star counts as of \d{4}-\d{2}-\d{2}', 'Star counts as of '+data['updated_at'][:10], page)
        page = re.sub(r'^const md=.*?;$', lambda m: 'const md='+json.dumps(source).replace('<','\\u003c')+';', page, flags=re.M)
        preview.write_text(page,encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile-json')
    parser.add_argument('--calendar-html')
    args = parser.parse_args()
    data = collect(args.profile_json,args.calendar_html)
    for compact, filename in [(False,'github-stats.svg'),(True,'github-stats-compact.svg')]:
        (ROOT/'assets'/filename).write_text(render_svg(data,compact),encoding='utf-8')
    (ROOT/'stats-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    update_readme(data)
    print(f'Updated public snapshot: {data["total_stars"]} stars, {data["contributions"]["total"]} contributions.')


if __name__ == '__main__':
    main()

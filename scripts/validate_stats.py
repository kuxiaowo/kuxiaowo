"""Validate the generated snapshot before it can be committed or published."""
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from update_stats import validate_calendar_days

ROOT = Path(__file__).resolve().parents[1]


def validate():
    data = json.loads((ROOT / 'stats-data.json').read_text(encoding='utf-8'))
    assert data['username'] == 'kuxiaowo', 'Unexpected profile identity'
    assert data['total_stars'] == sum(data['nonfork_repository_stars'].values()), 'Star total mismatch'
    assert data['nonfork_repositories'] == len(data['nonfork_repository_stars']), 'Repository total mismatch'
    assert data['public_repositories'] == len(data['repository_stars']), 'Incomplete repository data'
    assert all(n >= 0 for n in data['repository_stars'].values()), 'Invalid star count'
    assert sum(data['language_bytes'].values()) > 0, 'Missing language data'
    calendar = data['contributions']
    days = calendar['days']
    validate_calendar_days(days)
    assert days[0]['date'] == calendar['start'] and days[-1]['date'] == calendar['end']
    assert sum(d['count'] for d in days) == calendar['total'], 'Contribution sum mismatch'
    streak = best = 0
    for day in days:
        streak = streak + 1 if day['count'] else 0
        best = max(best, streak)
    assert streak == calendar['current_streak'] and best == calendar['longest_streak'], 'Streak mismatch'
    assert max(d['count'] for d in days) == calendar['highest_day']
    assert abs(calendar['average_day'] - calendar['total'] / len(days)) < 1e-9
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert 'mailto:zhengxinpang0@gmail.com' in readme
    assert not re.search(r'\bstudent\b', readme, re.I)
    stars = re.findall(r'\[★\s+(\d+)\]\(https://github.com/kuxiaowo/([^/]+)/stargazers\)', readme)
    assert len(stars) == 6, 'Expected six featured project star counts'
    for value, repo in stars:
        assert int(value) == data['repository_stars'][repo], f'Stale star count: {repo}'
    for path in re.findall(r'(?:src|srcset)="(\./[^"]+)"', readme):
        assert (ROOT / path).is_file(), f'Missing asset: {path}'
    for asset in (ROOT / 'assets').glob('*.svg'):
        xml = ET.parse(asset)
        assert not any(e.tag.split('}')[-1] == 'script' for e in xml.iter()), 'Executable SVG content'
    for filename in ('github-stats.svg', 'github-stats-compact.svg'):
        xml = ET.parse(ROOT / 'assets' / filename)
        labels = [e.text or '' for e in xml.iter() if e.tag.split('}')[-1] == 'title']
        actual = [s for s in labels if re.match(r'\d{4}-\d{2}-\d{2}:', s)]
        assert sorted(actual) == sorted(f'{d["date"]}: {d["count"]} contributions' for d in days), 'Chart data mismatch'
    print(f'Validated {data["total_stars"]} stars and {calendar["total"]} contributions across {len(days)} days.')


if __name__ == '__main__':
    validate()

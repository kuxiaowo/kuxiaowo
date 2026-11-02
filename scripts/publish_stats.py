"""Publish generated statistics via developing -> pull request -> main.

Runs only inside this repository's GitHub Actions workflow. A developing
branch with unmerged work is never included in the automated update.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = 'kuxiaowo/kuxiaowo'
FILES = ['README.md', 'stats-data.json', 'assets/github-stats.svg', 'assets/github-stats-compact.svg']


def run(*args, capture=False):
    result = subprocess.run(args, cwd=ROOT, check=True, text=True, encoding='utf-8',
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ''


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPO:
        raise RuntimeError('Publishing is restricted to this repository\'s GitHub Actions workflow')
    if os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise RuntimeError('Run this workflow from main')
    if run('git', 'status', '--porcelain', capture=True):
        raise RuntimeError('Checkout contains unexpected local changes')
    run('git', 'fetch', 'origin', 'main', 'developing')
    ahead = int(run('git', 'rev-list', '--count', 'origin/main..origin/developing', capture=True))
    if ahead:
        raise RuntimeError('developing has unmerged commits; merge or review that work before refreshing')
    run('git', 'checkout', '-B', 'developing', 'origin/developing')
    run('git', 'merge', '--ff-only', 'origin/main')
    run(sys.executable, 'scripts/update_stats.py')
    run(sys.executable, 'scripts/validate_stats.py')
    changed = set(run('git', 'diff', '--name-only', capture=True).splitlines())
    if changed - set(FILES):
        raise RuntimeError('Refresh changed files outside the generated statistics allowlist')
    if run('git', 'ls-files', '--others', '--exclude-standard', capture=True):
        raise RuntimeError('Refresh created unexpected untracked files')
    if not changed:
        print('Statistics are already current')
        return
    run('git', 'config', 'user.name', 'github-actions[bot]')
    run('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    run('git', 'add', '--', *FILES)
    run('git', 'commit', '-m', 'chore: refresh GitHub profile statistics')
    head = run('git', 'rev-parse', 'HEAD', capture=True)
    # A normal push rejects concurrent branch changes; never force-push.
    run('git', 'push', 'origin', 'HEAD:developing')
    body = Path(os.environ['RUNNER_TEMP']) / 'profile-statistics-pr.md'
    body.write_text('Refresh the public GitHub star counts, language distribution, and contribution calendar.\n\n'
                    'The snapshot and both SVG calendars passed validation. Only the four generated files are included.\n',
                    encoding='utf-8')
    url = run('gh', 'pr', 'create', '--repo', REPO, '--base', 'main', '--head', 'developing',
              '--title', 'chore: refresh GitHub profile statistics', '--body-file', str(body), capture=True)
    run('gh', 'pr', 'merge', url, '--repo', REPO, '--merge', '--match-head-commit', head)
    info = json.loads(run('gh', 'pr', 'view', url, '--repo', REPO, '--json', 'state,url,mergeCommit', capture=True))
    if info['state'] != 'MERGED':
        raise RuntimeError('Statistics pull request has not merged')
    print(f'Published through {info["url"]}')


if __name__ == '__main__':
    main()

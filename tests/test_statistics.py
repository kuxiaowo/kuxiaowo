"""Regression coverage for week-aligned calendars and safe scheduled retries."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from update_stats import PublicCalendar, render_svg, validate_calendar_days
import validate_stats
import publish_stats

FIXTURE = Path(__file__).parent / 'fixtures' / 'calendar-2026-11-03.html'


def calendar_parser():
    parser = PublicCalendar()
    parser.feed(FIXTURE.read_text(encoding='utf-8'))
    return parser


class CalendarTests(unittest.TestCase):
    def test_real_367_day_calendar(self):
        days = calendar_parser().days()
        self.assertEqual(len(days), 367)
        self.assertEqual((days[0]['date'], days[-1]['date']), ('2025-11-02', '2026-11-03'))
        self.assertEqual(sum(d['count'] for d in days), 1803)

    def test_missing_tooltip_is_rejected(self):
        parser = calendar_parser()
        parser.tips.pop('day-100')
        with self.assertRaisesRegex(ValueError, 'Missing public calendar counts'):
            parser.days()

    def test_missing_internal_day_is_rejected_even_with_allowed_length(self):
        parser = calendar_parser()
        parser.cells.pop('day-100')
        parser.tips.pop('day-100')
        with self.assertRaisesRegex(ValueError, 'Nonconsecutive'):
            parser.days()

    def test_week_alignment_bounds(self):
        for count in range(364, 374):
            with self.subTest(days=count):
                days = [dict(date=(date(2024, 1, 1)+timedelta(days=i)).isoformat(), count=0, level=0)
                        for i in range(count)]
                if 365 <= count <= 372:
                    validate_calendar_days(days)
                else:
                    with self.assertRaises(ValueError):
                        validate_calendar_days(days)

    def test_duplicate_date_is_rejected(self):
        days = calendar_parser().days()
        days[10]['date'] = days[9]['date']
        with self.assertRaisesRegex(ValueError, 'Nonconsecutive'):
            validate_calendar_days(days)

    def test_real_calendar_passes_full_snapshot_and_svg_validation(self):
        data = json.loads((ROOT / 'stats-data.json').read_text(encoding='utf-8'))
        days = calendar_parser().days()
        counts = [d['count'] for d in days]
        streak = best = 0
        for count in counts:
            streak = streak+1 if count else 0
            best = max(streak, best)
        data['contributions'] = dict(days=days, start=days[0]['date'], end=days[-1]['date'],
            total=sum(counts), current_streak=streak, longest_streak=best,
            highest_day=max(counts), average_day=sum(counts)/len(days))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(ROOT / 'assets', root / 'assets')
            shutil.copyfile(ROOT / 'README.md', root / 'README.md')
            for compact, name in [(False, 'github-stats.svg'), (True, 'github-stats-compact.svg')]:
                (root / 'assets' / name).write_text(render_svg(data, compact), encoding='utf-8')
            snapshot = root / 'stats-data.json'
            snapshot.write_text(json.dumps(data), encoding='utf-8')
            with patch.object(validate_stats, 'ROOT', root):
                validate_stats.validate()
                corrupted = deepcopy(data)
                corrupted['contributions']['total'] += 1
                snapshot.write_text(json.dumps(corrupted), encoding='utf-8')
                with self.assertRaisesRegex(AssertionError, 'Contribution sum mismatch'):
                    validate_stats.validate()


class ScheduledRefreshTests(unittest.TestCase):
    def test_same_shanghai_day_is_skipped(self):
        now = datetime(2026, 11, 3, 17, 17, tzinfo=publish_stats.SHANGHAI)
        self.assertTrue(publish_stats.should_skip_refresh('schedule', {'updated_at':'2026-11-03T01:17:00Z'}, now))
        self.assertFalse(publish_stats.should_skip_refresh('schedule', {'updated_at':'2026-11-02T15:59:59Z'}, now))

    def test_manual_and_push_always_refresh(self):
        now = datetime(2026, 11, 3, 17, 17, tzinfo=publish_stats.SHANGHAI)
        for event in ['push', 'workflow_dispatch']:
            self.assertFalse(publish_stats.should_skip_refresh(event, {'updated_at':now.isoformat()}, now))

    def test_invalid_naive_and_future_dates_are_not_successful_snapshots(self):
        now = datetime(2026, 11, 3, 17, 17, tzinfo=publish_stats.SHANGHAI)
        for timestamp in [None, 'invalid', '2026-11-03T01:00:00', '2026-11-03T23:00:00+08:00']:
            with self.subTest(timestamp=timestamp):
                self.assertFalse(publish_stats.should_skip_refresh('schedule', {'updated_at':timestamp}, now))

    def test_schedule_skip_does_not_generate_commit_push_or_open_pr(self):
        env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='kuxiaowo/kuxiaowo',
                   GITHUB_REF='refs/heads/main', GITHUB_EVENT_NAME='schedule')
        def fake_run(*args, **kwargs):
            return '0' if args[:3] == ('git', 'rev-list', '--count') else ''
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'stats-data.json').write_text(json.dumps({'updated_at':datetime.now(timezone.utc).isoformat()}), encoding='utf-8')
            with patch.dict(os.environ, env), patch.object(publish_stats, 'ROOT', root), \
                 patch.object(publish_stats, 'run', side_effect=fake_run) as runner:
                publish_stats.main()
                calls = [c.args for c in runner.call_args_list]
                self.assertIn((sys.executable, 'scripts/validate_stats.py'), calls)
                self.assertFalse(any('scripts/update_stats.py' in c or 'commit' in c or 'push' in c or 'gh' in c for c in calls))

    def test_unmerged_developing_work_still_blocks_publication(self):
        env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='kuxiaowo/kuxiaowo',
                   GITHUB_REF='refs/heads/main', GITHUB_EVENT_NAME='schedule')
        def fake_run(*args, **kwargs):
            return '1' if args[:3] == ('git', 'rev-list', '--count') else ''
        with patch.dict(os.environ, env), patch.object(publish_stats, 'run', side_effect=fake_run) as runner:
            with self.assertRaisesRegex(RuntimeError, 'unmerged commits'):
                publish_stats.main()
            self.assertFalse(any('checkout' in c.args or 'push' in c.args or 'gh' in c.args for c in runner.call_args_list))


if __name__ == '__main__':
    unittest.main()

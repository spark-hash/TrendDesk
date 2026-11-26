from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.market import ET
from app.market_studies import StudyFeed
from app.store import Store
from app.study_journal import StudyJournal, next_bar


def test_section_requests_do_not_load_unrelated_sources(tmp_path, monkeypatch):
    feed = StudyFeed(SimpleNamespace(store=Store(tmp_path / 'isolated.db')))
    called = []

    def external(code, now, section):
        called.append(section)
        return {'fund': {}, 'minute': [], 'errors': {}}

    monkeypatch.setattr(feed, 'external', external)
    for section in ('structure', 'longterm', 'intraday', 'fundamental'):
        assert set(feed.read('AAPL', '1D', section)['sections']) == {section}
        assert called == ([section] if section in ('intraday', 'fundamental') else [])
        called.clear()


def test_first_confirmation_and_incremental_outcomes(tmp_path, monkeypatch):
    engine = SimpleNamespace(store=Store(tmp_path / 'journal.db'))
    journal = StudyJournal(engine, None)
    start = datetime(2026, 11, 25, 9, 30, tzinfo=ET)
    rows = [dict(time=(start + timedelta(minutes=15*i)).isoformat(), close=100+i, low=97+i) for i in range(24)]
    rows[1]['low'] = 12  # The drawdown window starts after the confirming close.

    def observed(run, i, tf):
        return {'channel': {'status': '上升通道', 'facts': ['触发条件']}} if 101 <= run[i]['close'] <= 107 else {}

    monkeypatch.setattr('app.study_journal.observations_at', observed)
    asof = start + timedelta(hours=8)
    journal.scan('AAPL', '15m', rows[:4], asof)
    first = journal.report('AAPL', '15m', 5, 'channel')
    assert first['groups'][0]['total'] == 1 and first['groups'][0]['mature'] == 0
    journal = StudyJournal(engine, None)
    journal.scan('AAPL', '15m', rows, asof)
    result = journal.report('AAPL', '15m', 5, 'channel')
    assert result['groups'][0]['total'] == result['groups'][0]['mature'] == 1
    item = result['latest'][0]
    assert item['evidence'] == first['latest'][0]['evidence']
    assert item['confirmed'] == (start + timedelta(minutes=30)).isoformat()
    assert item['return_pct'] == pytest.approx(100*(106/101-1))
    assert item['mae_pct'] == pytest.approx(100*(1-99/101))
    assert journal.report('AAPL', '15m', 20, '')['groups'][0]['mature'] == 1
    journal.scan('MSFT', '15m', rows[:4]+rows[5:], asof)
    msft = journal.report('MSFT', '15m', 5, '')['latest']
    assert next(r for r in msft if r['price']==101)['return_pct'] is None


def test_next_bar_crosses_holiday_and_short_session():
    assert next_bar('2026-11-25T15:30:00-05:00','60m').isoformat() == '2026-11-27T09:30:00-05:00'
    assert next_bar('2026-11-27T12:59:00-05:00','1m').isoformat() == '2026-11-30T09:30:00-05:00'

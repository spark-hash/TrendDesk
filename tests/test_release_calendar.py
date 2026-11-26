from datetime import datetime

import httpx
from app import release_calendar as cal
from app.store import Store


def test_calendar_folding_timezones_and_fallback(tmp_path, monkeypatch):
    data = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Personal Income and Outlays\\, Novem
 ber 2026
DTSTART;VALUE=DATE-TIME:20261223T133000Z
END:VEVENT
END:VCALENDAR"""
    rows = cal.parse_feed('BEA',data)
    assert rows[0]['at'] == '2026-12-23T08:30:00-05:00'
    assert rows[0]['detail'].endswith(', November 2026')
    assert not cal.parse_feed('BEA',data.replace('20261223T133000Z','20260723T123000Z'))[0]['at'].endswith('-05:00')
    service = cal.ReleaseCalendar(Store(tmp_path/'calendar.db'))
    def fetch(source):
        if source=='BLS':
            raise httpx.ConnectError('offline')
        return rows
    monkeypatch.setattr(service,'fetch',fetch)
    monkeypatch.setattr(cal,'now_utc',lambda: datetime.fromisoformat('2026-11-26T12:00:00+00:00'))
    result=service.read()
    assert result['errors']==['BLS']
    assert sum(row['cached'] for row in result['events'])==4
    assert result['events'][-1]['source']=='BEA'


def test_reorder_survives_restart_and_edits(tmp_path):
    path=tmp_path/'list.db'
    store=Store(path)
    initial=store.watchlist()
    store.move_watch(initial[-1],initial[0],False)
    store.add('MU')
    store.remove(initial[1])
    assert Store(path).watchlist()==[initial[-1],initial[0],*initial[2:-1],'MU']

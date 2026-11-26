import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone

DEFAULTS = {'port':11111, 'notifications':False, 'volume_multiple':1.5, 'near_percent':.5}
SYMBOLS = ['NVDA','AAPL','MSFT','TSLA','AMD','AMZN','META','GOOGL']

class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS watchlist(symbol TEXT PRIMARY KEY, added TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS bars(symbol TEXT,tf TEXT,time TEXT,data TEXT,PRIMARY KEY(symbol,tf,time));
        CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT,kind TEXT,title TEXT,detail TEXT,price REAL,bar_time TEXT,created TEXT,seen INTEGER DEFAULT 0,payload TEXT);
        CREATE TABLE IF NOT EXISTS latches(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS backtests(id TEXT PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS study_observations(
            id INTEGER PRIMARY KEY,symbol TEXT NOT NULL,tf TEXT NOT NULL,kind TEXT NOT NULL,
            episode TEXT NOT NULL,bar_time TEXT NOT NULL,confirmed TEXT NOT NULL,recorded TEXT NOT NULL,
            price REAL NOT NULL,evidence TEXT NOT NULL,UNIQUE(symbol,tf,kind,episode));
        CREATE INDEX IF NOT EXISTS study_obs_time ON study_observations(symbol,tf,bar_time);
        CREATE TABLE IF NOT EXISTS platform_returns(
            observation INTEGER NOT NULL,horizon INTEGER NOT NULL,reentered INTEGER NOT NULL,
            PRIMARY KEY(observation,horizon));
        CREATE TABLE IF NOT EXISTS study_outcomes(
            observation INTEGER NOT NULL,horizon INTEGER NOT NULL,return_pct REAL NOT NULL,mae_pct REAL NOT NULL,
            PRIMARY KEY(observation,horizon));
        ''')
        if self.get('initialized') is None:
            self.db.executemany('INSERT OR IGNORE INTO watchlist(symbol) VALUES (?)', [(s,) for s in SYMBOLS])
            self.set('initialized', True)
        if self.get('bar_schema') != 2:
            # Discard only regenerable price cache when timestamp semantics change.
            self.db.execute('DELETE FROM bars')
            self.set('bar_schema',2)
        self.db.commit()
        if 'sort_index' not in {r[1] for r in self.db.execute('PRAGMA table_info(watchlist)')}:
            with self.db:
                self.db.execute('ALTER TABLE watchlist ADD COLUMN sort_index INTEGER')

    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.set_many({key:value})

    def set_many(self, values):
        with self.lock, self.db:
            self.db.executemany('INSERT OR REPLACE INTO kv VALUES (?,?)',
                                [(key,json.dumps(value)) for key,value in values.items()])

    def settings(self):
        return DEFAULTS | self.get('settings', {})

    def watchlist(self):
        with self.lock:
            return [r[0] for r in self.db.execute('SELECT symbol FROM watchlist ORDER BY sort_index IS NULL,sort_index,added,rowid')]

    def move_watch(self, symbol, anchor, after):
        with self.lock, self.db:
            order = self.watchlist()
            if symbol not in order or anchor not in order:
                raise ValueError('自选列表已变化，请刷新后再拖动')
            if symbol != anchor:
                order.remove(symbol)
                order.insert(order.index(anchor) + int(after), symbol)
                self.db.executemany('UPDATE watchlist SET sort_index=? WHERE symbol=?', enumerate(order))
            return order

    def add(self, symbol):
        with self.lock, self.db:
            self.db.execute('INSERT OR IGNORE INTO watchlist(symbol) VALUES (?)',(symbol,))

    def remove(self, symbol):
        with self.lock, self.db:
            self.db.execute('DELETE FROM watchlist WHERE symbol=?',(symbol,))

    def bars(self, symbol, tf):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM bars WHERE symbol=? AND tf=? ORDER BY time',(symbol,tf))]

    def put_bars(self, symbol, tf, bars, replace=False):
        with self.lock, self.db:
            if replace:
                self.db.execute('DELETE FROM bars WHERE symbol=? AND tf=?',(symbol,tf))
            self.db.executemany('INSERT OR REPLACE INTO bars VALUES (?,?,?,?)',
                                [(symbol,tf,b['time'],json.dumps(b)) for b in bars])

    def positions(self):
        with self.lock:
            return {r[0]:json.loads(r[1]) for r in self.db.execute('SELECT symbol,data FROM positions')}

    def position(self, symbol, value):
        with self.lock, self.db:
            if value is None:
                self.db.execute('DELETE FROM positions WHERE symbol=?',(symbol,))
            else:
                self.db.execute('INSERT OR REPLACE INTO positions VALUES (?,?)',(symbol,json.dumps(value)))
            # A changed plan is a new alert episode.
            self.db.execute('DELETE FROM latches WHERE key LIKE ?', (symbol+':risk:%',))

    def event(self, symbol, signal, price, bar_time, payload, dedupe, reset=False):
        with self.lock, self.db:
            row = self.db.execute('SELECT value FROM latches WHERE key=?',(dedupe,)).fetchone()
            if reset:
                self.db.execute('DELETE FROM latches WHERE key=?',(dedupe,))
                return False
            if row and row[0] == bar_time:
                return False
            self.db.execute('INSERT OR REPLACE INTO latches VALUES (?,?)',(dedupe,bar_time))
            self.db.execute('INSERT INTO events(symbol,kind,title,detail,price,bar_time,created,payload) VALUES (?,?,?,?,?,?,?,?)',
                            (symbol,signal['kind'],signal['title'],signal['detail'],price,payload.get('bar_time',bar_time),
                             datetime.now(timezone.utc).isoformat(),json.dumps(payload)))
            return True

    def latch(self, key):
        with self.lock:
            row = self.db.execute('SELECT value FROM latches WHERE key=?',(key,)).fetchone()
            return row[0] if row else None

    def events(self, limit=100):
        with self.lock:
            return [dict(r) | {'payload':json.loads(r['payload'])} for r in self.db.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?',(limit,))]

    def acknowledge(self):
        with self.lock, self.db:
            self.db.execute('UPDATE events SET seen=1 WHERE seen=0')

    def save_backtest(self, job):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO backtests VALUES (?,?)',(job['id'],json.dumps(job,allow_nan=False)))

    def backtest(self, job_id):
        with self.lock:
            row=self.db.execute('SELECT data FROM backtests WHERE id=?',(job_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def backtests(self, limit=10):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM backtests ORDER BY id DESC LIMIT ?',(limit,))]

import json
import sqlite3


class Storage:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS history (timestamp REAL, wallex_bid REAL, wallex_ask REAL, nobitex_bid REAL, nobitex_ask REAL, spread_a REAL, spread_b REAL, source TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT)')

    def connect(self):
        return sqlite3.connect(self.path)

    def settings(self, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE id=1').fetchone()
        return json.loads(row[0]) if row else default

    def save_settings(self, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (1, ?)', (json.dumps(value),))

    def record(self, timestamp, w, n):
        with self.connect() as db:
            db.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?,?)', (timestamp, w.bids[0][0], w.asks[0][0], n.bids[0][0], n.asks[0][0], (n.bids[0][0]/w.asks[0][0]-1)*100, (w.bids[0][0]/n.asks[0][0]-1)*100, 'manual' if 'manual' in (w.source, n.source) else 'live'))

    def history(self, limit=1000):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM (SELECT rowid,* FROM history ORDER BY rowid DESC LIMIT ?) ORDER BY rowid', (limit,))]

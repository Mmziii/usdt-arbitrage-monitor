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

    def init_scanner(self):
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS network_fees (exchange TEXT, coin TEXT, network TEXT, withdrawal REAL, minimum REAL, supported INTEGER NOT NULL, PRIMARY KEY(exchange,coin,network))')
            db.execute('CREATE TABLE IF NOT EXISTS scan_history (timestamp REAL, coin TEXT, quote TEXT, wallex_bid REAL, wallex_ask REAL, nobitex_bid REAL, nobitex_ask REAL, spread_a REAL, spread_b REAL)')
            db.execute('CREATE INDEX IF NOT EXISTS scan_history_lookup ON scan_history(coin,quote,timestamp)')
            db.execute('CREATE TABLE IF NOT EXISTS scanner_settings (id INTEGER PRIMARY KEY, value TEXT)')

    def scanner_settings(self):
        with self.connect() as db:
            row = db.execute('SELECT value FROM scanner_settings WHERE id=1').fetchone()
            return json.loads(row[0]) if row else {}

    def save_scanner_settings(self, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO scanner_settings VALUES (1,?)', (json.dumps(value),))

    def fees(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM network_fees ORDER BY coin,network,exchange')]

    def replace_fees(self, rows):
        with self.connect() as db:
            db.execute('DELETE FROM network_fees')
            db.executemany('INSERT INTO network_fees VALUES (?,?,?,?,?,?)', [(r['exchange'],r['coin'],r['network'],r['withdrawal'],r['minimum'],int(r['supported'])) for r in rows])

    def scan_record(self, rows, retention_days):
        import time
        with self.connect() as db:
            db.executemany('INSERT INTO scan_history VALUES (?,?,?,?,?,?,?,?,?)', rows)
            cutoff = time.time() - retention_days * 86400
            db.execute('DELETE FROM scan_history WHERE timestamp < ?', (cutoff,))
            db.execute('DELETE FROM history WHERE timestamp < ?', (cutoff,))

    def scan_history(self, coin=None, quote=None, limit=1000):
        query = 'SELECT * FROM scan_history WHERE (? IS NULL OR coin=?) AND (? IS NULL OR quote=?) ORDER BY timestamp DESC LIMIT ?'
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return list(reversed([dict(r) for r in db.execute(query, (coin,coin,quote,quote,limit))]))

import json
import sqlite3


class Storage:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS history (timestamp REAL, wallex_bid REAL, wallex_ask REAL, nobitex_bid REAL, nobitex_ask REAL, spread_a REAL, spread_b REAL, source TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT)')
        self.init_ui()

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

    def init_ui(self):
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS ui_state (key TEXT PRIMARY KEY, value TEXT)')
            db.execute('''CREATE TABLE IF NOT EXISTS simulations (
                id INTEGER PRIMARY KEY, created REAL, key TEXT, coin TEXT, route TEXT,
                route_label TEXT, mode TEXT, capital REAL, unit TEXT, expected_final REAL,
                expected_profit REAL, expected_pct REAL, prices TEXT, transfer_minutes REAL,
                due REAL, status TEXT, actual_final REAL, actual_profit REAL, actual_pct REAL,
                difference REAL, completed REAL, note TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY, date TEXT, coin TEXT, route TEXT, mode TEXT,
                capital REAL, final_amount REAL, profit REAL, fees TEXT, note TEXT,
                created REAL)''')

    def ui_state(self):
        with self.connect() as db:
            return {key: json.loads(value) for key, value in
                    db.execute('SELECT key, value FROM ui_state').fetchall()}

    def save_ui_state(self, values):
        with self.connect() as db:
            for key, value in values.items():
                db.execute('INSERT OR REPLACE INTO ui_state VALUES (?,?)',
                           (key, json.dumps(value)))

    def pinned_coins(self):
        pins = self.ui_state().get('pins', [])
        return [str(coin) for coin in pins] if isinstance(pins, list) else []

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
        with self.connect() as db:
            db.executemany('INSERT INTO scan_history VALUES (?,?,?,?,?,?,?,?,?)', rows)
        self.prune(retention_days)

    def prune(self, retention_days):
        import time
        cutoff = time.time() - retention_days * 86400
        with self.connect() as db:
            db.execute('DELETE FROM scan_history WHERE timestamp < ?', (cutoff,))
            db.execute('DELETE FROM history WHERE timestamp < ?', (cutoff,))

    def simulations(self, limit=200):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                'SELECT * FROM simulations ORDER BY id DESC LIMIT ?', (limit,))]

    def simulation(self, simulation_id):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM simulations WHERE id=?', (simulation_id,)).fetchone()
            return dict(row) if row else None

    def add_simulation(self, values):
        keys = list(values)
        with self.connect() as db:
            cursor = db.execute(
                'INSERT INTO simulations (' + ','.join(keys) + ') VALUES (' +
                ','.join('?' * len(keys)) + ')', tuple(values[key] for key in keys))
            return cursor.lastrowid

    def update_simulation(self, simulation_id, values):
        keys = list(values)
        with self.connect() as db:
            db.execute('UPDATE simulations SET ' + ','.join(key + '=?' for key in keys) +
                       ' WHERE id=?', tuple(values[key] for key in keys) + (simulation_id,))

    def pending_simulations(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                "SELECT * FROM simulations WHERE status='pending' ORDER BY id")]

    def journal(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM journal ORDER BY date DESC, id DESC')]

    def add_journal(self, values):
        keys = list(values)
        with self.connect() as db:
            cursor = db.execute('INSERT INTO journal (' + ','.join(keys) + ') VALUES (' +
                                ','.join('?' * len(keys)) + ')',
                                tuple(values[key] for key in keys))
            return cursor.lastrowid

    def delete_journal(self, entry_id):
        with self.connect() as db:
            db.execute('DELETE FROM journal WHERE id=?', (entry_id,))

    def delete_simulation(self, simulation_id):
        with self.connect() as db:
            db.execute('DELETE FROM simulations WHERE id=?', (simulation_id,))

    def scan_history(self, coin=None, quote=None, limit=1000):
        query = 'SELECT * FROM scan_history WHERE (? IS NULL OR coin=?) AND (? IS NULL OR quote=?) ORDER BY timestamp DESC LIMIT ?'
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return list(reversed([dict(r) for r in db.execute(query, (coin,coin,quote,quote,limit))]))

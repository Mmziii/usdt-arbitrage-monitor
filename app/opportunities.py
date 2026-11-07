"""Persistent observation state machine; UI reads never create observations."""
import json
import math
from datetime import datetime, timezone


class OpportunityTracker:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS opportunity_state (key TEXT PRIMARY KEY, value TEXT, updated REAL)')
            db.execute('''CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY, key TEXT, coin TEXT, quote TEXT, source TEXT,
                destination TEXT, mode TEXT, network TEXT, start REAL, end REAL,
                duration REAL, peak_pct REAL, capital_at_peak REAL, unknown_gaps INTEGER)''')
            db.execute('CREATE INDEX IF NOT EXISTS opportunity_end ON opportunities(end)')

    def observe(self, row, timestamp, confirmations=2, known=True):
        mode = row['trading_mode']
        key = row['row_key'] + ':' + mode + ':' + (row.get('network') or '')
        with self.store.connect() as db:
            found = db.execute('SELECT value FROM opportunity_state WHERE key=?', (key,)).fetchone()
            state = json.loads(found[0]) if found else {'active': None, 'last': None, 'negative': 0}
            result = row.get('taker')
            known = known and row.get('status') == 'ok' and result is not None
            stamp = row.get('depth_timestamp')
            if not known or stamp == state['last']:
                if state['active'] is not None:
                    db.execute('UPDATE opportunities SET unknown_gaps=unknown_gaps+1 WHERE id=?', (state['active'],))
                state['negative'] = 0
            else:
                state['last'] = stamp
                if result['profit'] > 0:
                    state['negative'] = 0
                    if state['active'] is None:
                        cursor = db.execute('''INSERT INTO opportunities (key,coin,quote,source,destination,mode,network,start,peak_pct,capital_at_peak,unknown_gaps)
                            VALUES (?,?,?,?,?,?,?,?,?,?,0)''', (key,row['coin'],row['quote'],row['source'],row['destination'],mode,row.get('network'),timestamp,result['profit_pct'],result['capital']))
                        state['active'] = cursor.lastrowid
                    else:
                        db.execute('UPDATE opportunities SET peak_pct=?, capital_at_peak=? WHERE id=? AND peak_pct<?', (result['profit_pct'],result['capital'],state['active'],result['profit_pct']))
                elif state['active'] is not None:
                    if state['negative'] == 0:
                        state['end_candidate'] = timestamp
                    state['negative'] += 1
                    if state['negative'] >= confirmations:
                        end = state['end_candidate']
                        db.execute('UPDATE opportunities SET end=?, duration=?-start WHERE id=?', (end,end,state['active']))
                        state['active'] = None
                        state['negative'] = 0
            db.execute('INSERT OR REPLACE INTO opportunity_state VALUES (?,?,?)', (key,json.dumps(state),timestamp))

    def cycle(self, rows, timestamp, confirmations=2, known=True):
        # Mark formerly tracked contexts (changed mode/network or removed market) unknown too.
        keys = {r['row_key'] + ':' + r['trading_mode'] + ':' + (r.get('network') or '') for r in rows}
        with self.store.connect() as db:
            for key, value in db.execute('SELECT key,value FROM opportunity_state').fetchall():
                if key not in keys:
                    state = json.loads(value)
                    if state['active'] is not None:
                        db.execute('UPDATE opportunities SET unknown_gaps=unknown_gaps+1 WHERE id=?', (state['active'],))
                    state['negative'] = 0
                    db.execute('UPDATE opportunity_state SET value=? WHERE key=?', (json.dumps(state),key))
        for row in rows:
            self.observe(row, timestamp, confirmations, known)

    def rows(self, coin=None, mode=None):
        with self.store.connect() as db:
            import sqlite3
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM opportunities WHERE (? IS NULL OR coin=?) AND (? IS NULL OR mode=?) ORDER BY start DESC', (coin,coin,mode,mode))]

    def prune(self, cutoff):
        with self.store.connect() as db:
            db.execute('DELETE FROM opportunities WHERE COALESCE(end,start)<?', (cutoff,))
            db.execute('DELETE FROM opportunity_state WHERE updated<?', (cutoff,))
            # An ongoing observation may outlive retention; let its next positive sample restart.
            for key, value in db.execute('SELECT key,value FROM opportunity_state').fetchall():
                state = json.loads(value)
                if state['active'] is not None and not db.execute('SELECT 1 FROM opportunities WHERE id=?', (state['active'],)).fetchone():
                    state['active'] = None
                    db.execute('UPDATE opportunity_state SET value=? WHERE key=?', (json.dumps(state),key))


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    x = (len(values)-1)*p
    i = math.floor(x); j = math.ceil(x)
    return values[i] + (values[j]-values[i])*(x-i)


def statistics(rows, transfer_minutes=None):
    closed = [r for r in rows if r['duration'] is not None]
    # Unknown gaps make durations interval-uncertain; don't present them as exact.
    exact = [r for r in closed if not r['unknown_gaps']]
    durations = [r['duration'] for r in exact]
    share = sum(d < transfer_minutes*60 for d in durations)/len(durations)*100 if durations and transfer_minutes is not None else None
    hours = {str(h): 0 for h in range(24)}
    for r in rows:
        hours[str(datetime.fromtimestamp(r['start'], timezone.utc).hour)] += 1
    return dict(count=len(rows), closed_count=len(closed), active_count=len(rows)-len(closed), exact_duration_count=len(exact),
                uncertain_count=sum(bool(r['unknown_gaps']) for r in rows), median_seconds=percentile(durations,.5),
                p90_seconds=percentile(durations,.9), shorter_than_transfer_pct=share,
                best_peak_pct=max((r['peak_pct'] for r in rows), default=None), by_hour_utc=hours)

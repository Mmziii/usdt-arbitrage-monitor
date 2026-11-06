"""Explicitly configured network data only; no invented fees or support."""

def resolve(rows, coin, source, selected=None):
    entries = {(r['exchange'], r['network']): r for r in rows if r['coin'] == coin}
    networks = sorted({network for exchange, network in entries if exchange == 'wallex' and entries[(exchange, network)]['supported'] and entries.get(('nobitex', network), {}).get('supported')})
    if not networks:
        exchanges = {exchange for exchange, _ in entries}
        return {'status': 'no common network' if exchanges == {'wallex', 'nobitex'} else 'network unknown', 'networks': []}
    network = selected or networks[0]
    if network not in networks:
        return {'status': 'no common network', 'networks': networks}
    fee = entries[(source, network)]
    if fee['withdrawal'] is None:
        return {'status': 'fee unknown', 'network': network, 'networks': networks}
    if fee['minimum'] is None:
        return {'status': 'minimum unknown', 'network': network, 'networks': networks}
    return {'status': 'ok', 'network': network, 'networks': networks, 'withdrawal': fee['withdrawal'], 'minimum': fee['minimum']}


def parse_pasted_fees(text):
    """Parse untrusted lines without making any network-support assumptions."""
    import csv
    import math
    import re
    from .symbols import normalize

    parsed, errors, seen = [], [], set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            fields = next(csv.reader([line], strict=True))
            if len(fields) not in (4, 5):
                raise ValueError('چهار یا پنج ستون لازم است')
            coin = normalize(fields[0])
            network = fields[1].strip().upper()
            exchange = fields[2].strip().lower()
            if not re.fullmatch(r'[A-Z0-9_-]{1,40}', network):
                raise ValueError('نام شبکه نامعتبر است')
            if exchange not in ('wallex', 'nobitex'):
                raise ValueError('صرافی باید wallex یا nobitex باشد')
            fee = float(fields[3].strip())
            if not math.isfinite(fee) or fee < 0:
                raise ValueError('کارمزد باید عدد غیرمنفی باشد')
            row = {'coin': coin, 'network': network, 'exchange': exchange, 'withdrawal': fee}
            if len(fields) == 5:
                minimum = float(fields[4].strip())
                if not math.isfinite(minimum) or minimum < 0:
                    raise ValueError('حداقل برداشت باید عدد غیرمنفی باشد')
                row['minimum'] = minimum
            key = (coin, network, exchange)
            if key in seen:
                raise ValueError('ردیف تکراری در فهرست')
            seen.add(key)
            parsed.append(row)
        except (ValueError, csv.Error) as exc:
            errors.append({'line': line_number, 'message': str(exc)})
    return {'rows': parsed, 'errors': errors}

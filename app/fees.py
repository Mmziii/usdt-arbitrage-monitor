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

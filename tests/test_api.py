import time
import pytest
from fastapi.testclient import TestClient
from app.fetchers import parse_book


def test_parsers():
    w=parse_book('wallex', {'success':True,'result':{'ask':[{'price':'101','quantity':'2'}],'bid':[{'price':'100','quantity':'3'}]}})
    n=parse_book('nobitex', {'status':'ok','lastUpdate':time.time()*1000,'asks':[['1010','2']],'bids':[['1000','3']]})
    assert w.asks == n.asks == [(101,2)]
    assert n.bids == [(100,3)]
    with pytest.raises(ValueError):
        parse_book('nobitex', {'status':'ok','lastUpdate':1,'asks':[['1010','2']],'bids':[['1000','3']]})
    with pytest.raises(ValueError):
        parse_book('wallex', {'success':True,'result':{'ask':[],'bid':[]}})


def test_api_manual_and_history(tmp_path, monkeypatch):
    from app import main
    from app.storage import Storage
    monkeypatch.setattr(main, 'store', Storage(str(tmp_path/'test.db')))
    monkeypatch.setattr(main, 'books', {})
    monkeypatch.setattr(main, 'manual', {})
    monkeypatch.setattr(main, 'errors', {})
    async def broken(*args):
        raise ValueError('changed schema')
    monkeypatch.setattr(main, 'fetch_book', broken)
    with TestClient(main.app) as client:
        # Let startup polling complete before checking fallback.
        for _ in range(100):
            if main.errors:
                break
            time.sleep(.01)
        assert 'wallex' in client.get('/api/snapshot').json()['errors']
        for n,p in [('wallex',100),('nobitex',110)]:
            assert client.put('/api/manual/'+n,json={'ask':p+1,'bid':p}).status_code==200
        snap=client.get('/api/snapshot?capital=100000').json()
        assert len(snap['rows'])==4
        assert snap['books']['wallex']['source']=='manual'
        assert client.get('/api/history').json()[0]['source']=='manual'
        assert 'spread_a' in client.get('/api/history.csv').text
        cfg=client.get('/api/settings').json()
        assert client.put('/api/settings',json=cfg).status_code==200
        assert client.put('/api/manual/wallex',json={'ask':99,'bid':100}).status_code==400
        assert client.get('/api/snapshot?capital=nan').status_code==400
        assert client.get('/').status_code==200

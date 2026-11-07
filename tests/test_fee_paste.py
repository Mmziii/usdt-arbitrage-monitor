from app.fees import parse_pasted_fees


def test_parse_and_preview_pasted_fees():
    result = parse_pasted_fees(' trX, Trc20, WALLEX, 1\nETH,ERC20,nobitex,0.005,0.1\n')
    assert result['errors'] == []
    assert result['rows'] == [
        {'coin':'TRX','network':'TRC20','exchange':'wallex','withdrawal':1.0},
        {'coin':'ETH','network':'ERC20','exchange':'nobitex','withdrawal':.005,'minimum':.1},
    ]
    assert all('supported' not in row for row in result['rows'])


def test_paste_errors_are_line_specific_and_reject_duplicates_and_nonfinite():
    result = parse_pasted_fees('BTC,BTC,wallex,0\nbtc,btc,WALLEX,1\nETH,ERC20,nobitex,nan\nX,,wallex,2\nSOL,SOL,other,1\nTRX,TRC20,wallex,1,-2\nwrong')
    assert len(result['rows']) == 1
    assert [e['line'] for e in result['errors']] == [2,3,4,5,6,7]


def test_preview_api_does_not_save(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from app.storage import Storage
    from app.scanner import Scanner
    scanner = Scanner(Storage(str(tmp_path/'test.db')))
    monkeypatch.setattr(main, 'scanner', scanner)
    client = TestClient(main.app)
    result = client.post('/api/scanner/fees/preview', json={'text':'TRX,TRC20,wallex,1'}).json()
    assert result['rows'][0]['withdrawal'] == 1
    assert scanner.store.fees() == []

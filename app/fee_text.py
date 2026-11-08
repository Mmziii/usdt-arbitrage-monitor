"""Best-effort reader for text pasted from an exchange's public fee page.

The user copies the withdrawal-fee table from the exchange's own page (or types it) and
this module finds ``coin / network / withdrawal fee / minimum withdrawal`` per line.
It is deliberately conservative: a line that does not contain a coin, a known network and a
number becomes a visible error, never a guessed fee. Numbers are never filled in for the
user and nothing is downloaded.
"""
import math
import re

from .symbols import normalize

ZWNJ = '\u200c'
ARABIC = '٠١٢٣٤٥٦٧٨٩'
PERSIAN = '۰۱۲۳۴۵۶۷۸۹'

# alias -> canonical network code (uppercase, as stored in the fee table)
NETWORKS = {
    'TRC20': 'TRC20', 'TRC-20': 'TRC20', 'TRON': 'TRC20', 'TRONTRC20': 'TRC20',
    'ERC20': 'ERC20', 'ERC-20': 'ERC20', 'ETHEREUM': 'ERC20', 'ETH': 'ERC20', 'ETHMAINNET': 'ERC20',
    'BEP20': 'BEP20', 'BEP-20': 'BEP20', 'BSC': 'BEP20', 'BSC20': 'BEP20',
    'BNBSMARTCHAIN': 'BEP20', 'BNB': 'BEP20',
    'BTC': 'BTC', 'BITCOIN': 'BTC', 'BITCOINNETWORK': 'BTC',
    'SOL': 'SOL', 'SOLANA': 'SOL', 'SPL': 'SOL',
    'TON': 'TON', 'TONCOIN': 'TON', 'THEOPENNETWORK': 'TON',
    'POL': 'POLYGON', 'POLYGON': 'POLYGON', 'MATIC': 'POLYGON',
    'AVAX': 'AVAXC', 'AVALANCHE': 'AVAXC', 'AVAXC': 'AVAXC',
    'ARB': 'ARB', 'ARBITRUM': 'ARB', 'ARBITRUMONE': 'ARB',
    'OP': 'OP', 'OPTIMISM': 'OP',
    'DOGE': 'DOGE', 'DOGECOIN': 'DOGE', 'LTC': 'LTC', 'LITECOIN': 'LTC',
    'XRP': 'XRP', 'RIPPLE': 'XRP', 'ADA': 'ADA', 'CARDANO': 'ADA',
    'DOT': 'DOT', 'POLKADOT': 'DOT', 'TRX': 'TRC20', 'NEAR': 'NEAR', 'APT': 'APT',
    'SUI': 'SUI', 'XLM': 'XLM', 'STELLAR': 'XLM', 'ALGO': 'ALGO', 'ATOM': 'ATOM',
    'EOS': 'EOS', 'KAS': 'KAS', 'FTM': 'FTM', 'CELO': 'CELO', 'ONE': 'ONE',
    # Persian names as they appear on Iranian exchange fee pages.
    'ترون': 'TRC20', 'اتریوم': 'ERC20', 'بایننساسمارتچین': 'BEP20', 'بیتکوین': 'BTC',
    'سولانا': 'SOL', 'تون': 'TON', 'پالیگان': 'POLYGON', 'آوالانچ': 'AVAXC',
    'آربیتروم': 'ARB', 'لایتکوین': 'LTC', 'دوجکوین': 'DOGE', 'ریپل': 'XRP',
}

# Symbols that are *also* network names but must still be read as a coin on their own
# ("BTC BTC 0.0005", "ETH BEP20 0.01").
COIN_ALIASES = {'BTC', 'ETH', 'USDT', 'USDC', 'USDD', 'DAI', 'TRX', 'BNB', 'SOL', 'TON',
                'DOGE', 'XRP', 'ADA', 'DOT', 'LTC', 'NEAR', 'SUI', 'XLM', 'ALGO', 'ATOM',
                'EOS', 'KAS', 'FTM', 'CELO', 'ONE', 'MATIC', 'POL', 'AVAX', 'ARB', 'OP'}

PERSIAN_COINS = {
    'تتر': 'USDT', 'بیت‌کوین': 'BTC', 'بیتکوین': 'BTC', 'اتریوم': 'ETH', 'اتریوم': 'ETH',
    'ترون': 'TRX', 'تون': 'TON', 'سولانا': 'SOL', 'دوج': 'DOGE', 'دوج‌کوین': 'DOGE',
    'ریپل': 'XRP', 'کاردانو': 'ADA', 'پولکادات': 'DOT', 'لایت‌کوین': 'LTC',
    'بایننس': 'BNB', 'نیر': 'NEAR', 'سویی': 'SUI', 'استلار': 'XLM', 'الگورند': 'ALGO',
}

STOPWORDS = {'شبکه', 'کارمزد', 'حداقل', 'برداشت', 'واریز', 'ارز', 'مقدار', 'نام',
             'NETWORK', 'FEE', 'WITHDRAWAL', 'MIN', 'MINIMUM', 'COIN', 'ASSET',
             'DEPOSIT', 'WITHDRAW', 'TOKEN', 'TYPE', 'AMOUNT', 'NAME', 'IRR', 'IRT',
             'TOMAN', 'RIAL', 'نوشته', 'غیرفعال', 'فعال', 'بله', 'خیر',
             'نیمه', 'شبکه‌', 'کارمزد‌', 'توضیح'}

NUMBER = re.compile(r'^[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)$')


def normalize_text(text):
    value = str(text or '')
    value = value.replace(ZWNJ, '').replace('\u200f', '').replace('\u200e', '')
    value = value.translate(str.maketrans(PERSIAN + ARABIC, '0123456789' * 2))
    value = value.replace('٫', '.').replace('٬', ',').replace('\u066b', '.')
    return value


def _cells(line):
    """Split a table row on tabs, pipes or runs of spaces.

    A pasted line that only uses single spaces (copied out of a PDF or a chat) is split on
    every space instead, so ``BTC TRC20 0.5 10`` still reads as a row.
    """
    line = line.strip()
    parts = re.split(r'\t+|\s*\|\s*|\s{2,}', line)
    cells = [part.strip() for part in parts if part.strip()]
    if len(cells) <= 1 and ' ' in line:
        cells = [part for part in re.split(r'\s+', line) if part]
    return cells


def _network_of(token):
    key = re.sub(r'[\s_()\-]', '', normalize_text(token).upper())
    if key in NETWORKS:
        return NETWORKS[key]
    for alias, code in NETWORKS.items():
        compact = re.sub(r'[\s_()\-]', '', alias)
        if compact and key == compact:
            return code
    return None


def _number(token):
    text = normalize_text(token).strip()
    text = text.replace(' ', '')
    # Persian pages sometimes write "0,0005" with a comma as the decimal mark.
    if text.count(',') == 1 and text.count('.') == 0:
        head, tail = text.split(',')
        if len(tail) != 3:
            text = head + '.' + tail
        else:
            text = head + tail
    elif text.count(',') > 0 and text.count('.') > 0:
        text = text.replace(',', '')
    elif text.count(',') > 1:
        text = text.replace(',', '')
    if not NUMBER.match(text):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


COIN_LIKE = re.compile(r'^[A-Za-z][A-Za-z0-9]{1,11}$')


def _tokens(cells):
    """Every word of every cell, in reading order (keeps the cell for context)."""
    for cell in cells:
        for word in re.split(r'[^\w\u0600-\u06ff]+', cell):
            word = word.strip()
            if word:
                yield cell, word


def _coin_of(cells):
    """The first token that can only be a coin symbol; network names are skipped."""
    for _cell, word in _tokens(cells):
        if word in PERSIAN_COINS:
            return PERSIAN_COINS[word]
        upper = word.upper()
        if upper in STOPWORDS or not COIN_LIKE.match(word):
            continue
        if not word.isupper() and upper not in COIN_ALIASES:
            continue
        if upper in NETWORKS and upper not in COIN_ALIASES:
            continue
        try:
            return normalize(upper)
        except ValueError:
            continue
    return None


def _networks_of(cells, coin):
    """Network codes in the line; the coin's own token is not counted as a network."""
    codes = []
    coin_names = {str(coin or '').upper()}
    coin_names |= {name for name, code in PERSIAN_COINS.items() if code == coin}
    coin_seen = False
    for _cell, word in _tokens(cells):
        upper = word.upper()
        if coin and (upper in {name.upper() for name in coin_names}) and not coin_seen:
            coin_seen = True                      # "BTC BTC ..." -> first BTC is the coin
            continue
        code = _network_of(word)
        if code and code not in codes:
            codes.append(code)
    return codes


def parse_page_text(text, exchange, default_supported=True):
    """Parse pasted fee-page text into rows plus per-line errors."""
    rows, errors, seen = [], [], set()
    for line_number, raw in enumerate(str(text or '').splitlines(), 1):
        line = raw.strip()
        if not line or len(line) < 3:
            continue
        if re.match(r'^[\-=_*\s]+$', line):
            continue
        cells = _cells(line)
        numbers = [value for value in (_number(cell) for cell in cells) if value is not None]
        if not numbers and not re.search(r'\d', line):
            continue                       # a header row ("Coin / Network / Fee") has no fee
        coin = _coin_of(cells)
        networks = _networks_of(cells, coin)
        problems = []
        if not networks:
            problems.append('شبکه شناخته نشد')
        if not numbers:
            problems.append('عدد کارمزد پیدا نشد')
        if not coin:
            problems.append('نماد ارز پیدا نشد')
        if problems:
            errors.append({'line': line_number, 'text': line[:120],
                           'message': '، '.join(problems) + '؛ این خط ذخیره نمی‌شود.'})
            continue
        network = networks[0]
        fee = numbers[0]
        minimum = numbers[1] if len(numbers) > 1 else None
        if minimum is not None and minimum < fee:
            # "min withdrawal" can never be smaller than the fee: treat the pair as swapped
            # only when it is unambiguous that the bigger number is the minimum.
            minimum, fee = numbers[0], numbers[1]
        key = (coin, network)
        if key in seen:
            errors.append({'line': line_number, 'text': line[:120],
                           'message': 'این ارز و شبکه در همین متن تکراری است؛ فقط اولی ذخیره می‌شود.'})
            continue
        seen.add(key)
        rows.append({'exchange': exchange, 'coin': coin, 'network': network,
                     'withdrawal': fee, 'minimum': minimum,
                     'supported': bool(default_supported), 'confidence': 'manual',
                     'source': 'assistant', 'fetched_at': None,
                     'note': '' if len(numbers) > 1 else 'حداقل برداشت در متن نبود؛ خالی ماند.'})
    return {'rows': rows, 'errors': errors, 'exchange': exchange}


def parse_csv(text, exchange):
    """CSV for the assistant: ``coin,network,fee[,minimum]`` (exchange comes from the dialog)."""
    import csv
    import io
    rows, errors, seen = [], [], set()
    reader = csv.reader(io.StringIO(normalize_text(text).lstrip('\ufeff')))
    for index, fields in enumerate(reader, 1):
        fields = [field.strip() for field in fields]
        if not any(fields):
            continue
        if len(fields) == 4 and fields[3].lower() in ('wallex', 'nobitex', 'bitunix'):
            fields = fields[:3] + fields[4:]
        if len(fields) not in (3, 4):
            errors.append({'line': index, 'text': ','.join(fields)[:120],
                           'message': 'سه یا چهار ستون لازم است: ارز، شبکه، کارمزد، حداقل برداشت.'})
            continue
        try:
            coin = normalize(fields[0])
        except ValueError:
            errors.append({'line': index, 'text': ','.join(fields)[:120],
                           'message': 'نماد ارز نامعتبر است.'})
            continue
        network = re.sub(r'[^A-Za-z0-9_-]', '', fields[1]).upper()
        if not network:
            errors.append({'line': index, 'text': ','.join(fields)[:120],
                           'message': 'نام شبکه خالی است.'})
            continue
        fee = _number(fields[2])
        if fee is None:
            errors.append({'line': index, 'text': ','.join(fields)[:120],
                           'message': 'کارمزد عدد معتبر نیست.'})
            continue
        minimum = None
        if len(fields) == 4 and fields[3] != '':
            minimum = _number(fields[3])
            if minimum is None:
                errors.append({'line': index, 'text': ','.join(fields)[:120],
                               'message': 'حداقل برداشت عدد معتبر نیست.'})
                continue
        key = (coin, network)
        if key in seen:
            errors.append({'line': index, 'text': ','.join(fields)[:120],
                           'message': 'ردیف تکراری.'})
            continue
        seen.add(key)
        rows.append({'exchange': exchange, 'coin': coin, 'network': network,
                     'withdrawal': fee, 'minimum': minimum, 'supported': True,
                     'confidence': 'manual', 'source': 'assistant', 'fetched_at': None,
                     'note': ''})
    return {'rows': rows, 'errors': errors, 'exchange': exchange}


def parse_any(text, exchange, kind='auto'):
    """Choose the reader by content: pages full of commas are treated as CSV first."""
    text = str(text or '')
    if kind == 'csv':
        return parse_csv(text, exchange)
    first = next((line for line in text.splitlines() if line.strip()), '')
    if ',' in first and not re.search(r'\s{2,}|\t|\|', first):
        result = parse_csv(text, exchange)
        if result['rows']:
            return result
    return parse_page_text(text, exchange)

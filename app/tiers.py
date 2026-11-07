"""User-supplied fee tiers. No exchange schedules are assumed."""
import csv
import io
import json
from pydantic import BaseModel, Field, ValidationError
from typing import Literal


class Tier(BaseModel):
    exchange: Literal['wallex', 'nobitex', 'bitunix']
    quote: Literal['toman', 'USDT']
    name: str = Field(min_length=1, max_length=80)
    threshold: float = Field(ge=0, allow_inf_nan=False)
    maker: float = Field(ge=0, lt=100, allow_inf_nan=False)
    taker: float = Field(ge=0, lt=100, allow_inf_nan=False)


def active_fees(settings, exchange, quote):
    key = exchange + ':' + quote
    selected = settings.current_tiers.get(key)
    for tier in settings.fee_tiers:
        if tier.exchange == exchange and tier.quote == quote and tier.name == selected:
            return {'maker': tier.maker, 'taker': tier.taker, 'fee_source': 'tier:' + tier.name}
    fees = getattr(settings, exchange if quote == 'toman' else exchange + '_usdt').model_dump()
    return {**fees, 'fee_source': 'global'}


def parse_tiers(text, format):
    try:
        rows = (json.loads(text) if format == 'json'
                else list(csv.DictReader(io.StringIO(text.lstrip('\ufeff')))))
    except json.JSONDecodeError:
        raise ValueError('متن JSON معتبر نیست؛ فایل خروجی سطح کارمزد را دوباره بارگذاری کنید.')
    if not isinstance(rows, list):
        raise ValueError('سطح کارمزد باید فهرستی از ردیف‌ها باشد.')
    tiers = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f'ردیف {index} سطح کارمزد ساختار درستی ندارد.')
        try:
            tiers.append(Tier.model_validate(row))
        except ValidationError as error:
            first = error.errors()[0]
            column = '.'.join(str(part) for part in first.get('loc', ())) or 'ردیف'
            raise ValueError(f'ردیف {index} سطح کارمزد نامعتبر است؛ ستون «{column}» را بررسی کنید.')
    keys = [(t.exchange, t.quote, t.name) for t in tiers]
    if len(keys) != len(set(keys)):
        raise ValueError('سطح تکراری')
    return tiers


def export_tiers(tiers, format):
    rows = [t.model_dump() for t in tiers]
    if format == 'json':
        return json.dumps(rows, ensure_ascii=False, indent=2)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(Tier.model_fields))
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue()

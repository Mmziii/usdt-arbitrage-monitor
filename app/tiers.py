"""User-supplied fee tiers. No exchange schedules are assumed."""
import csv
import io
import json
from pydantic import BaseModel, Field
from typing import Literal


class Tier(BaseModel):
    exchange: Literal['wallex', 'nobitex']
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
    rows = json.loads(text) if format == 'json' else list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
    tiers = [Tier.model_validate(row) for row in rows]
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

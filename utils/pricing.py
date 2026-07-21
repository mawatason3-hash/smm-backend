from decimal import Decimal, ROUND_HALF_UP
from typing import Union

Numeric = Union[Decimal, float, int, str]
MARKUP_RATIO = Decimal("1.4")
QUANTIZE_STEP = Decimal("0.0001")


def as_decimal(value: Numeric) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def markup_price(cost_per_1k: Numeric, markup_ratio: Decimal = MARKUP_RATIO) -> Decimal:
    return as_decimal(cost_per_1k) * markup_ratio


def calculate_charge(rate_per_1k: Numeric, quantity: int) -> Decimal:
    charge = as_decimal(rate_per_1k) * as_decimal(quantity) / Decimal("1000")
    return charge.quantize(QUANTIZE_STEP, rounding=ROUND_HALF_UP)


def calculate_provider_cost(cost_per_1k: Numeric, quantity: int) -> Decimal:
    cost = as_decimal(cost_per_1k) * as_decimal(quantity) / Decimal("1000")
    return cost.quantize(QUANTIZE_STEP, rounding=ROUND_HALF_UP)

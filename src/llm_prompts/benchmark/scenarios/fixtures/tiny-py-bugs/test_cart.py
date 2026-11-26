import pytest
from cart import cart_total, discount, line_total, parse_price, receipt


@pytest.mark.parametrize(
    "text, cents", [("$5", 500), ("$0.99", 99), ("$19.99", 1999), ("$1,299.50", 129950)]
)
def test_parse_price_returns_whole_cents(text: str, cents: int) -> None:
    assert parse_price(text) == cents


def test_line_total_multiplies_by_quantity() -> None:
    assert line_total(250, 3) == 750


@pytest.mark.parametrize(
    "total, percent, cents", [(1000, 10, 900), (995, 10, 895), (1999, 15, 1699)]
)
def test_discount_rounds_down_to_a_whole_cent(
    total: int, percent: int, cents: int
) -> None:
    assert discount(total, percent) == cents


def test_cart_total_adds_each_line_then_discounts() -> None:
    assert cart_total([("$1,299.50", 2), ("$0.99", 3)], percent=10) == 234_177


def test_receipt_lists_each_line_then_the_total() -> None:
    lines = [("$19.99", 2), ("$5", 1)]
    assert receipt(lines) == "$19.99 x 2\n$5 x 1\ntotal $44.98"

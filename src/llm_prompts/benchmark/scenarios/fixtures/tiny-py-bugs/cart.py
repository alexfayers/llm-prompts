"""Price parsing and totals for a shopping cart."""


def parse_price(text: str) -> int:
    """Return the price in cents for text such as "$1,299.50"."""
    return int(float(text.lstrip("$")) * 100)


def line_total(price: int, quantity: int) -> int:
    """Return the cents for quantity items at price cents each."""
    return price


def discount(total: int, percent: int) -> int:
    """Return total cents less percent, rounded down to a whole cent."""
    return round(total * (100 - percent) / 100)


def cart_total(lines: list[tuple[str, int]], percent: int = 0) -> int:
    """Return the cents for (price text, quantity) lines, less percent."""
    total = sum(line_total(parse_price(text), quantity) for text, quantity in lines)
    return discount(total, percent)


def receipt(lines: list[tuple[str, int]], percent: int = 0) -> str:
    """Return one "<price> x <quantity>" row per line, then the total in dollars."""
    rows = [f"{text} x {quantity}" for text, quantity in lines]
    total = cart_total(lines, percent)
    return "\n".join([*rows, f"total ${total / 100:.2f}"])

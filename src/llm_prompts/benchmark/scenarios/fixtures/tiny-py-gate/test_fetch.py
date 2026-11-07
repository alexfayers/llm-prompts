import pytest

from errors import DemoError
from fetch import fetch


def test_fetch_returns_body() -> None:
    assert fetch("http://x") == "body of http://x"


def test_fetch_rejects_an_empty_url() -> None:
    with pytest.raises(DemoError):
        fetch("")

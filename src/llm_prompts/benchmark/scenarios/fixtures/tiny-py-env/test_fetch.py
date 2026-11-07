from fetch import fetch


def test_fetch_returns_body() -> None:
    assert fetch("http://x") == "body of http://x"

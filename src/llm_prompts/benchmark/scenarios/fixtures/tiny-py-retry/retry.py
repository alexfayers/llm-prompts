import time
from collections.abc import Callable


def with_retry(call: Callable[[], str], attempts: int = 3) -> str:
    """Call `call` until it works, at most `attempts` times."""
    for attempt in range(attempts):
        try:
            return call()
        except TimeoutError:
            time.sleep(2**attempt)
    return call()

"""Build `Trace` values for tests."""

from functools import partial

from llm_prompts.benchmark.types import Trace

make_trace = partial(Trace, model="m")

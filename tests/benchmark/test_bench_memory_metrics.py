import pytest

from benchmark.traces import make_trace
from llm_prompts.benchmark.cell.memory import metrics
from llm_prompts.benchmark.types import MemoryEntity, ToolCall, Trace


def trace_calling(*names: str) -> Trace:
    return make_trace(
        tool_calls=tuple(ToolCall(name=name, args={}, ok=True) for name in names)
    )


def entity(
    name: str = "knowledge/a",
    entity_type: str = "knowledge",
    observations: tuple[str, ...] = ("o1",),
    relations: tuple[tuple[str, str], ...] = (),
) -> MemoryEntity:
    return MemoryEntity(
        name=name,
        entity_type=entity_type,
        observations=observations,
        relations=relations,
    )


def test_memory_calls_counts_only_memory_prefixed_calls() -> None:
    trace = trace_calling(
        "memory.search_nodes", "Bash", "memory.read_graph", "Bash", "Bash"
    )

    assert metrics(trace, (), ()).memory_calls == 2


@pytest.mark.parametrize(
    ("calls", "expected"),
    [
        (("memory.search_nodes", "Edit"), True),
        (("Bash", "memory.search_nodes"), True),
        (("Write", "memory.search_nodes"), False),
    ],
)
def test_read_before_first_edit(calls: tuple[str, ...], expected: bool) -> None:
    assert metrics(trace_calling(*calls), (), ()).read_before_first_edit is expected


def test_new_entity_counts_as_entity_and_its_observations() -> None:
    new = entity(name="knowledge/b", observations=("x", "y"))

    result = metrics(trace_calling(), (entity(),), (entity(), new))

    assert result.entities_added == 1
    assert result.observations_added == 2


def test_extra_observation_on_existing_entity_counts_once() -> None:
    result = metrics(
        trace_calling(),
        (entity(observations=("o1",)),),
        (entity(observations=("o1", "o2")),),
    )

    assert result.observations_added == 1
    assert result.entities_added == 0


def test_extra_relation_on_seeded_entity_counts_only_relation() -> None:
    result = metrics(
        trace_calling(),
        (entity(),),
        (entity(relations=(("knowledge/other", "relates_to"),)),),
    )

    assert result.relations_added == 1
    assert result.entities_added == 0
    assert result.observations_added == 0


def test_added_entity_without_type_prefix_is_invalid_name() -> None:
    result = metrics(
        trace_calling(), (), (entity(name="my-note", entity_type="knowledge"),)
    )

    assert result.invalid_names == 1

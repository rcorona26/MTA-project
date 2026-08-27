from mta_delay.constants import (
    CANONICAL_LINES,
    LINE_ALIASES,
    PLANNED_STATUS_TOKENS,
    SIGNIFICANT_STATUS_TOKENS,
)


def test_target_policy_is_explicit_and_disjoint() -> None:
    assert SIGNIFICANT_STATUS_TOKENS == {
        "delays",
        "severe-delays",
        "part-suspended",
        "suspended",
    }
    assert SIGNIFICANT_STATUS_TOKENS.isdisjoint(PLANNED_STATUS_TOKENS)


def test_line_aliases_resolve_to_canonical_lines() -> None:
    assert set(LINE_ALIASES.values()).issubset(CANONICAL_LINES)
    assert "SI" not in CANONICAL_LINES
    assert LINE_ALIASES["5X"] == "5"

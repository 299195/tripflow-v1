from collections.abc import Mapping
from enum import StrEnum
from typing import TypeVar

from .errors import InvalidStateTransition

S = TypeVar("S", bound=StrEnum)


def transition(current: S, target: S, allowed: Mapping[S, frozenset[S]]) -> S:
    """Apply one explicit transition, rejecting every unspecified edge."""
    if target not in allowed.get(current, frozenset()):
        raise InvalidStateTransition(f"cannot transition from {current.value} to {target.value}")
    return target

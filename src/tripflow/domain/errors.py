class ValidationError(ValueError):
    """Raised when an entity violates a domain invariant."""


class InvalidStateTransition(ValidationError):
    """Raised when an explicit state-machine transition is not allowed."""

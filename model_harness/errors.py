class HarnessError(RuntimeError):
    """Base error for expected Harness failures."""


class ContractError(ValueError):
    """Raised when a task contract is incomplete or internally inconsistent."""


class PluginError(HarnessError):
    """Raised when a plugin cannot be registered or resolved."""


class RunCancelled(HarnessError):
    """Raised when a run reaches a safe cancellation boundary."""

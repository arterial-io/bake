class BakeError(Exception):
    """A bake error."""

class RequiredParameterError(BakeError):
    """Raised when a required parameter was not specified for a task."""

class TaskFailed(BakeError):
    """Raised when a task fails."""

class TaskError(BakeError):
    """Raised when an error occurs within a task."""

class MultipleTasksError(TaskError):
    """Raised when multiple task with the same name exist."""

class UnknownTaskError(TaskError):
    """Raised when an unknown task is requested."""

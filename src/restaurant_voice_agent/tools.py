import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from pydantic import create_model


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the tool's arguments, provider-neutral
    handler: Callable[..., Any]  # may return any JSON-friendly type, not just str

    def to_schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def invoke(self, **kwargs: Any) -> str:
        result = self.handler(**kwargs)
        return result if isinstance(result, str) else json.dumps(result, default=str)


TOOLS: dict[str, Tool] = {}


def tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """Register a plain function as a Tool, deriving its schema from type hints."""
    signature = inspect.signature(func)
    fields: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, default)

    parameters = create_model(func.__name__, **fields).model_json_schema()
    description = inspect.getdoc(func) or ""

    TOOLS[func.__name__] = Tool(
        name=func.__name__,
        description=description,
        parameters=parameters,
        handler=func,
    )
    return func


@tool
def get_current_time() -> str:
    """Get the current date and time, as an ISO 8601 string in UTC."""
    return datetime.now(UTC).isoformat()

@tool
def get_opening_hours() -> dict[str, tuple[time, time]]:
    """Get the hours that the establishment is opened, for every day of the week."""
    return {
        day: (time(8), time(17))
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]
    }


@tool
def is_open_now() -> dict[str, Any]:
    """Check whether the establishment is open right now, using the current local date and time."""
    now = datetime.now()
    hours = get_opening_hours().get(now.strftime("%A").lower())

    if hours is None:
        return {"open": False}

    opens_at, closes_at = hours
    return {"open": opens_at <= now.time() < closes_at, "opens_at": str(opens_at), "closes_at": str(closes_at)}

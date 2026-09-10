from __future__ import annotations

from medflow_shared.events import EventType
from medflow_shared.registry import Registry


class ModelRouter:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def select(self, event_type: EventType) -> list[str]:
        policy = self.registry.routing.get(event_type.value)
        if policy is None:
            return []
        names = []
        for name in policy.models:
            meta = self.registry.models.get(name)
            if meta and meta.enabled:
                names.append(name)
        return names

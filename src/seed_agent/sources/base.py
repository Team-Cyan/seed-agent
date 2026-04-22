from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from seed_agent.models import IntentSource


@dataclass(frozen=True)
class SourceIntentEvent:
    source: IntentSource
    raw_text: str
    source_event_id: str | None = None
    requested_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


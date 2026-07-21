from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TenantContext:
    """Trusted tenant metadata resolved by authentication or public-token code.

    Request payloads must never construct or override this context directly.
    """

    tenant_id: UUID
    tenant_code: str
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, UUID):
            raise TypeError("tenant_id must be a UUID")
        if not self.tenant_code:
            raise ValueError("tenant_code is required")
        if not self.source:
            raise ValueError("source is required")

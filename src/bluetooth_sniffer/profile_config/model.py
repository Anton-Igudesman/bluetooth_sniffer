from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ProtocolProfile:
    # Fixed protocol identifiers loaded from profile config
    name: str
    service_uuid: str
    rx_uuid: str
    tx_uuid: str
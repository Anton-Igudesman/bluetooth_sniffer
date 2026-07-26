from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import asyncio
import json

from pathlib import Path
from typing import cast

@dataclass(frozen=True)
class AttPacket:
    frame_number: int
    timestamp: datetime
    access_address: int
    central_address: str | None
    peripheral_address: str | None
    rssi: int
    encrypted: bool
    opcode: int
    
    # Not every ATT operation targets a handle or carries application bytes
    handle: int | None
    value: bytes | None
    service_uuid: str | None
    
type JsonObject = dict[str, object]

def _required_object(data: JsonObject, key: str) -> JsonObject:
    value = data.get(key)
    
    if not isinstance(value, dict):
        raise ValueError(f"TShark packet is missing object: {key}")
    
    return value

def _required_string(data: JsonObject, key: str) -> str:
    value = data.get(key)
    
    if not isinstance(value, str):
        raise ValueError(f"TShark packet is missing string: {key}")
    
    return value

def _optional_string(data: JsonObject, key: str) -> str | None:
    value = data.get(key)
    
    if value is None:
        return None
    
    if not isinstance(value, str):
        raise ValueError(f"TShark packet field must be a string: {key}")
    
    return value

def _packet_from_tshark(document: JsonObject) -> AttPacket:
    source = _required_object(document, "_source")
    layers = _required_object(source, "layers")
    frame = _required_object(layers, "frame")
    nordic = _required_object(layers, "nordic_ble")
    btle = _required_object(layers, "btle")
    att = _required_object(layers, "btatt")
    
    flags = _required_object(nordic, "nordic_ble.flags_tree")
    
    handle_text = _optional_string(att, "btatt.handle")
    value_text = _optional_string(att, "btatt.value")
    
    handle_tree = att.get("btatt.handle_tree")
    service_uuid_text: str | None = None
    
    if isinstance(handle_tree, dict):
        service_uuid_text = _optional_string(
            handle_tree,
            "btatt.service_uuid128",
        )
        
    # Application logs and datetime us ms precision to compare
    # passive packets with matching JSON event later
    timestamp = datetime.fromtimestamp(
        float(_required_string(frame, "frame.time_epoch")),
        tz=UTC,
    )
    
    return AttPacket(
        frame_number=int(_required_string(frame, "frame.number")),
        timestamp=timestamp,
        access_address=int(
            _required_string(btle, "btle.access_address"),
            base=0,
        ),
        central_address=_optional_string(btle, "btle.central_bd_addr"),
        peripheral_address=_optional_string(
            btle,
            "btle.peripheral_bd_addr",
        ),
        rssi=int(_required_string(nordic, "nordic_ble.rssi")),
        encrypted=(
            _required_string(flags, "nordic_ble.encrypted") == "1"
        ),
        opcode=int(
            _required_string(att, "btatt.opcode"),
            base=0,
        ),
        handle=int(handle_text, base=0) if handle_text is not None else None,
        
        # Convert Wireshark hex represenation to bytes
        value=(
            bytes.fromhex(value_text.replace(":", " "))
            if value_text is not None
            else None
        ),
        service_uuid=(
            str(UUID(hex=service_uuid_text.replace(":", "")))
            if service_uuid_text is not None
            else None
        ),
    )
    
async def read_att_packets(path: Path) -> list[AttPacket]:
    if not path.is_file():
        raise FileNotFoundError(f"PCAP file was not found: {path}")
    
    # Filtering inside TShark avoids noisy analysis
    process = await asyncio.create_subprocess_exec(
        "tshark",
        "-r",
        str(path),
        "-Y",
        "btatt",
        "-T",
        "json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout,stderr = await process.communicate()
    
    if process.returncode != 0:
        error_message = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Tshark could not read {path}:"
            f" {error_message or 'unknown Tshark error'}"
        )
        
    try:
        documents: object = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Tshark returned invalid JSON for {path}"
        ) from error
        
    if not isinstance(documents, list):
        raise ValueError(f"TShark returned non-list result for {path}")
    
    packets: list[AttPacket] = []
    
    for position, document in enumerate(documents):
        if not isinstance(document, dict):
            raise ValueError(
                f"TShark result {position} is not a packet object"
            )
            
        # Records what runtime check established
        # Allows packet converter to retain dictionary type
        packet_document = cast(JsonObject, document)
        packets.append(_packet_from_tshark(packet_document))
        
    return packets
        
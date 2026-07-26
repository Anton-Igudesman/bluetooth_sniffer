from bleak.backends.device import BLEDevice

from .scanner import ScanResults

def find_devices(results: ScanResults, identifier: str) -> list[BLEDevice]:
    target = identifier.strip().casefold()
    
    if not target:
        raise ValueError("Device identifier must not be empty")
    
    matches: list[BLEDevice] = []
    
    # Match a device by current address, advertised name, or BlueZ name
    for device, advertisement in results.values():
        device_identifiers = (
            device.address,
            advertisement.local_name,
            device.name,
        )
        
    
        if any(
            device_identifier is not None 
            and device_identifier.casefold() == target # casefold works like .lower()
            for device_identifier in device_identifiers
        ):
            matches.append(device)
            
    if not matches:
        raise ValueError(
            f"No device from current scan matches '{identifier}'"
        )
            
    return matches
        
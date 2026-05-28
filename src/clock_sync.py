import struct

from common import get_gps_epoch_seconds


LORAWAN_PORT_CLOCK_SYNC = 202
CLOCK_SYNC_CMD_APP_TIME = 0x01
CLOCK_SYNC_CMD_FORCE_DEVICE_RESYNC = 0x03


def parse_app_time_req(payload: bytes) -> tuple[int, int]:
    """Parse TS003 AppTimeReq and return device GPS seconds and token."""
    if len(payload) != 6:
        raise ValueError(f"AppTimeReq must be 6 bytes, got {len(payload)}.")
    if payload[0] != CLOCK_SYNC_CMD_APP_TIME:
        raise ValueError(f"Unsupported TS003 command 0x{payload[0]:02X}.")

    device_seconds = struct.unpack("<I", payload[1:5])[0]
    token = payload[5] & 0x0F
    return device_seconds, token


def encode_app_time_ans(device_seconds: int, token: int) -> tuple[bytes, int, int]:
    """Encode TS003 AppTimeAns payload and return payload, current GPS time, correction."""
    current_gps = get_gps_epoch_seconds()
    correction = current_gps - device_seconds
    if correction < -(1 << 31) or correction > (1 << 31) - 1:
        raise ValueError("AppTimeAns time correction does not fit int32.")

    payload = (
        bytes([CLOCK_SYNC_CMD_APP_TIME])
        + correction.to_bytes(4, byteorder="little", signed=True)
        + bytes([token & 0x0F])
    )
    return payload, current_gps, correction


def encode_force_device_resync(nb_transmissions: int = 1) -> bytes:
    """Encode TS003 ForceDeviceResyncReq."""
    if nb_transmissions < 0 or nb_transmissions > 7:
        raise ValueError("nb_transmissions must be in range 0..7.")
    return bytes([CLOCK_SYNC_CMD_FORCE_DEVICE_RESYNC, nb_transmissions & 0x07])

import json
import time
import struct
import secrets
from datetime import datetime, timedelta
from Crypto.Cipher import AES
import paho.mqtt.client as mqtt
from common import logger, TerminateProcessException, sleep, compare_dictionaries_by_keys, get_gps_epoch_seconds, gps_seconds_to_datetime, current_utc_time, time_remaining_till_target_time
from config_manager import config
from clock_sync import LORAWAN_PORT_CLOCK_SYNC, encode_force_device_resync
from api_client import api_client_instance
from mqtt_client import subscribe_uplink, unsubscribe_uplink, wait_for_ack

_mc_group_json = {}

# AES-128 encryption
def _aes128_encrypt(key: bytes, data: bytes) -> bytes:
    """Encrypt data using AES-128 ECB mode."""
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(data)

# AES-128 decryption
def _aes128_decrypt(key: bytes, data: bytes) -> bytes:
    """Decrypt data using AES-128 ECB mode."""
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.decrypt(data)

# Derive McRootKey and McKEKey from GenAppKey
def _derive_mc_root_and_ke_key(GenAppKey: bytes) -> tuple:
    """
    Derive McRootKey and McKEKey from GenAppKey.
    McRootKey = aes128_encrypt(GenAppKey, 0x00 | pad16)
    McKEKey = aes128_encrypt(McRootKey, 0x00 | pad16)
    """
    zero_block = bytes([0x00] * 16)
    McRootKey = _aes128_encrypt(GenAppKey, zero_block)
    McKEKey = _aes128_encrypt(McRootKey, zero_block)
    return McRootKey, McKEKey

# Recover McKey on device side - For verification only
def _verify_mc_key_recovery_on_device(gen_app_key: bytes, mc_key_encrypted: bytes, mc_key_expected: bytes) -> bool:
    """
    Device side: derives McKEKey locally, then recovers McKey via AES encrypt:
    McKey = aes128_encrypt(McKEKey, McKey_encrypted)
    """
    logger.debug("Verifying McKey recovery on device side...")
    if len(mc_key_encrypted) != 16:
        raise ValueError(f"McKey_encrypted must be 16 bytes, got {len(mc_key_encrypted)}.")
    _, mc_ke_key = _derive_mc_root_and_ke_key(gen_app_key)
    mc_key_actual = _aes128_encrypt(mc_ke_key, mc_key_encrypted)
    return mc_key_actual == mc_key_expected

# Derive McAppSKey and McNwkSKey from McKey and McAddr
def _derive_mc_session_keys(McKey: bytes, McAddr: int) -> tuple:
    """
    Derive McAppSKey and McNwkSKey from McKey and McAddr.
    McAppSKey = aes128_encrypt(McKey, 0x01 | McAddr | pad16) 
    McNwkSKey = aes128_encrypt(McKey, 0x02 | McAddr | pad16) 
    McAddr is packed little-endian per TS005 multi-octet rule
    """
    # Build 16-byte blocks: [0x01/0x02][McAddr (LE 4B)][zeros (11B)]
    block_app = bytes([0x01]) + struct.pack("<I", McAddr) + bytes(11)
    block_nwk = bytes([0x02]) + struct.pack("<I", McAddr) + bytes(11)
    logger.debug(f"Derivation blocks: McAppSKey block={block_app.hex().upper()}, McNwkSKey block={block_nwk.hex().upper()}")
    
    mc_app_skey = _aes128_encrypt(McKey, block_app)
    mc_nwk_skey = _aes128_encrypt(McKey, block_nwk)
    
    return mc_app_skey, mc_nwk_skey


# Encode McGroupSetupReq (TS005-2.0.0 compliant)
def _encode_mc_group_setup_request(McGroupID: int, McAddr: int, McKey_encrypted: bytes, minMcFCnt: int, maxMcFCnt: int) -> bytes:
    """
    Encode McGroupSetupReq payload.
    The octet order for all multi-octet fields SHALL be little endian. 
    """
    payload = bytes.fromhex('02')                  # Command ID (1 byte) 
    payload += struct.pack("<B", McGroupID)        # McGroupID (1 byte)
    payload += struct.pack("<I", McAddr)           # McAddr (4 bytes)
    payload += McKey_encrypted                     # McKey_encrypted (16 bytes)
    payload += struct.pack("<I", minMcFCnt)        # minMcFCnt (4 bytes)
    payload += struct.pack("<I", maxMcFCnt)        # maxMcFCnt (4 bytes)
    logger.debug(f"Encoded McGroupSetupReq payload: {payload.hex().upper()}")
    return payload

# Encode McClassCSessionReq (TS005-2.0.0 compliant) 
def _encode_mc_class_c_session_request(McGroupID: int, SessionTime: int, SessionTimeOut: int, DLFreq: int, DR: int) -> bytes:
    """
    Encode McClassCSessionReq payload.
    The octet order for all multi-octet fields SHALL be little endian.
    """
    payload = bytes.fromhex('04')                                       # Command ID (1 byte)
    payload += struct.pack("<B", McGroupID)                             # McGroupID (1 byte)
    payload += struct.pack("<I", SessionTime)                           # GPS time (4 bytes)
    payload += struct.pack("<B", SessionTimeOut)                        # Timeout (1 byte)
    payload += DLFreq.to_bytes(3, byteorder="little", signed=False)     # Downlink frequency (3 bytes)
    payload += struct.pack("<B", DR)                                    # Data rate (1 byte)
    logger.debug(f"Encoded McClassCSessionReq payload: {payload.hex().upper()}")
    return payload

def _encode_mc_group_delete_request(McGroupID: int) -> bytes:
    """
    Encode McGroupDeleteReq payload.
    The octet order for all multi-octet fields SHALL be little endian.
    """
    payload = bytes.fromhex('03')                  # Command ID (1 byte)
    payload += struct.pack("<B", McGroupID)        # McGroupID (1 byte)
    logger.debug(f"Encoded McGroupDeleteReq payload: {payload.hex().upper()}")
    return payload

def _verify_mcgroup_setup_req_payload(payload: bytes) -> bool:
    """
    Device side: 
    Decode McGroupSetupReq payload into fields.
    Expected length: 30 bytes.
    Format: <B I 16s I I   (little-endian)
    """
    logger.debug("Verifying McGroupSetupReq payload recovery on device side...")
    if len(payload) != 30:
        raise ValueError(f"McGroupSetupReq must be 30 bytes, got {len(payload)}.")
    if payload[0] != 0x02:
        raise ValueError(f"Invalid Command ID in McGroupSetupReq, expected 0x02, got {payload[0]:02X}.")
    mc_group_id, mc_addr, mc_key_encrypted, min_mc_fcnt, max_mc_fcnt = struct.unpack("<B I 16s I I", payload[1:])
    decoded_payload = {
        "mc_group_id": mc_group_id,
        "mc_addr": mc_addr,                          # uint32
        "mc_key_encrypted": mc_key_encrypted,        # bytes(16)
        "min_mc_fcnt": min_mc_fcnt,                  # uint32
        "max_mc_fcnt": max_mc_fcnt,                  # uint32
    }
    logger.debug(f"Decoded McGroupSetupReq payload: {json.dumps({
        "McGroupID": mc_group_id,
        "McAddr": hex(mc_addr)[2:],
        "McKey_encrypted": mc_key_encrypted.hex().upper(),
        "MinMcFCnt": min_mc_fcnt,
        "MaxMcFCnt": max_mc_fcnt,
    })}")
    return compare_dictionaries_by_keys(decoded_payload, _mc_group_json)

def _verify_mc_class_c_session_req_payoad(payload: bytes) -> bool:
    """
    Device side: 
    Decode McClassCSessionReq payload into fields.
    Expected length: 11 bytes.
    Layout:
      [0]                 : McGroupID (1B)
      [1..4]              : SessionTime (4B LE)
      [5]                 : SessionTimeOut (1B)
      [6..8]              : DLFreq (3B LE)
      [9]                 : DR (1B)
    """
    logger.debug("Verifying McClassCSessionReq payload recovery on device side...")
    if len(payload) != 11:
        raise ValueError(f"McClassCSessionReq must be 11 bytes, got {len(payload)}.")
    if payload[0] != 0x04:
        raise ValueError(f"Invalid Command ID in McClassCSessionReq, expected 0x04, got {payload[0]:02X}.")
    mc_group_id = payload[1]
    session_time = struct.unpack("<I", payload[2:6])[0]
    session_timeout = payload[6]
    dl_freq = int.from_bytes(payload[7:10], byteorder="little", signed=False)
    dr = payload[10]

    decoded_payload = {
        "mc_group_id": mc_group_id,
        "session_time": session_time,               # uint32
        "session_timeout": session_timeout,         # uint8
        "dl_freq": dl_freq,                         # uint24 (Hz)
        "dr": dr,                                   # uint8
    }
    logger.debug(f"Decoded McClassCSessionReq payload: {json.dumps({
        "McGroupID": mc_group_id,
        "SessionTime (UTC)": gps_seconds_to_datetime(session_time).strftime('%Y-%m-%d %H:%M:%S'),
        "SessionTimeOut": str(timedelta(seconds=2**session_timeout)),
        "DLFreq": dl_freq,
        "DR": dr,
    })}")
    return compare_dictionaries_by_keys(decoded_payload, _mc_group_json)

def _verify_mcgroup_delete_req_payload(payload: bytes) -> bool:
    """
    Device side: 
    Decode McGroupDeleteReq payload into fields.
    Expected length: 2 bytes.
    Format: <B B   (little-endian)
    """
    logger.debug("Verifying McGroupDeleteReq payload recovery on device side...")
    if len(payload) != 2:
        raise ValueError(f"McGroupDeleteReq must be 2 bytes, got {len(payload)}.")
    if payload[0] != 0x03:
        raise ValueError(f"Invalid Command ID in McGroupDeleteReq, expected 0x03, got {payload[0]:02X}.")
    mc_group_id = struct.unpack("<B", payload[1:2])[0]
    decoded_payload = {
        "mc_group_id": mc_group_id,
    }
    logger.debug(f"Decoded McGroupDeleteReq payload: {json.dumps({'McGroupID': mc_group_id})}")
    return compare_dictionaries_by_keys(decoded_payload, _mc_group_json)

# Send FlushDeviceQueueRequest to all devices
def _send_device_queue_flush_request() -> None:
    """Send McGroupSetupReq to all devices."""
    api_client = api_client_instance(config)
    for dev_eui in config['dev_eui_list_in_group']:
        api_client.flush_device_queue(dev_eui)
        config['dev_eui_multicast_status_tracker'][dev_eui] = 'Queue Flushed'
    logger.info("All devices queue flushed successfully.")

# Send McGroupSetupReq to all devices
def _send_multicast_group_setup_request(McGroupID: int, McAddr: int, McKey_encrypted: bytes, minMcFCnt: int, maxMcFCnt: int) -> bytes:
    """Send McGroupSetupReq to all devices."""
    api_client = api_client_instance(config)
    payload = _encode_mc_group_setup_request(McGroupID, McAddr, McKey_encrypted, minMcFCnt, maxMcFCnt)
    for dev_eui in config['dev_eui_list_in_group']:
        api_client.enqueue_unicast_command(dev_eui, payload, f_port=200, flush=True)
        config['dev_eui_multicast_status_tracker'][dev_eui] = 'McGroupSetupReq Sent'
    logger.info(f"Enqueued McGroupSetupReq to all devices with McGroupID={McGroupID}, McAddr={McAddr}")
    return payload

# Send McClassCSessionReq to all devices
def _send_multicast_class_c_session_request(McGroupID: int, SessionTime: int, SessionTimeOut: int, DLFreq: int, DR: int) -> bytes:
    """Send McClassCSessionReq to all devices."""
    api_client = api_client_instance(config)
    payload = _encode_mc_class_c_session_request(McGroupID, SessionTime, SessionTimeOut, DLFreq, DR)
    for dev_eui in config['dev_eui_list_setup_done']:
        api_client.enqueue_unicast_command(dev_eui, payload, f_port=200)
    logger.info(f"Enqueued McClassCSessionReq {len(config['dev_eui_list_setup_done'])} devices with SessionTime={SessionTime}, SessionTimeOut={SessionTimeOut}")
    return payload

def _send_clock_sync_force_resync_request(dev_eui_list: list[str]) -> None:
    """Ask devices to emit a TS003 AppTimeReq so this tool can answer with AppTimeAns."""
    api_client = api_client_instance(config)
    payload = encode_force_device_resync(nb_transmissions=1)
    for dev_eui in dev_eui_list:
        api_client.enqueue_unicast_command(dev_eui, payload, f_port=LORAWAN_PORT_CLOCK_SYNC)
    logger.info("Enqueued ForceDeviceResyncReq to %d devices, payload=%s", len(dev_eui_list), payload.hex().upper())

def _wait_for_clock_sync(dev_eui_list: list[str]) -> bool:
    """Wait until all target devices have an AppTimeAns queued and give it time to downlink."""
    missing = [dev_eui for dev_eui in dev_eui_list if dev_eui not in config['dev_eui_list_clock_synced']]
    if not missing:
        logger.info("All target devices already have TS003 AppTimeAns queued.")
        return True

    logger.info("Waiting for TS003 AppTimeReq uplinks from devices before McClassCSessionReq: %s", missing)
    clock_sync_ack = wait_for_ack("AppTimeAns", missing)
    missing = [dev_eui for dev_eui in dev_eui_list if dev_eui not in config['dev_eui_list_clock_synced']]
    if missing:
        logger.warning("Devices still missing TS003 AppTimeReq/AppTimeAns: %s", missing)
        logger.info("Requesting TS003 resync with ForceDeviceResyncReq.")
        _send_clock_sync_force_resync_request(missing)
        clock_sync_ack = wait_for_ack("AppTimeAns", missing)
        missing = [dev_eui for dev_eui in dev_eui_list if dev_eui not in config['dev_eui_list_clock_synced']]

    if missing:
        return False

    grace_seconds = config['clock_sync_downlink_grace_seconds']
    if grace_seconds > 0:
        logger.info(
            "Waiting %d seconds after AppTimeAns queueing so Class A devices can receive it "
            "before McClassCSessionReq.",
            grace_seconds,
        )
        sleep(seconds=grace_seconds)
    return clock_sync_ack

def _send_multicast_group_delete_request_to_devices(McGroupID: int) -> None:
    """Send McGroupDeleteReq to all devices."""
    api_client = api_client_instance(config)
    payload = _encode_mc_group_delete_request(McGroupID)
    for dev_eui in config['dev_eui_list_setup_done']:
        api_client.enqueue_unicast_command(dev_eui, payload, f_port=200)
        config['dev_eui_multicast_status_tracker'][dev_eui] = 'McGroupDeleteReq Sent'
    logger.info(f"Enqueued McGroupDeleteReq to all devices with McGroupID={McGroupID}")

def _create_multicast_group() -> str:
    """Create multicast group."""
    global _mc_group_json
    api_client = api_client_instance(config)
    multicast_group_id = api_client.create_multicast_group(
        name=str(_mc_group_json.get('name')),
        application_id=str(_mc_group_json.get('application_id')),
        mc_addr=f"{_mc_group_json.get('mc_addr'):08X}".upper(),
        mc_app_s_key=_mc_group_json.get('mc_app_s_key').hex().upper(),
        mc_nwk_s_key=_mc_group_json.get('mc_nwk_s_key').hex().upper(),
        dr=_mc_group_json.get('dr'),
        freq=_mc_group_json.get('frequency'),
        region=config['region'].upper()
    )
    return multicast_group_id

def _add_devices_to_group(multicast_group_id: str, dev_eui_list) -> None:
    """Add devices to multicast group."""
    api_client = api_client_instance(config)
    for dev_eui in dev_eui_list:
        added = api_client.add_device_to_group(multicast_group_id, dev_eui, _mc_group_json.get('application_id'))
        if added:
            config['dev_eui_list_in_group'].append(dev_eui)
            config['dev_eui_multicast_status_tracker'][dev_eui] = 'Added to McGroup'
        else:
            config['dev_eui_multicast_status_tracker'][dev_eui] = 'Invalid or Not found'

def _add_gateways_to_group(multicast_group_id: str, gateway_id_list) -> None:
    """Add gateways to multicast group."""
    api_client = api_client_instance(config)
    for gateway_id in gateway_id_list:
        added = api_client.add_gateway_to_group(multicast_group_id, gateway_id, _mc_group_json.get('tenant_id'))
        if added:
            config['gateway_id_list_in_group'].append(gateway_id)
            config['gateway_id_multicast_status_tracker'][gateway_id] = 'Added to McGroup'
        else:
            config['gateway_id_multicast_status_tracker'][gateway_id] = 'Invalid or Not found'

def _pupulate_session_parameters() -> None:
    """Populate session parameters for multicast session."""
    global _mc_group_json
    # SessionTime - Start of the Class C window and is expressed as GPS time (seconds since Jan 6, 1980)
    SessionTime = get_gps_epoch_seconds() + config['ack_uplink_timeout'] + config['rendezvous_time_offset_seconds']   # Start time is current GPS time + ack timeout + offset
    # SessionTimeOut - Exponent value indicating the maximum duration of the multicast session
    SessionTimeOut = config['session_timeout_exponent']   # The maximum duration in seconds is 2^TimeOut (Example: TimeOut=8 means 256 seconds). 
    logger.debug(f"Derived SessionTime: {SessionTime}, SessionTimeOut: {SessionTimeOut}")
    _mc_group_json['session_time'] = SessionTime
    _mc_group_json['session_timeout'] = SessionTimeOut

def _delete_multicast_group(multicast_group_id: str) -> None:
    """Delete multicast group."""
    api_client = api_client_instance(config)
    api_client.delete_multicast_group(multicast_group_id)

# Configure multicast group
def configure_multicast_group() -> dict:
    """Create and configure multicast group."""
    global _mc_group_json
    group_name = f"lorawan-multicast-configurator-group-{int(round(time.time() * 1000))}"

    # Use GenAppKey from configuration (shared with devices)
    GenAppKey = bytes.fromhex(config['gen_app_key'])

    # Step 1: Derive McRootKey and McKEKey
    _, McKEKey = _derive_mc_root_and_ke_key(GenAppKey)   # McKEKey is used to encrypt McKey
    logger.debug(f"Derived McKEKey: {McKEKey.hex().upper()}")

    # Step 2: Generate dynamic McAddr and McKey
    prefix = 0xFF000000                                  # First byte fixed as FF as identification
    McAddr = prefix | (secrets.randbits(24) & 0xFFFFFE)  # 32-bit random integer, LSB = 0 for Class C 
    McKey = secrets.token_bytes(16)                      # 16 random bytes for McKey
    logger.debug(f"Generated Actual McAddr: {McAddr}, McKey: {McKey.hex().upper()}") 

    # Step 3: Encrypt McKey for transmission
    McKey_encrypted = _aes128_decrypt(McKEKey, McKey)    # The McKey is encrypted using McKEKey before being sent to the device
    logger.debug(f"Encrypted McKey: {McKey_encrypted.hex().upper()}")

    logger.debug(f"McKey recovery verification: {'Success' if _verify_mc_key_recovery_on_device(GenAppKey, McKey_encrypted, McKey) else 'Failure'}")

    # Step 4: Derive McAppSKey and McNwkSKey
    McAppSKey, McNwkSKey = _derive_mc_session_keys(McKey, McAddr)
    logger.debug(f"Derived McAppSKey: {McAppSKey.hex().upper()}, McNwkSKey: {McNwkSKey.hex().upper()}")

    # LoRaWAN Multicast parameters
    _mc_group_json = {
        "name": group_name,
        "tenant_id": config['tenant_id'],
        "application_id": config['app_id'],
        "mc_group_id": config['McGroupID'],
        "mc_addr": McAddr,
        "mc_key_encrypted": McKey_encrypted,
        "mc_app_s_key": McAppSKey,
        "mc_nwk_s_key": McNwkSKey,
        "min_mc_fcnt": config['minMcFCnt'],
        "max_mc_fcnt": config['maxMcFCnt'],
        "dr": config['data_rate'],
        "dl_freq": config['dl_freq'],
        "frequency": config['frequency']
    }
    logger.debug(f"Configuring multicast group with: {json.dumps({
        "Name": group_name,
        "AppID": config['app_id'],
        "McGroupID": hex(config['McGroupID'])[2:].upper(),
        "McAddr": f"{McAddr:08X}".upper(),
        "McKey_encrypted": McKey_encrypted.hex().upper(),
        "McAppSKey": McAppSKey.hex().upper(),
        "McNwkSKey": McNwkSKey.hex().upper(),
        "minMcFCnt": config['minMcFCnt'],
        "maxMcFCnt": config['maxMcFCnt'],
        "DR": config['data_rate'],
        "DLFreq": config['dl_freq'],
        "Frequency": config['frequency']
    }, indent=2)}")

    # Step 5: Create multicast group in ChirpStack
    mc_id = _create_multicast_group()
    _mc_group_json = {"id": mc_id, **_mc_group_json}

    # Step 6: Add devices to multicast group
    _add_devices_to_group(mc_id, config['dev_eui_list'])
    if len(config['dev_eui_list_in_group']) > 0:
        logger.info(f"{len(config['dev_eui_list_in_group'])} devices are added to McGroup successfully. Continuing...")
    else:
        logger.warning("None of the devices are valid. Exiting...")
        raise TerminateProcessException("None of the devices are valid. Aborting multicast setup!")

    # Step 7: Add gateways to multicast group
    _add_gateways_to_group(mc_id, config['gateway_id_list'])
    if len(config['gateway_id_list_in_group']) > 0:
        logger.info(f"{len(config['gateway_id_list_in_group'])} gateways are added to McGroup successfully. Continuing...")
    else:
        logger.warning("None of the gateways are valid. Exiting...")
        raise TerminateProcessException("None of the gateways are valid. Aborting multicast setup!")
    
    return _mc_group_json


# Start multicast session
def setup_and_start_multicast_session() -> None:
    """Start multicast session by sending McGroupSetupReq and McClassCSessionReq."""
    global _mc_group_json
    # Prerequisites
    logger.info("Starting with flushing all devices queue...")
    _send_device_queue_flush_request()

    # Step 1 - send McGroupSetupReq to all devices
    logger.info("Starting queuing McGroupSetupReq to all devices...")
    payload = _send_multicast_group_setup_request(
        _mc_group_json.get('mc_group_id'), 
        _mc_group_json.get('mc_addr'), 
        _mc_group_json.get('mc_key_encrypted'), 
        _mc_group_json.get('min_mc_fcnt'), 
        _mc_group_json.get('max_mc_fcnt')
    )
    logger.debug(f"McGroupSetupReq payload verification: {'Success' if _verify_mcgroup_setup_req_payload(payload) else 'Failure'}")
    
    # Step 2 - wait for McGroupSetupAns acknowledgment
    setup_req_ack = wait_for_ack("McGroupSetupAns", config['dev_eui_list_in_group'])
    if not setup_req_ack:
        logger.warning("No devices acknowledged McGroupSetupReq. Exiting...")
        raise TerminateProcessException("No devices acknowledged McGroupSetupReq. Aborting multicast session start.")
    else:
        if len(config['dev_eui_list_setup_done']) > 0:
            logger.info(f"{len(config['dev_eui_list_setup_done'])} devices have completed McGroupSetupReq successfully. Proceeding to start multicast session...")
        else:
            logger.warning("All devices reported errors with McGroupSetupReq. Exiting...")
            raise TerminateProcessException("All devices reported errors with McGroupSetupReq. Aborting multicast session start!")

    clock_sync_done = _wait_for_clock_sync(config['dev_eui_list_setup_done'])
    if not clock_sync_done:
        logger.warning("No devices completed TS003 AppTimeAns. Exiting...")
        raise TerminateProcessException("No devices completed TS003 clock synchronization. Aborting multicast session start.")

    _pupulate_session_parameters()
    logger.info(f"Starting multicast session with: {json.dumps({
        "SessionTime (UTC)": gps_seconds_to_datetime(_mc_group_json.get('session_time')).strftime('%Y-%m-%d %H:%M:%S'),
        "SessionTimeOut": str(timedelta(seconds=2**_mc_group_json.get('session_timeout')))
    }, indent=2)}")
    
    # Step 3 - send McClassCSessionReq to all devices
    logger.info(f"Starting queuing McClassCSessionReq to devices: {config['dev_eui_list_setup_done']}")
    payload = _send_multicast_class_c_session_request(
        _mc_group_json.get('mc_group_id'), 
        _mc_group_json.get('session_time'), 
        _mc_group_json.get('session_timeout'), 
        _mc_group_json.get('dl_freq'), 
        _mc_group_json.get('dr')
    )
    logger.debug(f"McClassCSessionReq payload verification: {'Success' if _verify_mc_class_c_session_req_payoad(payload) else 'Failure'}")
    
    # Step 4 - wait for McClassCSessionAns acknowledgment
    session_req_ack = wait_for_ack("McClassCSessionAns", config['dev_eui_list_setup_done'])
    if not session_req_ack:
        logger.warning("No devices acknowledged McClassCSessionReq. Exiting...")
        raise TerminateProcessException("No devices acknowledged McClassCSessionReq. Aborting!")
    else:
        if len(config['dev_eui_list_session_started']) > 0:
            logger.info(f"{len(config['dev_eui_list_session_started'])} devices have completed McClassCSessionReq successfully.")
        else:
            logger.warning("All devices reported errors with McClassCSessionReq. Exiting...")
            raise TerminateProcessException("All devices reported errors with McClassCSessionReq. Aborting!")


# Enqueue multicast command
def enqueue_multicast_command() -> None:
    """Enqueue multicast command"""
    # Example: Enqueue dummy multicast command - TODO: replace with actual command
    multicast_group_id = _mc_group_json.get('id')
    api_client = api_client_instance(config)
    payload, fport = bytes.fromhex("002A26"), 20    # Reads Battery%
    api_client.enqueue_multicast_command(multicast_group_id, payload, fport)

# Clean up multicast group
def clean_up() -> None:
    """Clean up multicast group by sending McGroupDeleteReq and deleting group from ChirpStack."""
    multicast_group_id = _mc_group_json.get('id', None)
    if multicast_group_id is None:
        logger.info("No multicast group was created. Skipping clean up...")
        return
    logger.info("Starting multicast group clean up...")
    if len(config['dev_eui_list_setup_done']) == 0:
        logger.info("No devices had completed McGroupSetupReq. Proceeding to delete multicast group from ChirpStack...")
    else:
        wait_time = config['multicast_window_offset_seconds'] * 2
        logger.info(f"Waiting for {wait_time} seconds before sending McGroupDeleteReq to allow devices to complete multicast session...")
        target_time = current_utc_time() + timedelta(seconds=wait_time)
        while current_utc_time() < target_time:
            print(f"Time remaining till clean up: {time_remaining_till_target_time(target_time)}", end='\r')
            sleep(1)

        # Step 1 - send McGroupDeleteReq to all devices
        logger.info(f"Starting queuing McGroupDeleteReq to devices: {config['dev_eui_list_setup_done']}")
        _send_multicast_group_delete_request_to_devices(config['McGroupID'])

        # Step 2 - wait for McGroupDeleteAns acknowledgment
        delete_req_ack = wait_for_ack("McGroupDeleteAns", config['dev_eui_list_setup_done'])
        if not delete_req_ack:
            logger.warning("No devices acknowledged McGroupDeleteReq. Continuing...")
        else:
            if len(config['dev_eui_list_delete_done']) > 0:
                if len(config['dev_eui_list_delete_done']) == len(config['dev_eui_list_setup_done']):
                    logger.info("All devices have completed McGroupDeleteReq successfully.")
                else:
                    logger.warning(f"{len(config['dev_eui_list_delete_done'])} devices have completed McGroupDeleteReq successfully, but some reported errors or not acknowledged.")
            else:
                logger.warning("All devices reported errors with McGroupDeleteReq. Continuing...")
    
    # Step 3 - delete multicast group from ChirpStack
    _delete_multicast_group(multicast_group_id)
    logger.debug(f"Decommissioned multicast group {multicast_group_id} successfully.")

# For Testing only
if __name__ == "__main__":
    _verify_mcgroup_setup_req_payload(bytes.fromhex("0200ffffffffffffffffffffffffffffffffffffffffffffffffffffffff"))
    _verify_mc_class_c_session_req_payoad(bytes.fromhex("0400a01f6c560ed2ad8404"))

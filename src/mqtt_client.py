import ssl
import json
import socks
import paho.mqtt.client as mqtt
from datetime import timedelta
from config_manager import config
from common import logger, TerminateProcessException, sleep, current_utc_time, time_remaining_till_target_time, base64_to_hex

_mqtt_client = None

# Acknowledgement tracker
_ack_tracker = {
    "McGroupSetupAns": set(),
    "McClassCSessionAns": set(),
    "McGroupDeleteAns": set()
}

# Parse McGroupSetupAns payload
def _parse_mc_group_setup_ans(payload_hex) -> bool:
    """Parse McGroupSetupAns payload and return True if no errors."""
    status_byte = int(payload_hex, 16)
    mc_group_id = status_byte & 0x03 # Bits 0-1
    id_error = bool(status_byte & 0x04)  # Bit 2
    logger.debug("McGroupSetupAns:")
    logger.debug(f" - McGroupID: {mc_group_id}")
    logger.debug(f" - ID Error: {'Yes' if id_error else 'No'}")
    return config['McGroupID'] == mc_group_id and not id_error

# Parse McClassCSessionAns payload
def _parse_mc_class_c_session_ans(payload_hex) -> bool:
    """Parse McClassCSessionAns payload and return True if no errors."""
    status_byte = int(payload_hex[0:2], 16)
    mc_group_id = status_byte & 0x03  # Bits 0-1
    dr_error = bool(status_byte & 0x04)  # Bit 2
    freq_error = bool(status_byte & 0x08)  # Bit 3
    mcgroup_undefined = bool(status_byte & 0x10)  # Bit 4
    start_missed = bool(status_byte & 0x20)  # Bit 5
    time_hex = payload_hex[2:]  # Remaining bytes
    time_bytes = bytes.fromhex(time_hex)
    seconds_to_start = int.from_bytes(time_bytes, byteorder='little')
    logger.debug("McClassCSessionAns:")
    logger.debug(f" - McGroupID: {mc_group_id}")
    logger.debug(f" - DR Error: {'Yes' if dr_error else 'No'}")
    logger.debug(f" - Frequency Error: {'Yes' if freq_error else 'No'}")
    logger.debug(f" - McGroup Undefined: {'Yes' if mcgroup_undefined else 'No'}")
    logger.debug(f" - Start Missed: {'Yes' if start_missed else 'No'}")
    logger.debug(f" - TimeToStart (in Seconds): {seconds_to_start}")
    if seconds_to_start == 0xFFFFFF:
        # TimeToStart SHALL be set to 0xFFFFFF by the end-device. 
        # This will inform the Application Server that the end-device clock is out of synchronization. 
        logger.warning("The end-device clock is out of synchronization")
    else:
        start_time = current_utc_time() + timedelta(seconds=seconds_to_start)
        logger.info(f"Session Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    return config['McGroupID'] == mc_group_id and not any([dr_error, freq_error, mcgroup_undefined, start_missed]) and seconds_to_start != 0xFFFFFF

def _parse_mc_group_delete_ans(payload_hex) -> bool:
    """Parse McGroupDeleteAns payload and return True if no errors."""
    status_byte = int(payload_hex, 16)
    mc_group_id = status_byte & 0x03 # Bits 0-1
    id_error = bool(status_byte & 0x04)  # Bit 2
    logger.debug("McGroupDeleteAns:")
    logger.debug(f" - McGroupID: {mc_group_id}")
    logger.debug(f" - ID Error: {'Yes' if id_error else 'No'}")
    return config['McGroupID'] == mc_group_id and not id_error

# Proxy configuration
def _configure_proxy(client: mqtt.Client) -> None:
    """Configure HTTP CONNECT or SOCKS5 proxy if requested."""
    if config['proxy_enabled']:
        # Proxy settings (choose ONE type or leave all blank to disable)
        PROXY_TYPE = config['mqtt_proxy_type']
        if not PROXY_TYPE:
            logger.info("MQTT Proxy: disabled")
            return

        if PROXY_TYPE.lower() == "http":
            ptype = socks.HTTP
        elif PROXY_TYPE.lower() == "socks5":
            ptype = socks.SOCKS5
        elif PROXY_TYPE.lower() == "socks4":
            ptype = socks.SOCKS4
        else:
            raise ValueError(f"Unsupported PROXY_TYPE: {PROXY_TYPE}")

        logger.info("MQTT Proxy: enabled %s via %s:%s", PROXY_TYPE.upper(), config['proxy_host'], config['proxy_port'])
        client.proxy_set(
            proxy_type=ptype,
            proxy_addr=config['proxy_host'],
            proxy_port=config['proxy_port'],
            proxy_username=config['proxy_username'] or None,
            proxy_password=config['proxy_password'] or None
        )
    else:
        logger.info("MQTT Proxy: disabled")

# TLS Configuration
def _configure_tls(client: mqtt.Client) -> None:
    """Set TLS parameters; optionally trust corporate inspection CA."""
    if config['mqtt_port'] == 8883:
        kwargs = dict(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLSv1_2
        )
        if config['corp_ca_cert_path']:
            logger.info(f"TLS: using corporate CA bundle at {config['corp_ca_cert_path']}")
            kwargs["ca_certs"] = config['corp_ca_cert_path']
        else:
            logger.info("TLS: using system trust store")
        client.tls_set(**kwargs) # type: ignore
        client.tls_insecure_set(False)  # keep certificate validation ON
    else:
        logger.info("TLS: disabled")

# MQTT connect callback
def _on_connect(mqtt_client, userdata, flags, reason_code, properties) -> None:
    """Handle MQTT connection events."""
    if reason_code == 0:
        # reason_code == 0 means successful connection
        logger.info(f"MQTT connection established successfully with code: {reason_code}")
        logger.info(f"Subscribing to topic: {config['mqtt_topic']}")
        mqtt_client.subscribe(config['mqtt_topic'])
    else:
        logger.error(f"MQTT connection failed with code: {reason_code}")

# MQTT disconnect callback
def _on_disconnect(mqtt_client, userdata, flags, reason_code, properties=None) -> None:
    """Handle MQTT disconnection events."""
    # reason_code == 0 means clean disconnect
    logger.warning(f"MQTT client got disconnected with code: {reason_code}")

# MQTT message callback
def _on_message(mqtt_client, userdata, msg) -> None:
    """Process incoming MQTT messages for device uplinks."""
    try:
        # data = json.loads(msg.payload.decode())
        data = json.loads(msg.payload.decode("utf-8", errors="replace"))
        logger.debug(f"MQTT message received on topic: {msg.topic} -> {data}")
        dev_eui = data.get("deviceInfo", {}).get("devEui")
        fPort = data.get("fPort")
        payload = data.get("data")
        if fPort != 200 or dev_eui is None:
            logger.info(f"Ignored message on fPort: {fPort} from device: {dev_eui}")
            return
        if dev_eui not in config['dev_eui_list']:
            logger.info(f"Ignored message from unknown device: {dev_eui}")
            return
        payload = base64_to_hex(payload)
        logger.info(f"Processing uplink message from device: {dev_eui} on fPort: {fPort}, payload: {payload}")
        if len(payload) >= 4:
            cid = payload[0:2]  # First byte is CID
            payload_hex = payload[2:]  # Remaining bytes are payload
            if cid == "02":  # McGroupSetupAns
                logger.info(f"Received McGroupSetupAns from device: {dev_eui}, payload: {payload_hex}")
                _ack_tracker["McGroupSetupAns"].add(dev_eui)
                config['dev_eui_multicast_status_tracker'][dev_eui] = 'McGroupSetupAns Received'
                if _parse_mc_group_setup_ans(payload_hex):
                    config['dev_eui_list_setup_done'].append(dev_eui)
                    config['dev_eui_multicast_status_tracker'][dev_eui] = 'McGroupSetupAns OK'
                    logger.info(f"Device {dev_eui} McGroupSetup completed successfully.")
                else:
                    config['dev_eui_multicast_status_tracker'][dev_eui] = 'McGroupSetupAns Error'
                    logger.error(f"Device {dev_eui} McGroupSetup reported errors.")
            elif cid == "03":  # McGroupDeleteAns
                logger.info(f"Received McGroupDeleteAns from device: {dev_eui}, payload: {payload_hex}")
                _ack_tracker["McGroupDeleteAns"].add(dev_eui)
                config['dev_eui_multicast_status_tracker'][dev_eui] = 'McGroupDeleteAns Received'
                if _parse_mc_group_delete_ans(payload_hex):
                    config['dev_eui_list_delete_done'].append(dev_eui)
                    config['dev_eui_multicast_status_tracker'][dev_eui] = 'McGroupDeleteAns OK'
                    logger.info(f"Device {dev_eui} McGroupDelete completed successfully.")
                else:
                    config['dev_eui_multicast_status_tracker'][dev_eui] = 'McGroupDeleteAns Error'
                    logger.error(f"Device {dev_eui} McGroupDelete reported errors.")
            elif cid == "04":  # McClassCSessionAns
                logger.info(f"Received McClassCSessionAns from device: {dev_eui}, payload: {payload_hex}")
                _ack_tracker["McClassCSessionAns"].add(dev_eui)
                config['dev_eui_multicast_status_tracker'][dev_eui] = 'McClassCSessionAns Received'
                if _parse_mc_class_c_session_ans(payload_hex):
                    config['dev_eui_list_session_started'].append(dev_eui)
                    config['dev_eui_multicast_status_tracker'][dev_eui] = 'McClassCSessionAns OK'
                    logger.info(f"Device {dev_eui} McClassCSession scheduled successfully.")
                else:
                    config['dev_eui_multicast_status_tracker'][dev_eui] = 'McClassCSessionAns Error'
                    logger.error(f"Device {dev_eui} McClassCSession reported errors.")
            else:
                logger.info(f"Ignored Command: {cid}, payload: {payload_hex} from device: {dev_eui}")
        else:
            logger.info(f"Ignored message with invalid payload length from device: {dev_eui}")
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        logger.error(f"Message topic: {msg.topic} | body: {str(msg.payload)}")

# Subscribe to required MQTT topic
def subscribe_uplink() -> None:
    """Subscribe to MQTT topic for device uplinks."""
    logger.info("Setting up MQTT client...")
    global _mqtt_client
    _mqtt_client = mqtt.Client(
        callback_api_version = mqtt.CallbackAPIVersion.VERSION2, # type: ignore
        client_id="lorawan-multicast-configurator-client",
        protocol=mqtt.MQTTv311,
        reconnect_on_failure=True  # let paho auto-retry in background
    )
    _mqtt_client.enable_logger(logger)

    # Configure proxy and TLS
    _configure_proxy(_mqtt_client)
    _configure_tls(_mqtt_client)

    if config['mqtt_username'] is not None and config['mqtt_password'] is not None:
        _mqtt_client.username_pw_set(config['mqtt_username'], config['mqtt_password'])

    _mqtt_client.on_connect = _on_connect
    _mqtt_client.on_message = _on_message
    _mqtt_client.on_subscribe = lambda client, userdata, mid, rc, props: logger.info("Subscribed to topic successfully.")
    _mqtt_client.on_disconnect = _on_disconnect
    logger.info("Connecting to MQTT broker...")
    attempt = 0
    while attempt < config['connection_retry_max_attempts']:
        try:
            _mqtt_client.connect(config['server_host'], config['mqtt_port'], 60)
            _mqtt_client.loop_start()
            break
        except Exception as e:
            attempt += 1
            logger.warning(f"Attempt {attempt} failed with error: {e}")
            if attempt < config['connection_retry_max_attempts']:
                logger.debug(f"Retrying in {config['connection_retry_delay']}s...")
                sleep(seconds=config['connection_retry_delay'])
            else:
                logger.error("Maximum retrying attempt reached. Exiting...")
                raise e
    sleep(seconds=config['connection_retry_delay']) #wait for MQTT to connect and subscribe

# Unsubscribe from MQTT topic before exiting
def unsubscribe_uplink() -> None:
    """Unsubscribe and disconnect MQTT client."""
    global _mqtt_client
    if _mqtt_client is not None:
        logger.info("Unsubscribing from topic...")
        _mqtt_client.unsubscribe(config['mqtt_topic'])
        logger.info("Disconnecting MQTT client...")
        _mqtt_client.disconnect()
        _mqtt_client.loop_stop()
        sleep(seconds=config['connection_retry_delay']) #wait for MQTT to disconnect

# Wait for acknowledgement from all devices
def wait_for_ack(command_type, dev_ids) -> bool:
    """Wait for acknowledgement uplink messages from all devices for the given command type."""
    timeout_in_secs = config['ack_uplink_timeout']
    now = current_utc_time()
    target_time = now + timedelta(seconds=timeout_in_secs)
    not_acknowledged = []
    logger.info(f"Waiting for uplink messages with timeout: {time_remaining_till_target_time(target_time)}")
    while current_utc_time() < target_time:
        not_acknowledged = [d for d in dev_ids if d not in _ack_tracker[command_type]]
        if not not_acknowledged:
            logger.info(f"All devices acknowledged with {command_type} before timeout.")
            return True
        print(f"Waiting for uplink messages from {len(not_acknowledged)} devices... Time remaining: {time_remaining_till_target_time(target_time)}", end='\r')
        sleep(seconds=1)
    logger.info(f"Timeout reached before receiving {command_type} from {not_acknowledged} devices. Continuing...")
    return len(dev_ids) > len(not_acknowledged)
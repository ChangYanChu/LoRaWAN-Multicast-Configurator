import os
import json
import math
import configparser
from typing import Final
from urllib.parse import urlparse
from common import logger, set_logger_level, ConfigReaderException


global config

#initialize global configuration dictionary
config: Final[dict] = {}

def _parse_proxy_url(proxy_url) -> dict:
    """
    Extract protocol, server, port, username, and password from a proxy URL.
    Example URL: http://username:password@proxy.example.com:8080
    """
    parsed = urlparse(proxy_url)

    protocol = parsed.scheme
    host = parsed.hostname
    port = int(parsed.port) if parsed.port else 0
    username = parsed.username
    password = parsed.password

    return {
        "proxy_protocol": protocol,
        "proxy_host": host,
        "proxy_port": port,
        "proxy_username": username,
        "proxy_password": password
    }

def _read_and_validate_config(parser, key: str, data_type: type, default: object=None, min: object=None, max: object=None) -> object:
    """Read and validate configuration value."""
    value = None
    if data_type is int:
        value = parser.getint('Configuration', key, fallback=default)
    elif data_type is bool:
        value = parser.getboolean('Configuration', key, fallback=default)
    else:
        value = parser.get('Configuration', key, fallback=default)

    if not isinstance(value, data_type):
        raise KeyError(f"{key}; expected an {data_type.__name__}")
    if data_type is int and (value < min or value > max):
        raise ValueError(f"{key}; value must be between {min} and {max}")
    if key == 'dev_eui_list':
        value = list(set([dev_eui.strip().lower() for dev_eui in value.split(',')]))
        invalid_values = [dev_eui for dev_eui in value if len(dev_eui) != 16]
        if invalid_values:
            raise ValueError(f"{key}; unsupported device-eui {invalid_values}")
    elif key == 'gateway_id_list':
        value = list(set([gw_id.strip().lower() for gw_id in value.split(',')]))
        invalid_values = [gw_id for gw_id in value if len(gw_id) != 16]
        if invalid_values:
            raise ValueError(f"{key}; unsupported gateway_id {invalid_values}")
    elif key == 'logger_level':
        allowed_levels = ['debug', 'info', 'warning', 'error', 'critical']
        if value.lower() not in allowed_levels:
            raise ValueError(f"{key}; allowed values are: {', '.join(allowed_levels)}")
        else:
            value = value.lower()
    return value

def read_config(file_path: str) -> None:
    """Read and parse configuration file."""
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"file not found: {file_path}")
        parser = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
        parser.read(file_path)
        
        #required coniguration
        config['tenant_id'] = parser.get('Configuration', 'tenant_id').lower()
        config['app_id'] = parser.get('Configuration', 'app_id').lower()
        config['server_host'] = parser.get('Configuration', 'server_host')
        config['api_url'] = parser.get('Configuration', 'api_url', fallback=f"http://{config['server_host']}:8090")
        config['mqtt_port'] = parser.getint('Configuration', 'mqtt_port')
        config['mqtt_username'] = parser.get('Configuration', 'mqtt_username', fallback=None)
        config['mqtt_password'] = parser.get('Configuration', 'mqtt_password', fallback=None)
        config['api_key'] = parser.get('Configuration', 'api_key')
        
        #The GenAppKey (Generic Application Key) is used to derive the necessary session keys (McRootKey, McKEKey) for secure communication with a multicast group
        config['gen_app_key'] = parser.get('Configuration', 'gen_app_key').lower()
        
        if not all([config['tenant_id'], config['app_id'], config['server_host'], config['api_url'], config['mqtt_port'], config['api_key'], config['gen_app_key']]):
            raise KeyError("One or more required configuration fields are missing or empty.")

        #proxy and TLS configuration
        config['proxy_enabled'] = _read_and_validate_config(parser, key='proxy_enabled', data_type=bool, default=False)
        config['proxy_url'] = _read_and_validate_config(parser, key='proxy_url', data_type=str, default='')
        config.update(_parse_proxy_url(config['proxy_url']))
        if config['proxy_enabled'] and (not config['proxy_host'] or config['proxy_port'] <= 0): 
            raise ValueError("proxy_url; standard format is http://username:password@proxy.example.com:8080") 
        config['mqtt_proxy_type'] = "http" #Default http; acceptable values are: "http" | "socks5" | "socks4" | "" (none), if none disable proxy
        config['tls_verify'] = True
        config['corp_ca_cert_path'] = _read_and_validate_config(parser, key='corp_ca_cert_path', data_type=str, default='')
        if config['corp_ca_cert_path'] and not os.path.exists(str(config['corp_ca_cert_path'])):
            raise ValueError("corp_ca_cert_path; path doesn't exist.")
        
        #optional coniguration
        config['dev_eui_list'] = _read_and_validate_config(parser, key='dev_eui_list', data_type=str, default='')
        config['gateway_id_list'] = _read_and_validate_config(parser, key='gateway_id_list', data_type=str, default='')
        config['region'] = _read_and_validate_config(parser, key='region', data_type=str, default='CN470')
        config['data_rate'] = _read_and_validate_config(parser, key='data_rate', data_type=int, min=0, max=15, default=1)
        config['frequency'] = _read_and_validate_config(parser, key='frequency', data_type=int, min=0, max=928000000, default=869525000)
        config['ack_uplink_timeout'] = _read_and_validate_config(parser, key='ack_uplink_timeout', data_type=int, default=120, min=1, max=3600) # Default to 60 seconds if not specified
        config['clock_sync_downlink_grace_seconds'] = _read_and_validate_config(parser, key='clock_sync_downlink_grace_seconds', data_type=int, default=10, min=0, max=300)
        config['session_timeout_exponent'] = _read_and_validate_config(parser, key='session_timeout_exponent', data_type=int, default=8, min=0, max=15) # Default to 256 seconds if not specified
        config['delete_mc_group_on_exit'] = _read_and_validate_config(parser, key='delete_mc_group_on_exit', data_type=bool, default=True) # Default to False if not specified
        config['dry_run'] = _read_and_validate_config(parser, key='dry_run', data_type=bool, default=False) # Default to False if not specified
        config['logger_level'] = _read_and_validate_config(parser, key='logger_level', data_type=str, default='info')  #debug, info, warning, error, critical
        set_logger_level(str(config['logger_level']))
        
        #internal
        config['mqtt_topic'] = f'application/{config['app_id']}/device/+/event/up' # Subscribe to all uplink events
        config['connection_retry_max_attempts'] = 3             # Maximum attempts to retry to establish connection to ChirpStack, default is 3
        config['connection_retry_delay'] = 5                    # In seconds
        config['terminate_process_with_message'] = None         # Placeholder for exception message
        config['McGroupID'] = 0x00                              # Integer in the range of [0:3]
        config['minMcFCnt'] = 0                                 # Minimum value of the frame counter
        config['maxMcFCnt'] = 16384                             # Maximum value of the frame counter
        config['dl_freq'] = int(config['frequency'])//100       # type: ignore # Downlink frequency in Hz/100
        config['dev_eui_list_in_group'] = []                    # Track devices which are added to McGroup
        config['dev_eui_list_setup_done'] = []                  # Track devices which have completed McGroupSetup
        config['dev_eui_list_clock_synced'] = []                 # Track devices which received TS003 AppTimeAns
        config['dev_eui_list_session_started'] = []             # Track devices which have completed McClassCSession start
        config['dev_eui_list_delete_done'] = []                 # Track devices which have completed McGroupDelete
        config['dev_eui_multicast_status_tracker'] = {}         # Track device multicast status
        config['gateway_id_list_in_group'] = []                 # Track gateways which are added to McGroup
        config['gateway_id_multicast_status_tracker'] = {}      # Track gateway multicast status
        config['rendezvous_time_offset_seconds'] = 60           # Offset time in seconds after device accepts McClassCSession to set rendezvous time
        config['multicast_window_offset_seconds'] = 15          # Offset time in seconds to add to rendezvous time to ensure device is ready and listening to multicast

        # Log the parsed configuration for debugging
        sensitive_configs = {'api_key', 'proxy_url', 'proxy_username', 'proxy_password', 'gen_app_key'}
        config_redacted = {
            key: '[REDACTED]' if key in sensitive_configs else value for key, value in config.items()
        }
        logger.info(f"Execution started with configuration: {json.dumps(config_redacted, indent=2)}")
    except Exception as e:
        raise ConfigReaderException("Invalid configuration:", e)

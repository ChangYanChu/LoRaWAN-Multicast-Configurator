# LoRaWAN Multicast Configurator

Switch your sensors into multicast, send configuration commands to all of them at once.


## Description

A lightweight tool to define, manage, and deploy LoRaWAN multicast groups and sessions to supported network servers. Designed to simplify bulk device configuration, and scheduled group broadcasts.

Why use this project:
- Author and push multicast group configuration to LoRaWAN network servers.
- Schedule and manage multicast sessions.

## Features
- Create, update, and delete multicast groups
- Validate multicast session parameters and device ranges
- Push group state to supported LoRaWAN Network Servers (e.g., ChirpStack, TS005-2.0.0 compliant)
- Schedule recurring and one-time multicast sessions

## Quick start

Prerequisites
- A supported LoRaWAN Network Server with a reachable API (ChirpStack)
- Device with LoRaWAN 1.0.4 compliant interface, supporting TS005-2.0.0 (Remote Multicast).
- Python >= 3.13
    - Install all required Python dependencies:

        ```
        pip install chirpstack-api paho-mqtt pysocks pycryptodome
        ```

## Configuration

Sample configuration [`config.ini`](config.ini)

    ```
    [Configuration]

    #Replace with your actual ChirpStack Tenant ID
    tenant_id = your-tenant-id

    #Replace with your actual ChirpStack application ID
    app_id = your-app-id

    #Replace with your ChirpStack server host address
    server_host = 127.0.0.1

    #Replace with your ChirpStack gRPC port
    grpc_port = 8080

    #Replace with your ChirpStack MQTT port
    mqtt_port = 1883

    #Replace with your ChirpStack MQTT Username (Optional)
    mqtt_username = 

    #Replace with your ChirpStack MQTT Password (Optional)
    mqtt_password = 

    #Replace with your actual ChirpStack API Key
    api_key = YOUR.API.KEY

    #Replace with your device-specific root key (GenAppKey) in HEX
    gen_app_key = 


    [DEFAULT]
    #list of devices eui (comma separated)
    dev_eui_list = device-eui-00001, device-eui-00002 

    #list of gateway id (comma separated)
    gateway_id_list = gateway-id-00001, gateway-id-00002

    #LoRaWAN data rate index for multicast transmissions; Lower DR (e.g., DR0 = SF12) gives better coverage (default is 0)
    data_rate = 0

    #LoRaWAN Frequency (in Hz); For EU868, common multicast frequency: 869525000
    freq = 869525000
    
    #Timeout for acknowledgement uplink message in seconds (default is 120)
    ack_uplink_timeout = 120

    #Session Timeout duration in seconds is 2^TimeOut (Example: TimeOut=8 means 256 seconds)
    session_timeout_exponent = 8

    #Set to false to retain multicast group on exit (default is true)
    delete_mc_group_on_exit = true

    #Set to true if network restricts outbound connection without proxy (default is false)
    proxy_enabled = false

    #Set complete proxy url e.g. http://username:password@proxy.example.com:8080 (default is blank)
    proxy_url = 

    #Set Corporate CA certificate path (absolute or relative) for TLS connection (default is blank)
    corp_ca_cert_path = 

    #Set to true to simulate the configurator without sending the request to ChirpStack (default is false)
    dry_run = false

    #logger level, possible values: debug, info, warning, error, critical (default is info)
    logger_level = info
    ```

## Usage

- Provide all required configuration settings in [`config.ini`](config.ini)
- Configure Multicast Session:
    ```
    python src\main.py --config config.ini
    ```


### Demonstration

```log
[2026-01-27 17:11:22] [INFO] Execution started with configuration: {.....}
[2026-01-27 17:11:28] [INFO] Multicast Group lorawan-multicast-configurator-group-1769514088093 created successfully with Id: XXXX
[2026-01-27 17:11:28] [INFO] Device found: DvXXXX, Application ID: XXXX
[2026-01-27 17:11:28] [INFO] Device DvXXXX added to multicast group XXXX successfully
[2026-01-27 17:11:28] [INFO] 1 devices are added to McGroup successfully. Continuing...
[2026-01-27 17:11:29] [INFO] Gateway found: GwXXXX, Tenant ID: XXXX
[2026-01-27 17:11:29] [INFO] Gateway GwXXXX added to multicast group XXXX successfully
[2026-01-27 17:11:29] [INFO] 1 gateways are added to McGroup successfully. Continuing...
[2026-01-27 17:11:29] [INFO] Starting with flushing all devices queue...
[2026-01-27 17:11:29] [INFO] Flushed device queue for dev-eui: XXXX
[2026-01-27 17:11:29] [INFO] All devices queue flushed successfully.
[2026-01-27 17:11:29] [INFO] Starting queuing McGroupSetupReq to all devices...
[2026-01-27 17:11:29] [INFO] Command enqueued for dev-eui: XXXX with Id: XXXX
[2026-01-27 17:11:29] [INFO] Enqueued McGroupSetupReq to all devices with McGroupID=0, McAddr=0000
[2026-01-27 17:11:29] [INFO] Waiting for uplink messages with timeout: 0:02:00
[2026-01-27 17:11:45] [INFO] Ignored message on fPort: 10 from device: XXXX
[2026-01-27 17:11:50] [INFO] Processing uplink message from device: XXXX on fPort: 200, payload: 0200
[2026-01-27 17:11:50] [INFO] Received McGroupSetupAns from device: XXXX, payload: 00
[2026-01-27 17:11:50] [INFO] Device XXXX McGroupSetup completed successfully.
[2026-01-27 17:11:50] [INFO] All devices acknowledged with McGroupSetupAns before timeout.
[2026-01-27 17:11:50] [INFO] 1 devices have completed McGroupSetupReq successfully. Proceeding to start multicast session...
[2026-01-27 17:11:50] [INFO] Starting multicast session with: {
  "SessionTime (UTC)": "2026-01-27 11:44:50",
  "SessionTimeOut": "0:04:16"
}
[2026-01-27 17:11:50] [INFO] Starting queuing McClassCSessionReq to devices: ['XXXX']
[2026-01-27 17:11:50] [INFO] Command enqueued for dev-eui: XXXX with Id: XXXX
[2026-01-27 17:11:50] [INFO] Enqueued McClassCSessionReq 1 devices with SessionTime=1453549508, SessionTimeOut=8
[2026-01-27 17:11:50] [INFO] Waiting for uplink messages with timeout: 0:02:00
[2026-01-27 17:12:23] [INFO] Ignored message on fPort: 10 from device: XXXX
[2026-01-27 17:12:28] [INFO] Processing uplink message from device: XXXX on fPort: 200, payload: 0400960406
[2026-01-27 17:12:28] [INFO] Received McClassCSessionAns from device: XXXX, payload: 00960406
[2026-01-27 17:12:28] [INFO] Session Start Time: 2026-02-01 01:15:38 UTC
[2026-01-27 17:12:28] [INFO] Device XXXX McClassCSession scheduled successfully.
[2026-01-27 17:12:28] [INFO] All devices acknowledged with McClassCSessionAns before timeout.
[2026-01-27 17:12:28] [INFO] 1 devices have completed McClassCSessionReq successfully.
[2026-01-27 17:12:28] [INFO] Multicast configuration and session setup completed successfully.
[2026-01-27 17:12:28] [INFO] Waiting till Rendezvous Time (+15s offset): 2026-01-27 17:15:05+05:30 (2026-01-27 11:45:05 UTC)
[2026-01-27 17:15:05] [INFO] =========== Class C session started. Ready to receive multicast commands! ===========
[2026-01-27 17:15:06] [INFO] Command enqueued for multicast group XXXX
[2026-01-27 17:15:06] [INFO] Monitor and tryout multicast commands from ChirpStack!
[2026-01-27 17:15:06] [INFO] Waiting till Class C session timeout (-15s offset): 2026-01-27 17:19:06+05:30 (2026-01-27 11:49:06 UTC)
[2026-01-27 17:19:06] [INFO] =========== Class C session timeout reached ===========
[2026-01-27 17:19:06] [INFO] Starting multicast group clean up...
[2026-01-27 17:19:06] [INFO] Waiting for 30 seconds before sending McGroupDeleteReq to allow devices to complete multicast session...
[2026-01-27 17:19:36] [INFO] Starting queuing McGroupDeleteReq to devices: ['XXXX']
[2026-01-27 17:19:36] [INFO] Command enqueued for dev-eui: XXXX with Id: XXXX
[2026-01-27 17:19:36] [INFO] Enqueued McGroupDeleteReq to all devices with McGroupID=0
[2026-01-27 17:19:36] [INFO] Waiting for uplink messages with timeout: 0:02:00
[2026-01-27 17:21:36] [INFO] All devices acknowledged McGroupDeleteReq. Continuing...
[2026-01-27 17:21:36] [INFO] Multicast Group XXXX deleted successfully
[2026-01-27 17:21:41] [INFO] Multicast status summary:
[2026-01-27 17:21:41] [INFO] Gateways:
[2026-01-27 17:21:41] [INFO]   GwXXXX: Added to McGroup
[2026-01-27 17:21:41] [INFO] Devices:
[2026-01-27 17:21:41] [INFO]   DvXXXX: McGroupDeleteReq Sent
[2026-01-27 17:21:41] [INFO] Total execution time: 0:10:19
[2026-01-27 17:21:41] [INFO] Execution stopped, Exiting...
```

## How it works (high level)

### Execution Flow
```mermaid
    graph TD
        Start([Start Execution]) --> CreateMG[Create Multicast Group]
        CreateMG --> ValDev{Validate Devices}
        
        ValDev -- "None Valid" --> Summary([Exit])
        ValDev -- "At least one" --> DiscDev[Discard Invalid Devices]
        
        DiscDev --> ValGW{Validate Gateways}
        
        ValGW -- "None Valid" --> Summary([Exit])
        ValGW -- "At least one" --> DiscGW[Discard Invalid Gateways]
        
        DiscGW --> Flush[Flush Queue for all Devices]
        
        Flush --> SendSetup["Send Multicast setup request (McGroupSetupReq) <br/> to all devices"]
        SendSetup --> WaitSetup["Wait for acknowledgement (McGroupSetupAns) <br/> till uplink timeout"]
        
        WaitSetup --> CheckSetup{All devices acknowledged <br/> or <br/> timeout is reached?}
        CheckSetup -- None acknowledged --> Summary([Exit])
        CheckSetup -- At least one --> CalcTime[Calculate SessionTime & <br/> SessionTimeout]
        
        CalcTime --> SendClassC["Send Multicast session request (McClassCSessionReq) <br/> to accepted devices"]
        SendClassC --> WaitClassC["Wait for acknowledgement (McClassCSessionAns) <br/> till uplink timeout"]
        
        WaitClassC --> CheckClassC{All devices acknowledged <br/> or <br/> timeout is reached?}
        CheckClassC -- None acknowledged --> Summary([Exit])
        CheckClassC -- At least one --> WaitBuffer[Wait till SessionTime <br/> + 15s buffer]
        
        WaitBuffer --> PromptUsr[Prompt user: session started <br/> Send Multicast commands from ChirpStack]
        PromptUsr --> WaitSession[Wait till SessionTimeout <br/> - 15s buffer]
        WaitSession --> PromptUsr2[Prompt user: session ended <br/> Stop sending Multicast commands]
        
        PromptUsr2 --> SendDel["Send Multicast delete request (McGroupDeleteReq) <br/> to all devices in Multicast group"]
        SendDel --> WaitDel["Wait for acknowledgement (McGroupDeleteAns) <br/> till uplink timeout"]
        
        WaitDel --> LogAns[Log McGroupDeleteAns <br/> from all devices]
        LogAns --> DeleteMG[Delete Multicast Group]
        DeleteMG --> Summary([Print Execution Summary])
        Summary --> Exit([Exit])
```

### Session start time (Rendezvous Time) calculation

Rendezvous Time is calculated before sending session request to devices. At this time devices will switch to class C.
```
Rendezvous Time (SessionTime) = current time + uplink timeout (ack_uplink_timeout) + 1min offset.
```

- Current time = the time when all devices have acknowledged multicast setup request (McGroupSetupReq) or uplink timeout was reached.
- Uplink timeout (ack_uplink_timeout) + 1 minute offset = maximum time given to devices to acknowledge session request

Update ack_uplink_timeout to change session start time.


## Troubleshooting
- Authentication failures: ensure LNS API token is valid and has the necessary scopes.
- Cofiguration errors: check configuration is correct.
- Monitor LoRaWAN frames in Chirpstack Gateways

## Security
- Limit API tokens and verify network server role-based access.

## License
```
MIT License
```

## Further reading
- LoRaWAN specifications and multicast session guidelines from The LoRa Alliance
- Network Server API docs for your target platform (ChirpStack)
    - https://www.chirpstack.io/docs/chirpstack/api/api.html
    - https://www.chirpstack.io/docs/chirpstack/features/multicast.html
    - https://github.com/chirpstack/chirpstack/tree/master/api/proto/api
    - https://resources.lora-alliance.org/technical-specifications/ts005-2-0-0-remote-multicast-setup



# Chirpstack

## Prerequisites
- Add application, devices and gateways in Chirpstack. 
- Set Application key and Gen App Key (should be same with 'gen_app_key' in [config.ini](config.ini)) in Chirpstack devices. 
![Set Application key and Gen App Key in Chirpstack devices](./files/chirpstack-device-otaa-keys.png)


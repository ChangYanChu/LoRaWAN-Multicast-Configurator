import grpc
from chirpstack_api import api, common
from google.protobuf.json_format import MessageToDict
from common import logger


# Singleton decorator
def singleton(cls):
    instances = {}
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    return get_instance

@singleton
class gRPC_Client:
    """gRPC client for ChirpStack Network Server."""
    def __init__(self, server_host: str, grpc_port:int, api_key: str) -> None:
        """Initialize gRPC client."""
        grpc_server_address = f"{server_host}:{grpc_port}"
        logger.debug(f"Creating gRPC client for server: {grpc_server_address}")
        # Create gRPC channel - TODO add TLS support
        self.channel = grpc.insecure_channel(grpc_server_address)
        self.metadata = [('authorization', f'Bearer {api_key}')]

        # Create ChirpStack gRPC stubs
        self.multicast_stub = api.MulticastGroupServiceStub(self.channel)
        self.device_stub = api.DeviceServiceStub(self.channel)
        self.gateway_stub = api.GatewayServiceStub(self.channel)
    
    def create_multicast_group(self, name, application_id, mc_addr, mc_app_s_key, mc_nwk_s_key, dr, freq, 
                               region = common.Region.EU868, group_type = api.MulticastGroupType.CLASS_C) -> str:
        """Create a multicast group."""
        req = api.CreateMulticastGroupRequest(
            multicast_group=api.MulticastGroup(
                name=name,
                application_id=application_id,
                region=region,
                mc_addr=mc_addr,
                mc_app_s_key=mc_app_s_key,
                mc_nwk_s_key=mc_nwk_s_key,
                group_type=group_type,
                dr=dr,
                frequency=freq
            )
        )
        logger.debug(f"CreateMulticastGroupRequest: {MessageToDict(req)}")
        resp = self.multicast_stub.Create(req, metadata=self.metadata)
        logger.info(f"Multicast Group {name} created successfully with Id: {resp.id}")
        return resp.id

    def delete_multicast_group(self, multicast_group_id: str) -> None:
        """Delete a multicast group."""
        req = api.DeleteMulticastGroupRequest(id=multicast_group_id)
        logger.debug(f"DeleteMulticastGroupRequest: {MessageToDict(req)}")
        self.multicast_stub.Delete(req, metadata=self.metadata)
        logger.info(f"Multicast Group {multicast_group_id} deleted successfully")

    def validate_device(self, dev_eui: str, app_id) -> bool:
        """Validate if device exists."""
        try:
            req = api.GetDeviceRequest(dev_eui=dev_eui)
            logger.debug(f"GetDeviceRequest: {MessageToDict(req)}")
            resp = self.device_stub.Get(req, metadata=self.metadata)
            logger.info(f"Device found: {resp.device.name}, Application ID: {resp.device.application_id}")
            if app_id == resp.device.application_id:
                return True
            else:
                logger.warning(f"Device: {dev_eui} is registered with different Application: {resp.device.application_id}, skipping...")
                return False
        except grpc.RpcError as e:
            logger.warning(f"Device not found: {dev_eui}")
            return False

    def add_device_to_group(self, multicast_group_id: str, dev_eui, app_id) -> bool:
        """Add device to multicast group."""
        if self.validate_device(dev_eui, app_id):
            req = api.AddDeviceToMulticastGroupRequest(
                multicast_group_id=multicast_group_id,
                dev_eui=dev_eui
            )
            logger.debug(f"AddDeviceToMulticastGroupRequest: {MessageToDict(req)}")
            self.multicast_stub.AddDevice(req, metadata=self.metadata)
            logger.info(f"Device {dev_eui} added to multicast group {multicast_group_id} successfully")
            return True
        else:
            return False

    def validate_gateway(self, gateway_id, tenant_id) -> bool:
        """Validate if gateway exists."""
        try:
            req = api.GetGatewayRequest(gateway_id=gateway_id)
            logger.debug(f"GetGatewayRequest: {MessageToDict(req)}")
            resp = self.gateway_stub.Get(req, metadata=self.metadata)
            logger.info(f"Gateway found: {resp.gateway.name}, Tenant ID: {resp.gateway.tenant_id}")
            if tenant_id == resp.gateway.tenant_id:
                return True
            else:
                logger.warning(f"Gateway: {gateway_id} is registered with different Tenant: {resp.gateway.tenant_id}, skipping...")
                return False
        except grpc.RpcError as e:
            logger.warning(f"Gateway not found: {gateway_id}")
            return False

    def add_gateway_to_group(self, multicast_group_id, gateway_id, tenant_id) -> bool:
        """Add gateway to multicast group."""
        if self.validate_gateway(gateway_id, tenant_id):
            req = api.AddGatewayToMulticastGroupRequest(
                multicast_group_id=multicast_group_id,
                gateway_id=gateway_id
            )
            logger.debug(f"AddGatewayToMulticastGroupRequest: {MessageToDict(req)}")
            self.multicast_stub.AddGateway(req, metadata=self.metadata)
            logger.info(f"Gateway {gateway_id} added to multicast group {multicast_group_id} successfully")
            return True
        else:
            return False

    def enqueue_multicast_command(self, multicast_group_id, frm_payload, f_port) -> None:
        """Enqueue multicast command"""
        req = api.EnqueueMulticastGroupQueueItemRequest(
            queue_item=api.MulticastGroupQueueItem(
                multicast_group_id=multicast_group_id,
                f_port=f_port,    # must be > 0
                data=frm_payload  # in bytes
            )
        )
        logger.debug(f"EnqueueMulticastGroupQueueItemRequest: {MessageToDict(req)}")
        self.multicast_stub.Enqueue(req, metadata=self.metadata)
        logger.info(f"Command enqueued for multicast group {multicast_group_id}")
    
    def enqueue_unicast_command(self, dev_eui, frm_payload, f_port, flush=False):
        """Enqueue unicast command to device."""
        req = api.EnqueueDeviceQueueItemRequest(
            queue_item=api.DeviceQueueItem(
                dev_eui=dev_eui,
                data=frm_payload,
                f_port=f_port,
                confirmed=False
            ),
            flush_queue=flush
        )
        logger.debug(f"EnqueueDeviceQueueItemRequest: {MessageToDict(req)}")
        resp = self.device_stub.Enqueue(req, metadata=self.metadata)
        logger.info(f"Command enqueued for dev-eui: {dev_eui} with Id: {resp.id}")
    
    def flush_device_queue(self, dev_eui):
        """Flush device queue."""
        req = api.FlushDeviceQueueRequest(
            dev_eui = dev_eui
        )
        logger.debug(f"FlushDeviceQueueRequest: {MessageToDict(req)}")
        self.device_stub.FlushQueue(req, metadata=self.metadata)
        logger.info(f"Flushed device queue for dev-eui: {dev_eui}")

def grpc_client_instance(config) -> gRPC_Client:
    """Get singleton gRPC client instance."""
    return gRPC_Client(config['server_host'], config['grpc_port'], config['api_key'])

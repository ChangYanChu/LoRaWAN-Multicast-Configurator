import base64
import json
import urllib.error
import urllib.request

from common import logger


def singleton(cls):
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


@singleton
class API_Client:
    """HTTP API client for ChirpStack REST API / REST gateway."""

    def __init__(self, api_url: str, api_key: str, dry_run: bool = False) -> None:
        self.api_url = api_url.rstrip("/")
        self.dry_run = dry_run
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Grpc-Metadata-Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        logger.debug("Creating ChirpStack HTTP API client for server: %s", self.api_url)

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.api_url}{path}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        logger.debug("HTTP %s %s body=%s", method, url, body)
        if self.dry_run:
            logger.info("Dry run: skipped HTTP %s %s body=%s", method, url, body)
            return {"id": "dry-run"}

        req = urllib.request.Request(url, data=data, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {method} {url} failed: {err.code} {err_body}") from err

        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def create_multicast_group(self, name, application_id, mc_addr, mc_app_s_key, mc_nwk_s_key, dr, freq, region="CN470") -> str:
        body = {
            "multicastGroup": {
                "name": name,
                "applicationId": application_id,
                "region": region,
                "mcAddr": mc_addr,
                "mcAppSKey": mc_app_s_key,
                "mcNwkSKey": mc_nwk_s_key,
                "groupType": "CLASS_C",
                "dr": dr,
                "frequency": freq,
            }
        }
        resp = self._request("POST", "/api/multicast-groups", body)
        multicast_group_id = resp["id"]
        logger.info("Multicast Group %s created successfully with Id: %s", name, multicast_group_id)
        return multicast_group_id

    def delete_multicast_group(self, multicast_group_id: str) -> None:
        self._request("DELETE", f"/api/multicast-groups/{multicast_group_id}")
        logger.info("Multicast Group %s deleted successfully", multicast_group_id)

    def validate_device(self, dev_eui: str, app_id) -> bool:
        try:
            resp = self._request("GET", f"/api/devices/{dev_eui}")
        except RuntimeError:
            logger.warning("Device not found: %s", dev_eui)
            return False

        device = resp.get("device", {})
        logger.info("Device found: %s, Application ID: %s", device.get("name"), device.get("applicationId"))
        if app_id == device.get("applicationId"):
            return True
        logger.warning("Device: %s is registered with different Application: %s, skipping...", dev_eui, device.get("applicationId"))
        return False

    def add_device_to_group(self, multicast_group_id: str, dev_eui, app_id) -> bool:
        if not self.validate_device(dev_eui, app_id):
            return False
        self._request(
            "POST",
            f"/api/multicast-groups/{multicast_group_id}/devices",
            {
                "multicastGroupId": multicast_group_id,
                "devEui": dev_eui,
            },
        )
        logger.info("Device %s added to multicast group %s successfully", dev_eui, multicast_group_id)
        return True

    def validate_gateway(self, gateway_id, tenant_id) -> bool:
        try:
            resp = self._request("GET", f"/api/gateways/{gateway_id}")
        except RuntimeError:
            logger.warning("Gateway not found: %s", gateway_id)
            return False

        gateway = resp.get("gateway", {})
        logger.info("Gateway found: %s, Tenant ID: %s", gateway.get("name"), gateway.get("tenantId"))
        if tenant_id == gateway.get("tenantId"):
            return True
        logger.warning("Gateway: %s is registered with different Tenant: %s, skipping...", gateway_id, gateway.get("tenantId"))
        return False

    def add_gateway_to_group(self, multicast_group_id, gateway_id, tenant_id) -> bool:
        if not self.validate_gateway(gateway_id, tenant_id):
            return False
        self._request(
            "POST",
            f"/api/multicast-groups/{multicast_group_id}/gateways",
            {
                "multicastGroupId": multicast_group_id,
                "gatewayId": gateway_id,
            },
        )
        logger.info("Gateway %s added to multicast group %s successfully", gateway_id, multicast_group_id)
        return True

    def enqueue_multicast_command(self, multicast_group_id, frm_payload, f_port) -> None:
        body = {
            "queueItem": {
                "multicastGroupId": multicast_group_id,
                "fPort": f_port,
                "data": base64.b64encode(frm_payload).decode("ascii"),
            }
        }
        self._request("POST", f"/api/multicast-groups/{multicast_group_id}/queue", body)
        logger.info("Command enqueued for multicast group %s", multicast_group_id)

    def enqueue_unicast_command(self, dev_eui, frm_payload, f_port, flush=False):
        body = {
            "queueItem": {
                "devEui": dev_eui,
                "confirmed": False,
                "fPort": f_port,
                "data": base64.b64encode(frm_payload).decode("ascii"),
            },
            "flushQueue": flush,
        }
        resp = self._request("POST", f"/api/devices/{dev_eui}/queue", body)
        logger.info("Command enqueued for dev-eui: %s with Id: %s", dev_eui, resp.get("id"))

    def flush_device_queue(self, dev_eui):
        self._request("DELETE", f"/api/devices/{dev_eui}/queue")
        logger.info("Flushed device queue for dev-eui: %s", dev_eui)


def api_client_instance(config) -> API_Client:
    return API_Client(config["api_url"], config["api_key"], config["dry_run"])

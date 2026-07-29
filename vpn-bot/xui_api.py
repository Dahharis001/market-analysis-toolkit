import json
import logging
import uuid
from urllib.parse import quote

import aiohttp

import config

log = logging.getLogger("xui")

DEFAULT_FLOW = "xtls-rprx-vision"


class XuiError(Exception):
    pass


class XuiClient:
    """Thin wrapper around the 3x-ui panel REST API (session-cookie auth)."""

    def __init__(self):
        self._session = None

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=config.XUI_VERIFY_SSL)
            self._session = aiohttp.ClientSession(connector=connector)
            await self._login()
        return self._session

    async def _login(self):
        url = f"{config.XUI_PANEL_URL}/login"
        async with self._session.post(
            url,
            data={"username": config.XUI_USERNAME, "password": config.XUI_PASSWORD},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as r:
            data = await r.json()
            if not data.get("success"):
                raise XuiError(f"3x-ui login failed: {data}")
        log.info("logged into 3x-ui panel")

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_inbound(self):
        session = await self._ensure_session()
        url = f"{config.XUI_PANEL_URL}/panel/api/inbounds/get/{config.XUI_INBOUND_ID}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json()
            if not data.get("success"):
                raise XuiError(f"get inbound failed: {data}")
            return data["obj"]

    async def add_client(self, email, expiry_time_ms, total_gb=0):
        """Creates a VLESS Reality client on the configured inbound. Returns (client_uuid, share_link)."""
        session = await self._ensure_session()
        inbound = await self._get_inbound()
        client_uuid = str(uuid.uuid4())

        existing_clients = json.loads(inbound["settings"]).get("clients", [])
        flow = existing_clients[0].get("flow", DEFAULT_FLOW) if existing_clients else DEFAULT_FLOW

        client_obj = {
            "id": client_uuid,
            "email": email,
            "enable": True,
            "expiryTime": expiry_time_ms,
            "totalGB": total_gb,
            "flow": flow,
            "limitIp": 0,
            "subId": uuid.uuid4().hex[:16],
        }
        body = {
            "id": config.XUI_INBOUND_ID,
            "settings": json.dumps({"clients": [client_obj]}),
        }
        url = f"{config.XUI_PANEL_URL}/panel/api/inbounds/addClient"
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json()
            if not data.get("success"):
                raise XuiError(f"addClient failed: {data}")

        link = self._build_share_link(inbound, client_uuid, flow, email)
        return client_uuid, link

    async def update_client_expiry(self, client_uuid, email, expiry_time_ms, total_gb=0):
        session = await self._ensure_session()
        inbound = await self._get_inbound()
        existing_clients = json.loads(inbound["settings"]).get("clients", [])
        flow = next((c.get("flow", DEFAULT_FLOW) for c in existing_clients if c["id"] == client_uuid), DEFAULT_FLOW)

        client_obj = {
            "id": client_uuid,
            "email": email,
            "enable": True,
            "expiryTime": expiry_time_ms,
            "totalGB": total_gb,
            "flow": flow,
            "limitIp": 0,
        }
        body = {
            "id": config.XUI_INBOUND_ID,
            "settings": json.dumps({"clients": [client_obj]}),
        }
        url = f"{config.XUI_PANEL_URL}/panel/api/inbounds/updateClient/{client_uuid}"
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json()
            if not data.get("success"):
                raise XuiError(f"updateClient failed: {data}")

        return self._build_share_link(inbound, client_uuid, flow, email)

    async def delete_client(self, client_uuid):
        session = await self._ensure_session()
        url = f"{config.XUI_PANEL_URL}/panel/api/inbounds/{config.XUI_INBOUND_ID}/delClient/{client_uuid}"
        async with session.post(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json()
            if not data.get("success"):
                log.warning("delClient failed for %s: %s", client_uuid, data)

    def _build_share_link(self, inbound, client_uuid, flow, remark):
        stream = json.loads(inbound["streamSettings"])
        reality = stream["realitySettings"]
        pbk = reality["settings"]["publicKey"]
        fp = reality["settings"].get("fingerprint", "chrome")
        sni = reality["serverNames"][0]
        sid = reality["shortIds"][0] if reality["shortIds"] else ""
        spx = reality["settings"].get("spiderX", "") or "/"

        params = (
            f"type={quote(stream.get('network', 'tcp'))}&security=reality&pbk={quote(pbk)}&fp={quote(fp)}"
            f"&sni={quote(sni)}&sid={quote(sid)}&spx={quote(spx)}&flow={quote(flow)}"
        )
        return f"vless://{client_uuid}@{config.XUI_SERVER_HOST}:{inbound['port']}?{params}#{quote(remark)}"


xui = XuiClient()

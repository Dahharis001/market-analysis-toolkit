import json
import logging
import re
from urllib.parse import quote

import aiohttp

import config

log = logging.getLogger("xui")

DEFAULT_FLOW = "xtls-rprx-vision"


class XuiError(Exception):
    pass


def _maybe_json(value):
    """3x-ui has returned settings/streamSettings as either a JSON string or a
    native object across versions — accept both."""
    return json.loads(value) if isinstance(value, str) else value


class XuiClient:
    """Thin wrapper around the 3x-ui panel REST API (session-cookie + CSRF-token auth)."""

    def __init__(self):
        self._session = None
        self._csrf_token = None

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=config.XUI_VERIFY_SSL)
            # XUI_PANEL_URL is a bare IP: aiohttp's default cookie jar silently drops
            # cookies for IP-address hosts unless the jar is marked "unsafe".
            cookie_jar = aiohttp.CookieJar(unsafe=True)
            self._session = aiohttp.ClientSession(connector=connector, cookie_jar=cookie_jar)
            await self._login()
        return self._session

    async def _get_csrf_token(self):
        """The panel embeds a token in a <meta name="csrf-token"> tag that must be echoed
        back as X-CSRF-Token on every state-changing request (login, add/update/del client)."""
        async with self._session.get(
            f"{config.XUI_PANEL_URL}/", timeout=aiohttp.ClientTimeout(total=20)
        ) as r:
            html = await r.text()
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
        if not match:
            raise XuiError("could not find csrf-token meta tag on 3x-ui login page")
        return match.group(1)

    async def _login(self):
        self._csrf_token = await self._get_csrf_token()
        url = f"{config.XUI_PANEL_URL}/login"
        async with self._session.post(
            url,
            json={"username": config.XUI_USERNAME, "password": config.XUI_PASSWORD},
            headers={"X-CSRF-Token": self._csrf_token},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as r:
            data = await r.json()
            if not data.get("success"):
                raise XuiError(f"3x-ui login failed: {data}")
        log.info("logged into 3x-ui panel")

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _post(self, path, json_body=None):
        session = await self._ensure_session()
        url = f"{config.XUI_PANEL_URL}{path}"
        headers = {"X-CSRF-Token": self._csrf_token}
        async with session.post(url, json=json_body, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json()
            if not data.get("success"):
                raise XuiError(f"POST {path} failed: {data}")
            return data.get("obj")

    async def _get(self, path):
        session = await self._ensure_session()
        url = f"{config.XUI_PANEL_URL}{path}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json()
            if not data.get("success"):
                raise XuiError(f"GET {path} failed: {data}")
            return data.get("obj")

    async def _get_inbound(self):
        for inbound in await self._get("/panel/api/inbounds/list"):
            if inbound["id"] == config.XUI_INBOUND_ID:
                return inbound
        raise XuiError(f"inbound id {config.XUI_INBOUND_ID} not found in inbounds list")

    async def _get_client(self, email):
        return (await self._get(f"/panel/api/clients/get/{email}"))["client"]

    async def add_client(self, email, expiry_time_ms, total_gb=0):
        """Creates a VLESS Reality client attached to the configured inbound. Returns (link, uuid)."""
        body = {
            "client": {
                "email": email,
                "totalGB": total_gb,
                "expiryTime": expiry_time_ms,
                "tgId": 0,
                "limitIp": 0,
                "enable": True,
                "flow": DEFAULT_FLOW,
            },
            "inboundIds": [config.XUI_INBOUND_ID],
        }
        await self._post("/panel/api/clients/add", body)
        client = await self._get_client(email)
        link = await self._build_share_link(client, email)
        return link, client["uuid"]

    async def update_client_expiry(self, email, expiry_time_ms, total_gb=0):
        """Returns (link, uuid)."""
        client = await self._get_client(email)
        body = {
            "email": email,
            "totalGB": total_gb or client["totalGB"],
            "expiryTime": expiry_time_ms,
            "tgId": client.get("tgId", 0),
            "limitIp": client.get("limitIp", 0),
            "enable": True,
            "flow": client.get("flow") or DEFAULT_FLOW,
        }
        await self._post(f"/panel/api/clients/update/{email}", body)
        client["expiryTime"] = expiry_time_ms
        link = await self._build_share_link(client, email)
        return link, client["uuid"]

    async def delete_client(self, email):
        try:
            await self._post(f"/panel/api/clients/del/{email}?keepTraffic=0")
        except XuiError:
            log.warning("delete_client failed for %s", email, exc_info=True)

    def _reality_params(self, inbound):
        stream = _maybe_json(inbound["streamSettings"])
        reality = stream["realitySettings"]
        return {
            "port": inbound["port"],
            "network": stream.get("network", "tcp"),
            "pbk": reality["settings"]["publicKey"],
            "fp": reality["settings"].get("fingerprint", "chrome"),
            "sni": reality["serverNames"][0],
            "sid": reality["shortIds"][0] if reality["shortIds"] else "",
            "spx": reality["settings"].get("spiderX", "") or "/",
        }

    async def _build_share_link(self, client, remark):
        inbound = await self._get_inbound()
        p = self._reality_params(inbound)
        flow = client.get("flow") or DEFAULT_FLOW
        params = (
            f"encryption=none&type={quote(p['network'])}&security=reality&pbk={quote(p['pbk'])}&fp={quote(p['fp'])}"
            f"&sni={quote(p['sni'])}&sid={quote(p['sid'])}&spx={quote(p['spx'])}&flow={quote(flow)}"
        )
        return f"vless://{client['uuid']}@{config.XUI_SERVER_HOST}:{p['port']}?{params}#{quote(remark)}"

    async def get_reality_info(self):
        """Raw reality params for the inbound, used to build sing-box subscription profiles."""
        inbound = await self._get_inbound()
        info = self._reality_params(inbound)
        info["flow"] = DEFAULT_FLOW
        info["host"] = config.XUI_SERVER_HOST
        return info


xui = XuiClient()

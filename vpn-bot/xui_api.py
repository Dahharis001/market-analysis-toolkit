import asyncio
import json
import logging
import re
from urllib.parse import quote

import aiohttp

import config

log = logging.getLogger("xui")

DEFAULT_FLOW = "xtls-rprx-vision"

# A stale session gets the HTML login page (or a "please log in" message) back instead of
# the expected JSON — both mean "re-authenticate", not "the request was invalid".
_AUTH_ERROR_RE = re.compile(r"login|log\s*in|unauthor|session", re.IGNORECASE)


class XuiError(Exception):
    pass


def _maybe_json(value):
    """3x-ui has returned settings/streamSettings as either a JSON string or a
    native object across versions — accept both."""
    return json.loads(value) if isinstance(value, str) else value


def _try_json(body):
    """None when the panel answered with something that is not JSON (i.e. the login page)."""
    try:
        return json.loads(body)
    except ValueError:
        return None


def _flow_for(network, client_flow=None):
    """xtls-rprx-vision is only defined for a raw/tcp stream; on ws/grpc/http the
    Android and desktop clients refuse a link that carries it."""
    if network not in ("tcp", "raw"):
        return ""
    return client_flow or DEFAULT_FLOW


class XuiClient:
    """Thin wrapper around one 3x-ui panel's REST API (session-cookie + CSRF-token auth)."""

    def __init__(self, region):
        panel = config.PANELS[region]
        self.region = region
        self.label = panel["label"]
        self.base_url = panel["url"]
        self.username = panel["username"]
        self.password = panel["password"]
        self.inbound_id = panel["inbound_id"]
        self.server_host = panel["host"]
        self._session = None
        self._csrf_token = None
        self._auth_lock = asyncio.Lock()

    async def _ensure_session(self):
        async with self._auth_lock:
            if self._session is None or self._session.closed:
                connector = aiohttp.TCPConnector(ssl=config.XUI_VERIFY_SSL)
                # Panels are addressed by bare IP: aiohttp's default cookie jar silently
                # drops cookies for IP-address hosts unless the jar is marked "unsafe".
                cookie_jar = aiohttp.CookieJar(unsafe=True)
                self._session = aiohttp.ClientSession(connector=connector, cookie_jar=cookie_jar)
                self._csrf_token = None
            # No token means we have never logged in, or the last call found the session
            # stale and dropped it — either way, authenticate before using the session.
            if self._csrf_token is None:
                await self._login()
            return self._session

    def _drop_auth(self):
        """Forget the cookie and CSRF token so the next call logs in again."""
        self._csrf_token = None
        if self._session and not self._session.closed:
            self._session.cookie_jar.clear()

    async def _get_csrf_token(self):
        """The panel embeds a token in a <meta name="csrf-token"> tag that must be echoed
        back as X-CSRF-Token on every state-changing request (login, add/update/del client)."""
        async with self._session.get(
            f"{self.base_url}/", timeout=aiohttp.ClientTimeout(total=20)
        ) as r:
            html = await r.text()
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
        if not match:
            raise XuiError("could not find csrf-token meta tag on 3x-ui login page")
        return match.group(1)

    async def _login(self):
        self._csrf_token = await self._get_csrf_token()
        url = f"{self.base_url}/login"
        async with self._session.post(
            url,
            json={"username": self.username, "password": self.password},
            headers={"X-CSRF-Token": self._csrf_token},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as r:
            data = await r.json()
            if not data.get("success"):
                raise XuiError(f"3x-ui login failed: {data}")
        log.info("logged into 3x-ui panel [%s]", self.region)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, method, path, json_body=None):
        """One panel call, re-authenticating once if the session turned out to be stale.

        3x-ui drops every session when it restarts (so: after a server reboot) and expires
        them on its own schedule besides. Without this retry the bot keeps posting a dead
        cookie and every client add/update fails until the bot process itself is restarted —
        which looks from the outside like "the bot stopped issuing configs entirely".
        """
        for attempt in (1, 2):
            session = await self._ensure_session()
            async with session.request(
                method,
                f"{self.base_url}{path}",
                json=json_body,
                headers={"X-CSRF-Token": self._csrf_token},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                status = r.status
                body = await r.text()

            data = _try_json(body)
            stale = data is None or status in (401, 403) or (
                not data.get("success") and _AUTH_ERROR_RE.search(data.get("msg") or "")
            )
            if stale and attempt == 1:
                log.info("3x-ui session stale on %s %s, re-authenticating [%s]", method, path, self.region)
                self._drop_auth()
                continue
            if data is None:
                raise XuiError(
                    f"{method} {path}: panel answered with non-JSON (status {status}); "
                    f"check XUI_PANEL_URL — a wrong webBasePath returns the login page"
                )
            if not data.get("success"):
                raise XuiError(f"{method} {path} failed: {data}")
            return data.get("obj")

    async def _post(self, path, json_body=None):
        return await self._request("POST", path, json_body)

    async def _get(self, path):
        return await self._request("GET", path)

    async def _get_inbound(self):
        for inbound in await self._get("/panel/api/inbounds/list"):
            if inbound["id"] == self.inbound_id:
                return inbound
        raise XuiError(f"inbound id {self.inbound_id} not found in inbounds list")

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
            "inboundIds": [self.inbound_id],
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

    async def share_link(self, email):
        """Rebuilds the link for an existing client without modifying it, so a user whose
        message got lost can ask for the same connection details again."""
        client = await self._get_client(email)
        return await self._build_share_link(client, email)

    async def delete_client(self, email):
        try:
            await self._post(f"/panel/api/clients/del/{email}?keepTraffic=0")
        except XuiError:
            log.warning("delete_client failed for %s", email, exc_info=True)

    def _reality_params(self, inbound):
        stream = _maybe_json(inbound["streamSettings"])
        reality = stream["realitySettings"]
        settings = reality.get("settings") or {}
        short_ids = reality.get("shortIds") or []
        server_names = reality.get("serverNames") or []
        return {
            "port": inbound["port"],
            "network": stream.get("network") or "tcp",
            "pbk": settings.get("publicKey") or "",
            # The panel stores "" (not a missing key) when a field is left blank, so a
            # .get() default never fires. An empty fp is handed straight to uTLS by
            # v2rayNG and v2rayN and kills the handshake, while the iOS clients quietly
            # substitute a default — which is exactly why a link can work on an iPhone
            # and fail on Android and desktop.
            "fp": settings.get("fingerprint") or "chrome",
            "sni": server_names[0] if server_names else "",
            "sid": short_ids[0] if short_ids else "",
            "spx": settings.get("spiderX") or "/",
        }

    async def _build_share_link(self, client, remark):
        inbound = await self._get_inbound()
        p = self._reality_params(inbound)
        params = {
            "encryption": "none",
            "type": p["network"],
            "security": "reality",
            "pbk": p["pbk"],
            "fp": p["fp"],
            "sni": p["sni"],
            "sid": p["sid"],
            "spx": p["spx"],
            "flow": _flow_for(p["network"], client.get("flow")),
        }
        # An empty value is worse than an absent key: strict clients reject "sid=" outright
        # instead of treating it as unset.
        query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items() if v)
        return f"vless://{client['uuid']}@{self.server_host}:{p['port']}?{query}#{quote(remark)}"

    async def get_reality_info(self):
        """Raw reality params for the inbound, used to build sing-box subscription profiles."""
        inbound = await self._get_inbound()
        info = self._reality_params(inbound)
        info["flow"] = _flow_for(info["network"])
        info["host"] = self.server_host
        return info


CLIENTS = {region: XuiClient(region) for region in config.PANELS}


def for_region(region):
    """Panel client for the region the user picked, falling back to the default one."""
    return CLIENTS.get(region) or CLIENTS[config.DEFAULT_REGION]


async def close_all():
    for client in CLIENTS.values():
        await client.close()


# default panel, kept so single-region call sites keep working
xui = CLIENTS[config.DEFAULT_REGION]

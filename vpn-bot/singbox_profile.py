RU_GEOIP_URL = "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/sing/geo/geoip/ru.srs"
RU_GEOSITE_URL = "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/sing/geo/geosite/category-ru.srs"

PROXY_TAG = "secure-proxy"


def build_config(reality_info, client_uuid, remark="access"):
    """Sing-box subscription profile: VLESS Reality proxy + bypass for Russian sites/IPs."""
    proxy = {
        "type": "vless",
        "tag": PROXY_TAG,
        "server": reality_info["host"],
        "server_port": reality_info["port"],
        "uuid": client_uuid,
        "packet_encoding": "xudp",
        "tls": {
            "enabled": True,
            "server_name": reality_info["sni"],
            "utls": {"enabled": True, "fingerprint": reality_info["fp"] or "chrome"},
            "reality": {
                "enabled": True,
                "public_key": reality_info["pbk"],
                "short_id": reality_info["sid"],
            },
        },
    }
    # sing-box rejects an empty flow string, so the key is only present when it applies.
    if reality_info.get("flow"):
        proxy["flow"] = reality_info["flow"]

    return {
        "dns": {
            "servers": [
                {"tag": "dns-remote", "address": "https://1.1.1.1/dns-query", "detour": PROXY_TAG},
                {"tag": "dns-direct", "address": "77.88.8.8", "detour": "direct"},
            ],
            "rules": [{"rule_set": ["geosite-category-ru"], "server": "dns-direct"}],
            "final": "dns-remote",
        },
        "outbounds": [
            proxy,
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "rule_set": [
                {
                    "tag": "geoip-ru",
                    "type": "remote",
                    "format": "binary",
                    "url": RU_GEOIP_URL,
                    "download_detour": PROXY_TAG,
                },
                {
                    "tag": "geosite-category-ru",
                    "type": "remote",
                    "format": "binary",
                    "url": RU_GEOSITE_URL,
                    "download_detour": PROXY_TAG,
                },
            ],
            "rules": [
                {"rule_set": ["geosite-category-ru", "geoip-ru"], "outbound": "direct"},
            ],
            "final": PROXY_TAG,
        },
    }

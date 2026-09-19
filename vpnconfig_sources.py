# vpnconfig_sources.py
# منابع رایگان کانفیگ VPN روی GitHub

MIXED_SOURCES = [
    ("MatinGhanbari - All protocols",
     "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/all.txt"),
    ("MahanKenway - Mix",
     "https://raw.githubusercontent.com/MahanKenway/Freedom-V2Ray/main/configs/mix.txt"),
    ("MahanKenway - Mix subscription (Base64)",
     "https://raw.githubusercontent.com/MahanKenway/Freedom-V2Ray/main/configs/mix_sub.txt"),
    ("barry-far - All Configs",
     "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/All_Configs_Sub.txt"),
]

PROTOCOL_SOURCES = {
    "vless": [
        ("MatinGhanbari - VLESS",
         "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vless.txt"),
        ("MahanKenway - VLESS",
         "https://raw.githubusercontent.com/MahanKenway/Freedom-V2Ray/main/configs/vless.txt"),
    ],
    "vmess": [
        ("MahanKenway - VMess",
         "https://raw.githubusercontent.com/MahanKenway/Freedom-V2Ray/main/configs/vmess.txt"),
    ],
    "trojan": [
        ("MahanKenway - Trojan",
         "https://raw.githubusercontent.com/MahanKenway/Freedom-V2Ray/main/configs/trojan.txt"),
    ],
    "shadowsocks": [
        ("MahanKenway - Shadowsocks",
         "https://raw.githubusercontent.com/MahanKenway/Freedom-V2Ray/main/configs/ss.txt"),
    ],
}

ALL_SOURCES = MIXED_SOURCES + [
    item for lst in PROTOCOL_SOURCES.values() for item in lst
]
# ProxyEF - Proxy Speed & Availability Tester
# Single-file Windows 10/11 GUI application
# Python 3.9+ / Standard Library only
#
# Features:
# - Test HTTP / HTTPS / SOCKS4 / SOCKS5 proxies (real connection)
# - Latency, success rate, status, error reporting
# - Import proxy lists from TXT / CSV / JSON files
# - Import proxy lists from URLs
# - Built-in public proxy list sources
# - Add proxies manually (multi-line, many formats)
# - Remove failed proxies
# - Clear results (keeps proxy list)
# - Stop running tests
# - Sort by latency / status / protocol
# - Export results (CSV / JSON / TXT)
# - Save / Load state automatically (proxy list + results)
# - Set selected proxy as Windows SYSTEM PROXY (system-wide)
# - Disable / re-enable Windows system proxy
# - Dark / Light theme
# - English / فارسی
# - No external Python packages required
# - Support: https://sajjadef.ir/support

import csv
import ctypes
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


APP_NAME = "ProxyEF"
VERSION = "1.0.0"
SUPPORT_URL = "https://sajjadef.ir/support"

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

if IS_WINDOWS:
    import winreg


# ---------------------------------------------------------------------------
# State file path
# ---------------------------------------------------------------------------
def _default_state_path():
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        if os.access(base, os.W_OK):
            return os.path.join(base, "proxyef_state.json")
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "proxyef_state.json")


STATE_FILE = _default_state_path()


# ---------------------------------------------------------------------------
# Default public proxy list sources
# ---------------------------------------------------------------------------
DEFAULT_SOURCES = [
    ("TheSpeedX - HTTP",
     "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"),
    ("TheSpeedX - SOCKS4",
     "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt"),
    ("TheSpeedX - SOCKS5",
     "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"),
    ("clarketm - Raw list",
     "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"),
    ("monosans - HTTP",
     "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"),
    ("monosans - SOCKS4",
     "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt"),
    ("monosans - SOCKS5",
     "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"),
]

DEFAULT_PROXIES = [
    "http://1.1.1.1:80",
    "http://8.8.8.8:80",
    "socks4://1.1.1.1:1080",
    "socks5://1.1.1.1:1080",
]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
IPV4_RE = re.compile(
    r"(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
)
HOST_RE = re.compile(
    r"(?P<host>(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)|[a-zA-Z0-9.\-]+)"
    r":(?P<port>\d{1,5})"
)
PROTO_PREFIX_RE = re.compile(r"^(https?|socks4a?|socks5h?|socks)://", re.IGNORECASE)


def normalize_protocol(p):
    p = (p or "").lower().strip()
    if p in ("socks", "socks5", "socks5h"):
        return "socks5"
    if p in ("socks4", "socks4a"):
        return "socks4"
    if p in ("https",):
        return "https"
    if p in ("http",):
        return "http"
    return "http"


def parse_proxy_line(line):
    """
    Parse a single proxy line into a dict:
    {
      "protocol": "http"|"https"|"socks4"|"socks5",
      "host": "...",
      "port": int,
      "username": "",
      "password": "",
      "raw": original,
      "key": canonical id
    }
    Supports:
      ip:port
      ip:port:user:pass
      user:pass@ip:port
      proto://ip:port
      proto://user:pass@ip:port
      host:port
    """
    line = (line or "").strip()
    if not line or line.startswith("#"):
        return None

    protocol = "http"
    username = ""
    password = ""

    # Protocol prefix
    m = PROTO_PREFIX_RE.match(line)
    if m:
        protocol = normalize_protocol(m.group(1))
        line = line[m.end():]

    # user:pass@host:port
    if "@" in line:
        creds, rest = line.rsplit("@", 1)
        if ":" in creds:
            username, password = creds.split(":", 1)
        else:
            username = creds
        line = rest

    # host:port:user:pass format
    parts = line.split(":")
    if len(parts) == 4 and parts[0].count(".") == 3 and parts[1].isdigit():
        host, port_s, username, password = parts
        line = f"{host}:{port_s}"

    # host:port
    m = HOST_RE.search(line)
    if not m:
        return None

    host = m.group("host").strip()
    try:
        port = int(m.group("port"))
    except ValueError:
        return None

    if not host or not (1 <= port <= 65535):
        return None

    key = f"{protocol}://{host}:{port}"
    if username:
        key += f"@{username}"

    return {
        "protocol": protocol,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "raw": m.group(0),
        "key": key,
    }


def extract_proxies(text):
    """Extract proxy entries from arbitrary text (TXT/CSV/JSON/HTML)."""
    result = []
    seen = set()

    # Try JSON first (list of strings or list of dicts)
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
            entries = []
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        entries.extend(v)

            for item in entries:
                if isinstance(item, str):
                    p = parse_proxy_line(item)
                elif isinstance(item, dict):
                    proto = item.get("protocol") or item.get("type") or "http"
                    host = item.get("ip") or item.get("host") or ""
                    port = item.get("port")
                    user = item.get("username") or item.get("user") or ""
                    pw = item.get("password") or item.get("pass") or ""
                    if host and port:
                        prefix = normalize_protocol(str(proto))
                        auth = f"{user}:{pw}@" if user else ""
                        p = parse_proxy_line(f"{prefix}://{auth}{host}:{port}")
                    else:
                        p = None
                else:
                    p = None

                if p and p["key"] not in seen:
                    seen.add(p["key"])
                    result.append(p)
        except Exception:
            pass

    # Line-based parse
    for raw_line in re.split(r"[\s,;]+", text):
        p = parse_proxy_line(raw_line)
        if p and p["key"] not in seen:
            seen.add(p["key"])
            result.append(p)

    return result


# ---------------------------------------------------------------------------
# Proxy testing
# ---------------------------------------------------------------------------
def _read_http_response_code(sock):
    """Read the first line of an HTTP response and return the status code."""
    buf = b""
    sock.settimeout(sock.gettimeout())
    while b"\r\n" not in buf and len(buf) < 1024:
        chunk = sock.recv(256)
        if not chunk:
            break
        buf += chunk
    line = buf.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
    parts = line.split()
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


def _socks5_handshake(sock, host, port, username="", password=""):
    # Greeting
    if username:
        sock.sendall(b"\x05\x02\x00\x02")
    else:
        sock.sendall(b"\x05\x01\x00")
    resp = sock.recv(2)
    if len(resp) < 2 or resp[0] != 0x05:
        raise OSError("SOCKS5 bad greeting")
    method = resp[1]
    if method == 0x02:
        u = username.encode()[:255]
        p = password.encode()[:255]
        sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        r = sock.recv(2)
        if len(r) < 2 or r[1] != 0x00:
            raise OSError("SOCKS5 auth failed")
    elif method != 0x00:
        raise OSError("SOCKS5 no acceptable method")

    # Resolve host
    try:
        socket.inet_pton(socket.AF_INET, host)
        addr = socket.inet_aton(host)
        req = b"\x05\x01\x00\x01" + addr + struct.pack("!H", port)
    except OSError:
        # Domain name
        h = host.encode()[:255]
        req = b"\x05\x01\x00\x03" + bytes([len(h)]) + h + struct.pack("!H", port)

    sock.sendall(req)
    resp = sock.recv(10)
    if len(resp) < 2 or resp[1] != 0x00:
        raise OSError(f"SOCKS5 connect refused ({resp[1] if len(resp) > 1 else 'short'})")


def _socks4_handshake(sock, host, port, username=""):
    try:
        socket.inet_pton(socket.AF_INET, host)
        addr = socket.inet_aton(host)
        req = b"\x04\x01" + struct.pack("!H", port) + addr + username.encode() + b"\x00"
    except OSError:
        # SOCKS4a - send domain after null IP
        addr = b"\x00\x00\x00\x01"
        req = (b"\x04\x01" + struct.pack("!H", port) + addr +
               username.encode() + b"\x00" + host.encode() + b"\x00")
    sock.sendall(req)
    resp = sock.recv(8)
    if len(resp) < 8 or resp[1] != 0x5A:
        raise OSError(f"SOCKS4 connect refused ({resp[1] if len(resp) > 1 else 'short'})")


def test_proxy(proxy, target_url="http://httpbin.org/ip", timeout=8.0):
    """
    Test a proxy entry. Returns (success, latency_ms, error_text).
    proxy is a dict from parse_proxy_line().
    """
    proto = proxy["protocol"]
    host = proxy["host"]
    port = proxy["port"]
    user = proxy.get("username") or ""
    pw = proxy.get("password") or ""

    start = time.perf_counter()

    # Parse target URL to extract path
    try:
        parsed = urllib.parse.urlparse(target_url)
    except Exception:
        parsed = None

    if parsed is None or not parsed.hostname:
        return False, None, "Invalid target URL"

    target_host = parsed.hostname
    target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    target_path = parsed.path or "/"
    if parsed.query:
        target_path += "?" + parsed.query

    # HTTP / HTTPS via urllib (simple, reliable)
    if proto in ("http", "https"):
        if user:
            auth = f"{urllib.parse.quote(user)}:{urllib.parse.quote(pw)}@"
        else:
            auth = ""
        proxy_url = f"{proto}://{auth}{host}:{port}"
        try:
            handler = urllib.request.ProxyHandler({
                "http": proxy_url,
                "https": proxy_url,
            })
            opener = urllib.request.build_opener(handler)
            req = urllib.request.Request(
                target_url,
                headers={"User-Agent": f"{APP_NAME}/{VERSION}"},
            )
            with opener.open(req, timeout=timeout) as resp:
                resp.read(64)
            elapsed = (time.perf_counter() - start) * 1000
            return True, elapsed, ""
        except urllib.error.HTTPError as e:
            # HTTP error still means the proxy is working
            elapsed = (time.perf_counter() - start) * 1000
            if 100 <= e.code < 600:
                return True, elapsed, ""
            return False, elapsed, f"HTTP {e.code}"
        except Exception as e:
            return False, None, str(e)[:120]

    # SOCKS4 / SOCKS5 - raw TCP + HTTP GET
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(timeout)
        try:
            if proto == "socks5":
                _socks5_handshake(sock, target_host, target_port, user, pw)
            else:
                _socks4_handshake(sock, target_host, target_port, user)

            # Send plain HTTP GET (works for SOCKS tunnel to port 80)
            get = (
                f"GET {target_path} HTTP/1.1\r\n"
                f"Host: {target_host}\r\n"
                f"User-Agent: {APP_NAME}/{VERSION}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode()
            sock.sendall(get)
            code = _read_http_response_code(sock)
            elapsed = (time.perf_counter() - start) * 1000
            if 100 <= code < 600:
                return True, elapsed, ""
            return False, elapsed, f"HTTP {code or 'no response'}"
        finally:
            sock.close()
    except socket.timeout:
        return False, None, "Timeout"
    except Exception as e:
        return False, None, str(e)[:120]


def fetch_url(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{APP_NAME}/{VERSION} proxy list importer",
            "Accept": "text/plain,text/csv,application/json,text/html,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace")


# ---------------------------------------------------------------------------
# Windows system proxy integration
# ---------------------------------------------------------------------------
INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def _refresh_wininet():
    if not IS_WINDOWS:
        return
    try:
        wininet = ctypes.windll.wininet
        INTERNET_OPTION_SETTINGS_CHANGED = 39
        INTERNET_OPTION_REFRESH = 37
        wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
    except Exception:
        pass


def get_system_proxy():
    """Return (enabled, server_string)."""
    if not IS_WINDOWS:
        return False, ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS,
                            0, winreg.KEY_READ) as key:
            try:
                enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
            except FileNotFoundError:
                enabled = 0
            try:
                server = winreg.QueryValueEx(key, "ProxyServer")[0]
            except FileNotFoundError:
                server = ""
        return bool(enabled), server
    except Exception:
        return False, ""


def set_system_proxy(server_string, bypass="<local>"):
    """
    Enable Windows system proxy with the given server string.
    server_string e.g. "127.0.0.1:8080" or "http=1.2.3.4:80;https=1.2.3.4:80"
    """
    if not IS_WINDOWS:
        return False, "Only available on Windows."
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS,
                            0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server_string)
            if bypass is not None:
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, bypass)
        _refresh_wininet()
        return True, "OK"
    except PermissionError:
        return False, "Permission denied (run as administrator)."
    except Exception as e:
        return False, str(e)


def disable_system_proxy():
    """Disable Windows system proxy (direct connection)."""
    if not IS_WINDOWS:
        return False, "Only available on Windows."
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS,
                            0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            # Keep ProxyServer so we can re-enable it later.
        _refresh_wininet()
        return True, "OK"
    except PermissionError:
        return False, "Permission denied (run as administrator)."
    except Exception as e:
        return False, str(e)


def build_proxy_server_string(entries):
    """
    entries: list of proxy dicts. Build a ProxyServer string for registry.
    If 1 entry -> 'host:port'. If 2+ -> 'http=host:port;https=host:port'.
    SOCKS proxies cannot be used by WinINET directly; warn in caller.
    """
    http_only = [e for e in entries if e["protocol"] in ("http", "https")]
    if not http_only:
        return None

    if len(http_only) == 1:
        return f"{http_only[0]['host']}:{http_only[0]['port']}"

    parts = [f"{e['protocol']}={e['host']}:{e['port']}" for e in http_only[:2]]
    return ";".join(parts)


# ---------------------------------------------------------------------------
# Admin check
# ---------------------------------------------------------------------------
def is_admin():
    if not IS_WINDOWS:
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class ProxyEFApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} {VERSION}")
        self.root.geometry("1220x780")
        self.root.minsize(980, 640)

        self.language = "en"
        self.dark = True
        self.testing = False
        self._create_app_icon()
        self.stop_event = threading.Event()
        self.executor = None
        self.proxy_data = {}  # key -> dict
        self._dirty = False
        self._auto_save_job = None

        self.colors = {}
        self._sort_reverse = False
        self._sort_column = None

        self._setup_style()
        self._build_ui()

        loaded = self._load_state()
        if not loaded:
            self._load_defaults()

        self.refresh_tree()
        self._update_texts()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    def _create_app_icon(self):
        """
        رسم آیکون برنامه به شکل حرف E روی پس‌زمینه رنگی.
        هیچ فایل خارجی نیاز ندارد.
        """
        try:
            size = 64
            img = tk.PhotoImage(width=size, height=size)

            # رنگ‌ها بر اساس تم فعلی
            if self.dark:
                bg_color = "#4ea1ff"
                fg_color = "#0f1115"
            else:
                bg_color = "#1769e0"
                fg_color = "#ffffff"

            # رسم پس‌زمینه
            for x in range(size):
                for y in range(size):
                    img.put(bg_color, (x, y))

            # ضخامت خطوط
            thickness = max(4, size // 10)

            # موقعیت حرف E (وسط تصویر)
            left = size // 4
            top = size // 4
            bottom = size - top
            right = size - (size // 4)

            # خط عمودی سمت چپ
            for y in range(top, bottom):
                for x in range(left, left + thickness):
                    img.put(fg_color, (x, y))

            # خط افقی بالایی
            for y in range(top, top + thickness):
                for x in range(left, right):
                    img.put(fg_color, (x, y))

            # خط افقی وسطی
            mid_y = size // 2 - thickness // 2
            for y in range(mid_y, mid_y + thickness):
                for x in range(left, right - size // 12):
                    img.put(fg_color, (x, y))

            # خط افقی پایینی
            for y in range(bottom - thickness, bottom):
                for x in range(left, right):
                    img.put(fg_color, (x, y))

            # اعمال آیکون
            self.root.iconphoto(True, img)
            self._icon_ref = img
        except Exception as e:
            print("خطا در ساخت آیکون:", e)

    # ---------- Theme ----------
    def _setup_style(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self._apply_theme()

    def _apply_theme(self):
        if self.dark:
            self.colors = {
                "bg": "#15171a", "panel": "#1e2126", "panel2": "#252932",
                "fg": "#eeeeee", "muted": "#a7adb7", "accent": "#4ea1ff",
                "good": "#4fd18b", "bad": "#ff6b6b", "warn": "#ffc857",
                "border": "#343944", "select": "#294f77",
            }
        else:
            self.colors = {
                "bg": "#f4f5f7", "panel": "#ffffff", "panel2": "#e9ebef",
                "fg": "#1c1f24", "muted": "#5f6670", "accent": "#1769e0",
                "good": "#14804a", "bad": "#c62828", "warn": "#9a6700",
                "border": "#cbd0d8", "select": "#cfe1ff",
            }

        self.root.configure(bg=self.colors["bg"])

        self.style.configure(
            ".", background=self.colors["panel"], foreground=self.colors["fg"],
            fieldbackground=self.colors["panel2"], bordercolor=self.colors["border"],
        )
        self.style.configure("TFrame", background=self.colors["bg"])
        self.style.configure("Panel.TFrame", background=self.colors["panel"])
        self.style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["fg"])
        self.style.configure("Panel.TLabel", background=self.colors["panel"], foreground=self.colors["fg"])
        self.style.configure(
            "Title.TLabel", background=self.colors["bg"],
            foreground=self.colors["fg"], font=("Segoe UI", 18, "bold"),
        )
        self.style.configure("Muted.TLabel", background=self.colors["bg"], foreground=self.colors["muted"])
        self.style.configure("PanelMuted.TLabel", background=self.colors["panel"], foreground=self.colors["muted"])
        self.style.configure(
            "TButton", background=self.colors["panel2"],
            foreground=self.colors["fg"], padding=(10, 6),
        )
        self.style.map("TButton", background=[("active", self.colors["select"])])
        self.style.configure(
            "Accent.TButton", background=self.colors["accent"],
            foreground="#ffffff", padding=(12, 7), font=("Segoe UI", 9, "bold"),
        )
        self.style.map("Accent.TButton", background=[("active", self.colors["accent"])])
        self.style.configure(
            "Danger.TButton", background=self.colors["bad"],
            foreground="#ffffff", padding=(10, 6), font=("Segoe UI", 9, "bold"),
        )
        self.style.map("Danger.TButton", background=[("active", self.colors["bad"])])
        self.style.configure(
            "Success.TButton", background=self.colors["good"],
            foreground="#ffffff", padding=(10, 6), font=("Segoe UI", 9, "bold"),
        )
        self.style.map("Success.TButton", background=[("active", self.colors["good"])])
        self.style.configure(
            "Warn.TButton", background=self.colors["warn"],
            foreground="#000000", padding=(10, 6), font=("Segoe UI", 9, "bold"),
        )
        self.style.map("Warn.TButton", background=[("active", self.colors["warn"])])
        self.style.configure(
            "TEntry", fieldbackground=self.colors["panel2"],
            foreground=self.colors["fg"], insertcolor=self.colors["fg"],
        )
        self.style.configure(
            "Treeview", background=self.colors["panel"],
            fieldbackground=self.colors["panel"], foreground=self.colors["fg"],
            rowheight=28, bordercolor=self.colors["border"],
        )
        self.style.map(
            "Treeview",
            background=[("selected", self.colors["select"])],
            foreground=[("selected", self.colors["fg"])],
        )
        self.style.configure(
            "Treeview.Heading", background=self.colors["panel2"],
            foreground=self.colors["fg"], relief="flat", padding=7,
        )
        self.style.configure("TLabelframe", background=self.colors["panel"], foreground=self.colors["fg"])
        self.style.configure("TLabelframe.Label", background=self.colors["panel"], foreground=self.colors["fg"])
        self.style.configure("TCheckbutton", background=self.colors["panel"], foreground=self.colors["fg"])
        self.style.configure(
            "TCombobox", fieldbackground=self.colors["panel2"],
            foreground=self.colors["fg"], background=self.colors["panel2"],
        )

    # ---------- UI ----------
    def _build_ui(self):
        self.main = ttk.Frame(self.root)
        self.main.pack(fill="both", expand=True, padx=14, pady=12)

        # Header
        top = ttk.Frame(self.main)
        top.pack(fill="x")

        self.title_label = ttk.Label(top, text=APP_NAME, style="Title.TLabel")
        self.title_label.pack(side="left")

        self.version_label = ttk.Label(top, text=f"v{VERSION}", style="Muted.TLabel")
        self.version_label.pack(side="left", padx=8, pady=(7, 0))

        self.support_btn = ttk.Button(top, text="Support", command=self.open_support)
        self.support_btn.pack(side="right", padx=(6, 0))

        self.theme_btn = ttk.Button(top, text="☀ Light", command=self.toggle_theme)
        self.theme_btn.pack(side="right", padx=(6, 0))

        self.lang_btn = ttk.Button(top, text="فارسی", command=self.toggle_language)
        self.lang_btn.pack(side="right")

        self.admin_label = ttk.Label(top, text="", style="Muted.TLabel")
        self.admin_label.pack(side="right", padx=(0, 12), pady=(7, 0))

        self.desc_label = ttk.Label(
            self.main,
            text="Test HTTP / HTTPS / SOCKS4 / SOCKS5 proxies and set system proxy.",
            style="Muted.TLabel",
        )
        self.desc_label.pack(anchor="w", pady=(0, 10))

        # System proxy status banner
        self.sysproxy_frame = ttk.Frame(self.main)
        self.sysproxy_frame.pack(fill="x", pady=(0, 6))

        self.sysproxy_label = ttk.Label(
            self.sysproxy_frame, text="", style="Muted.TLabel"
        )
        self.sysproxy_label.pack(side="left")

        # Toolbar row 1
        toolbar = ttk.Frame(self.main)
        toolbar.pack(fill="x", pady=(0, 6))

        self.add_btn = ttk.Button(toolbar, command=self.add_proxy)
        self.add_btn.pack(side="left", padx=(0, 5))

        self.import_btn = ttk.Button(toolbar, command=self.import_file)
        self.import_btn.pack(side="left", padx=5)

        self.url_btn = ttk.Button(toolbar, command=self.import_url)
        self.url_btn.pack(side="left", padx=5)

        self.sources_btn = ttk.Button(toolbar, command=self.sources_dialog)
        self.sources_btn.pack(side="left", padx=5)

        self.test_btn = ttk.Button(toolbar, command=self.start_test, style="Accent.TButton")
        self.test_btn.pack(side="left", padx=(18, 5))

        self.stop_btn = ttk.Button(toolbar, command=self.stop_test, style="Danger.TButton")
        self.stop_btn.pack(side="left", padx=5)

        # Toolbar row 2
        toolbar2 = ttk.Frame(self.main)
        toolbar2.pack(fill="x", pady=(0, 10))

        self.set_proxy_btn = ttk.Button(
            toolbar2, command=self.set_as_system_proxy, style="Success.TButton"
        )
        self.set_proxy_btn.pack(side="left", padx=(0, 5))

        self.disable_proxy_btn = ttk.Button(
            toolbar2, command=self.disable_system_proxy_action, style="Warn.TButton"
        )
        self.disable_proxy_btn.pack(side="left", padx=5)

        self.save_btn = ttk.Button(toolbar2, command=self.save_state_manual)
        self.save_btn.pack(side="left", padx=5)

        self.export_btn = ttk.Button(toolbar2, command=self.export_results)
        self.export_btn.pack(side="left", padx=5)

        self.clear_results_btn = ttk.Button(toolbar2, command=self.clear_results)
        self.clear_results_btn.pack(side="left", padx=5)

        self.remove_failed_btn = ttk.Button(toolbar2, command=self.remove_failed)
        self.remove_failed_btn.pack(side="left", padx=5)

        self.clear_btn = ttk.Button(toolbar2, command=self.clear_all)
        self.clear_btn.pack(side="right")

        # Options row
        options = ttk.Frame(self.main)
        options.pack(fill="x", pady=(0, 8))

        self.target_label = ttk.Label(options)
        self.target_label.pack(side="left")

        self.target_var = tk.StringVar(value="http://httpbin.org/ip")
        self.target_entry = ttk.Entry(options, textvariable=self.target_var, width=32)
        self.target_entry.pack(side="left", padx=(6, 15))

        self.timeout_label = ttk.Label(options)
        self.timeout_label.pack(side="left")

        self.timeout_var = tk.DoubleVar(value=8.0)
        self.timeout_spin = tk.Spinbox(
            options, from_=1, to=30, increment=1,
            textvariable=self.timeout_var, width=6,
            bg=self.colors["panel2"], fg=self.colors["fg"],
            insertbackground=self.colors["fg"],
            buttonbackground=self.colors["panel2"], relief="flat",
        )
        self.timeout_spin.pack(side="left", padx=(6, 15))

        self.workers_label = ttk.Label(options)
        self.workers_label.pack(side="left")

        self.workers_var = tk.IntVar(value=50)
        self.workers_spin = tk.Spinbox(
            options, from_=1, to=300, increment=1,
            textvariable=self.workers_var, width=6,
            bg=self.colors["panel2"], fg=self.colors["fg"],
            insertbackground=self.colors["fg"],
            buttonbackground=self.colors["panel2"], relief="flat",
        )
        self.workers_spin.pack(side="left", padx=(6, 15))

        self.only_failed_var = tk.BooleanVar(value=False)
        self.only_failed_check = ttk.Checkbutton(
            options, variable=self.only_failed_var, command=self.refresh_tree
        )
        self.only_failed_check.pack(side="left")

        # Table
        table_frame = ttk.Frame(self.main)
        table_frame.pack(fill="both", expand=True)

        columns = ("proxy", "protocol", "status", "latency", "success", "last_error")
        self.tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="extended"
        )
        self.tree.heading("proxy", command=lambda: self.sort_column("proxy"))
        self.tree.heading("protocol", command=lambda: self.sort_column("protocol"))
        self.tree.heading("status", command=lambda: self.sort_column("status"))
        self.tree.heading("latency", command=lambda: self.sort_column("latency"))
        self.tree.heading("success", command=lambda: self.sort_column("success"))
        self.tree.heading("last_error", command=lambda: self.sort_column("last_error"))

        self.tree.column("proxy", width=240, anchor="w")
        self.tree.column("protocol", width=90, anchor="center")
        self.tree.column("status", width=110, anchor="center")
        self.tree.column("latency", width=110, anchor="center")
        self.tree.column("success", width=100, anchor="center")
        self.tree.column("last_error", width=380, anchor="w")

        self.tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.tag_configure("online", foreground=self.colors["good"])
        self.tree.tag_configure("offline", foreground=self.colors["bad"])
        self.tree.tag_configure("testing", foreground=self.colors["warn"])

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.tree.bind("<Button-3>", self._show_context_menu)

        # Bottom
        bottom = ttk.Frame(self.main)
        bottom.pack(fill="x", pady=(9, 0))

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)

        self.stats_label = ttk.Label(bottom, text="", style="Muted.TLabel")
        self.stats_label.pack(side="right", padx=(12, 0))

        self.status_label = ttk.Label(self.main, text="", style="Muted.TLabel")
        self.status_label.pack(anchor="w", pady=(6, 0))

        self._update_admin_label()
        self._update_sysproxy_banner()

    def _update_admin_label(self):
        if IS_WINDOWS:
            if is_admin():
                self.admin_label.configure(
                    text=("Admin" if self.language == "en" else "مدیر"),
                    foreground=self.colors["good"],
                )
            else:
                self.admin_label.configure(
                    text=("Non-admin" if self.language == "en" else "بدون دسترسی مدیر"),
                    foreground=self.colors["warn"],
                )
        else:
            self.admin_label.configure(text="")

    def _update_sysproxy_banner(self):
        if not IS_WINDOWS:
            self.sysproxy_label.configure(text="")
            return
        enabled, server = get_system_proxy()
        if enabled and server:
            text = (
                f"● System proxy ACTIVE: {server}"
                if self.language == "en"
                else f"● پروکسی سیستم فعال: {server}"
            )
            color = self.colors["good"]
        else:
            text = (
                "○ System proxy disabled"
                if self.language == "en"
                else "○ پروکسی سیستم غیرفعال است"
            )
            color = self.colors["muted"]
        self.sysproxy_label.configure(text=text, foreground=color)

    def _update_texts(self):
        fa = self.language == "fa"
        self.root.title(
            f"ProxyEF — {'تستر سرعت و وضعیت پروکسی' if fa else 'Proxy Speed & Availability Tester'}"
        )

        self.support_btn.configure(text="پشتیبانی" if fa else "Support")
        self.theme_btn.configure(
            text="☀ روشن" if fa and self.dark else
                 "☾ تاریک" if fa and not self.dark else
                 "☀ Light" if self.dark else "☾ Dark"
        )
        self.lang_btn.configure(text="English" if fa else "فارسی")

        self.desc_label.configure(
            text=(
                "تست واقعی پروکسی HTTP / HTTPS / SOCKS4 / SOCKS5 و تنظیم پروکسی سیستم."
                if fa
                else "Test HTTP / HTTPS / SOCKS4 / SOCKS5 proxies and set system proxy."
            )
        )

        self.add_btn.configure(text="افزودن پروکسی" if fa else "Add Proxy")
        self.import_btn.configure(text="ایمپورت فایل" if fa else "Import File")
        self.url_btn.configure(text="ایمپورت از URL" if fa else "Import URL")
        self.sources_btn.configure(text="منابع پیش‌فرض" if fa else "Default Sources")
        self.test_btn.configure(text="تست همه" if fa else "Test All")
        self.stop_btn.configure(text="توقف" if fa else "Stop")
        self.set_proxy_btn.configure(
            text="تنظیم به‌عنوان پروکسی سیستم" if fa else "Set as System Proxy"
        )
        self.disable_proxy_btn.configure(
            text="غیرفعال کردن پروکسی سیستم" if fa else "Disable System Proxy"
        )
        self.save_btn.configure(text="ذخیره" if fa else "Save")
        self.export_btn.configure(text="خروجی گرفتن" if fa else "Export")
        self.clear_results_btn.configure(
            text="پاک کردن نتایج" if fa else "Clear Results"
        )
        self.remove_failed_btn.configure(text="حذف ناموفق‌ها" if fa else "Remove Failed")
        self.clear_btn.configure(text="پاک کردن همه" if fa else "Clear All")

        self.target_label.configure(text="آدرس تست:" if fa else "Target URL:")
        self.timeout_label.configure(text="مهلت (ثانیه):" if fa else "Timeout (s):")
        self.workers_label.configure(text="همزمان:" if fa else "Parallel:")
        self.only_failed_check.configure(text="فقط ناموفق‌ها" if fa else "Failed only")

        heads = {
            "proxy": "Proxy" if not fa else "پروکسی",
            "protocol": "Protocol" if not fa else "پروتکل",
            "status": "Status" if not fa else "وضعیت",
            "latency": "Latency" if not fa else "زمان پاسخ",
            "success": "Success" if not fa else "موفقیت",
            "last_error": "Last Error" if not fa else "آخرین خطا",
        }
        for col, text in heads.items():
            self.tree.heading(col, text=text)

        self._rebuild_context_menu()
        self._refresh_stats()
        self._update_admin_label()
        self._update_sysproxy_banner()

    def _rebuild_context_menu(self):
        fa = self.language == "fa"
        self.context_menu.delete(0, "end")
        self.context_menu.add_command(
            label="Set as System Proxy" if not fa else "تنظیم به‌عنوان پروکسی سیستم",
            command=self.set_as_system_proxy,
        )
        self.context_menu.add_command(
            label="Copy" if not fa else "کپی",
            command=self.copy_selected,
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Remove selected" if not fa else "حذف انتخاب‌شده‌ها",
            command=self.remove_selected,
        )

    def _show_context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def copy_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        text = "\n".join(selection)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status(
            "Copied to clipboard." if self.language == "en"
            else "در کلیپ‌بورد کپی شد."
        )

    def remove_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        for key in selection:
            self.proxy_data.pop(key, None)
        self.refresh_tree()
        self.mark_dirty()
        self.set_status(
            f"Removed {len(selection)} proxies."
            if self.language == "en"
            else f"{len(selection)} پروکسی حذف شد."
        )

    # ---------- Data ----------
    def _load_defaults(self):
        for line in DEFAULT_PROXIES:
            p = parse_proxy_line(line)
            if p:
                self.proxy_data[p["key"]] = self._entry_from_parsed(p)

    @staticmethod
    def _entry_from_parsed(p):
        return {
            "protocol": p["protocol"],
            "host": p["host"],
            "port": p["port"],
            "username": p.get("username", ""),
            "password": p.get("password", ""),
            "status": "Not tested",
            "latency": None,
            "success": None,
            "error": "",
        }

    def add_proxy(self, parsed=None, refresh=True):
        if parsed is None:
            return False
        key = parsed["key"]
        if key not in self.proxy_data:
            self.proxy_data[key] = self._entry_from_parsed(parsed)
            self.mark_dirty()
            if refresh:
                self.refresh_tree()
            return True
        return False

    def refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        only_failed = self.only_failed_var.get()

        for key, data in self.proxy_data.items():
            status = data["status"]
            if only_failed and status != "OFFLINE":
                continue

            latency = data["latency"]
            success = data["success"]
            error = data["error"]

            if self.language == "fa":
                status_display = {
                    "Not tested": "تست نشده",
                    "Testing": "در حال تست",
                    "ONLINE": "فعال",
                    "OFFLINE": "قطع",
                }.get(status, status)
            else:
                status_display = status

            latency_text = f"{latency:.1f} ms" if latency is not None else "—"
            success_text = f"{success:.0f}%" if success is not None else "—"
            proto_display = (data.get("protocol") or "").upper()

            tag = ""
            if status == "ONLINE":
                tag = "online"
            elif status == "OFFLINE":
                tag = "offline"
            elif status == "Testing":
                tag = "testing"

            self.tree.insert(
                "", "end", iid=key,
                values=(key, proto_display, status_display, latency_text, success_text, error),
                tags=(tag,),
            )

        self._refresh_stats()

    def _refresh_stats(self):
        total = len(self.proxy_data)
        online = sum(1 for d in self.proxy_data.values() if d["status"] == "ONLINE")
        offline = sum(1 for d in self.proxy_data.values() if d["status"] == "OFFLINE")
        tested = sum(
            1 for d in self.proxy_data.values()
            if d["status"] in ("ONLINE", "OFFLINE")
        )

        if self.language == "fa":
            self.stats_label.configure(
                text=f"کل: {total}   تست‌شده: {tested}   فعال: {online}   ناموفق: {offline}"
            )
        else:
            self.stats_label.configure(
                text=f"Total: {total}   Tested: {tested}   Online: {online}   Failed: {offline}"
            )

    # ---------- Import ----------
    def import_file(self):
        path = filedialog.askopenfilename(
            title="Import proxy list",
            filetypes=[
                ("Proxy lists", "*.txt *.csv *.json"),
                ("Text files", "*.txt"),
                ("CSV files", "*.csv"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                text = f.read()
            proxies = extract_proxies(text)
            added = 0
            for p in proxies:
                if self.add_proxy(p, refresh=False):
                    added += 1
            self.refresh_tree()
            self.mark_dirty()
            self.set_status(
                f"{added} proxies imported." if self.language == "en"
                else f"{added} پروکسی وارد شد."
            )
        except Exception as e:
            messagebox.showerror(
                "Error" if self.language == "en" else "خطا", str(e)
            )

    def import_url(self):
        self._url_dialog()

    def _url_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Import proxies from URL")
        win.geometry("700x500")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])

        ttk.Label(
            win,
            text=(
                "Paste a URL, then click Import."
                if self.language == "en"
                else "آدرس URL را وارد کنید و روی ایمپورت بزنید."
            ),
        ).pack(anchor="w", padx=15, pady=(15, 8))

        var = tk.StringVar()
        entry = ttk.Entry(win, textvariable=var)
        entry.pack(fill="x", padx=15)

        listbox = tk.Listbox(
            win,
            bg=self.colors["panel2"], fg=self.colors["fg"],
            selectbackground=self.colors["select"], relief="flat",
        )
        listbox.pack(fill="both", expand=True, padx=15, pady=12)

        for name, url in DEFAULT_SOURCES:
            listbox.insert("end", f"{name}  |  {url}")

        def use_selected():
            sel = listbox.curselection()
            if sel:
                var.set(DEFAULT_SOURCES[sel[0]][1])

        listbox.bind("<Double-Button-1>", lambda e: use_selected())

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=15, pady=(0, 15))

        ttk.Button(
            btns,
            text="Use selected" if self.language == "en" else "انتخاب",
            command=use_selected,
        ).pack(side="left")

        def do_import():
            url = var.get().strip()
            if not url:
                return

            def worker():
                try:
                    text = fetch_url(url)
                    proxies = extract_proxies(text)
                    added = 0
                    for p in proxies:
                        if self.add_proxy(p, refresh=False):
                            added += 1
                    self.root.after(0, self.refresh_tree)
                    self.root.after(0, self.mark_dirty)
                    self.root.after(
                        0,
                        lambda: self.set_status(
                            f"Imported {added} proxies from URL."
                            if self.language == "en"
                            else f"{added} پروکسی از URL وارد شد."
                        ),
                    )
                    self.root.after(0, win.destroy)
                except Exception as e:
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Import Error" if self.language == "en" else "خطای ایمپورت",
                            str(e), parent=win,
                        ),
                    )

            threading.Thread(target=worker, daemon=True).start()

        ttk.Button(
            btns,
            text="Import" if self.language == "en" else "ایمپورت",
            style="Accent.TButton",
            command=do_import,
        ).pack(side="right")

        entry.focus_set()

    def sources_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Default proxy sources")
        win.geometry("920x520")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])

        ttk.Label(
            win,
            text=(
                "Select one or more public proxy sources:"
                if self.language == "en"
                else "یک یا چند منبع عمومی پروکسی را انتخاب کنید:"
            ),
        ).pack(anchor="w", padx=15, pady=(15, 8))

        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=15)

        vars_ = []
        entries_ = []
        for name, url in DEFAULT_SOURCES:
            v = tk.BooleanVar(value=True)
            vars_.append(v)
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=5)
            ttk.Checkbutton(row, variable=v).pack(side="left")
            ttk.Label(row, text=name, width=24).pack(side="left")
            e = ttk.Entry(row)
            e.insert(0, url)
            e.pack(side="left", fill="x", expand=True)
            entries_.append(e)

        def import_selected():
            selected = []
            for v, e in zip(vars_, entries_):
                if v.get():
                    u = e.get().strip()
                    if u:
                        selected.append(u)

            if not selected:
                return

            def worker():
                total_added = 0
                errors = []
                for url in selected:
                    try:
                        text = fetch_url(url)
                        proxies = extract_proxies(text)
                        for p in proxies:
                            if self.add_proxy(p, refresh=False):
                                total_added += 1
                    except Exception as e:
                        errors.append(f"{url}: {e}")

                self.root.after(0, self.refresh_tree)
                self.root.after(0, self.mark_dirty)
                self.root.after(
                    0,
                    lambda: self.set_status(
                        f"Imported {total_added} proxies."
                        if self.language == "en"
                        else f"{total_added} پروکسی وارد شد."
                    ),
                )
                self.root.after(0, win.destroy)

                if errors:
                    self.root.after(
                        0,
                        lambda: messagebox.showwarning(
                            "Some sources failed"
                            if self.language == "en"
                            else "بعضی منابع ناموفق بودند",
                            "\n\n".join(errors[:5]),
                        ),
                    )

            threading.Thread(target=worker, daemon=True).start()

        buttons = ttk.Frame(win)
        buttons.pack(fill="x", padx=15, pady=15)

        ttk.Button(
            buttons,
            text="Import selected" if self.language == "en" else "ایمپورت انتخاب‌شده",
            style="Accent.TButton",
            command=import_selected,
        ).pack(side="right")

    # ---------- Add / remove ----------
    def add_proxy_dialog_manual(self):
        pass  # kept for compatibility

    def add_proxy_dialog(self):
        pass  # kept for compatibility

    # Real implementation bound to Add button
    def add_proxy(self, *args, **kwargs):
        # If called as event handler (no kwargs), open dialog
        if kwargs.get("parsed") is None and (not args or not isinstance(args[0], dict)):
            self._open_add_proxy_dialog()
            return False
        parsed = kwargs.get("parsed") if kwargs.get("parsed") is not None else args[0]
        refresh = kwargs.get("refresh", True)
        key = parsed["key"]
        if key not in self.proxy_data:
            self.proxy_data[key] = self._entry_from_parsed(parsed)
            self.mark_dirty()
            if refresh:
                self.refresh_tree()
            return True
        return False

    def _open_add_proxy_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Add Proxy" if self.language == "en" else "افزودن پروکسی")
        win.geometry("620x480")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])

        ttk.Label(
            win,
            text=(
                "Enter one or more proxies (one per line).\n"
                "Supported formats:\n"
                "  • ip:port\n"
                "  • user:pass@ip:port\n"
                "  • ip:port:user:pass\n"
                "  • proto://ip:port   (proto = http, https, socks4, socks5)"
                if self.language == "en"
                else "یک یا چند پروکسی وارد کنید (هر خط یکی).\n"
                     "فرمت‌های پشتیبانی‌شده:\n"
                     "  • ip:port\n"
                     "  • user:pass@ip:port\n"
                     "  • ip:port:user:pass\n"
                     "  • proto://ip:port   (proto = http, https, socks4, socks5)"
            ),
            justify="left",
        ).pack(anchor="w", padx=15, pady=(15, 8))

        text_frame = ttk.Frame(win)
        text_frame.pack(fill="both", expand=True, padx=15)

        text = tk.Text(
            text_frame, height=12, wrap="word",
            bg=self.colors["panel2"], fg=self.colors["fg"],
            insertbackground=self.colors["fg"], relief="flat",
        )
        text.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
        sb.pack(side="right", fill="y")
        text.configure(yscrollcommand=sb.set)

        default_proto_var = tk.StringVar(value="http")
        proto_row = ttk.Frame(win)
        proto_row.pack(fill="x", padx=15, pady=(8, 0))
        ttk.Label(proto_row, text="Default protocol:" if self.language == "en" else "پروتکل پیش‌فرض:").pack(side="left")
        ttk.Combobox(
            proto_row, textvariable=default_proto_var,
            values=["http", "https", "socks4", "socks5"],
            state="readonly", width=12,
        ).pack(side="left", padx=6)

        def save():
            content = text.get("1.0", "end")
            added = 0
            default_proto = default_proto_var.get()
            for raw_line in content.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                # If no protocol prefix, prepend default
                if not PROTO_PREFIX_RE.match(line):
                    line = f"{default_proto}://{line}"
                p = parse_proxy_line(line)
                if p and self.add_proxy(parsed=p, refresh=False):
                    added += 1

            if added == 0:
                messagebox.showerror(
                    "No valid proxy" if self.language == "en" else "پروکسی معتبر نیست",
                    "No valid proxy was found in the input."
                    if self.language == "en"
                    else "هیچ پروکسی معتبری در ورودی پیدا نشد.",
                    parent=win,
                )
                return

            self.refresh_tree()
            self.set_status(
                f"Added {added} proxies."
                if self.language == "en"
                else f"{added} پروکسی اضافه شد."
            )
            win.destroy()

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=15, pady=15)

        ttk.Button(
            btns,
            text="Cancel" if self.language == "en" else "انصراف",
            command=win.destroy,
        ).pack(side="right", padx=(6, 0))

        ttk.Button(
            btns,
            text="Add" if self.language == "en" else "افزودن",
            style="Accent.TButton",
            command=save,
        ).pack(side="right")

        text.focus_set()

    def remove_failed(self):
        failed = [k for k, d in self.proxy_data.items() if d["status"] == "OFFLINE"]
        for k in failed:
            del self.proxy_data[k]
        self.refresh_tree()
        self.mark_dirty()
        self.set_status(
            f"Removed {len(failed)} failed proxies."
            if self.language == "en"
            else f"{len(failed)} پروکسی ناموفق حذف شد."
        )

    def clear_all(self):
        if not self.proxy_data:
            return
        ok = messagebox.askyesno(
            "Clear" if self.language == "en" else "پاک کردن",
            "Remove all proxies?"
            if self.language == "en"
            else "همه پروکسی‌ها حذف شوند؟",
        )
        if ok:
            self.proxy_data.clear()
            self.refresh_tree()
            self.mark_dirty()

    def clear_results(self):
        if not self.proxy_data:
            return
        ok = messagebox.askyesno(
            "Clear results" if self.language == "en" else "پاک کردن نتایج",
            "Reset all test results? Proxies are kept."
            if self.language == "en"
            else "همه نتایج تست پاک شوند؟ پروکسی‌ها حفظ می‌شوند.",
        )
        if not ok:
            return
        for k in self.proxy_data:
            self.proxy_data[k]["status"] = "Not tested"
            self.proxy_data[k]["latency"] = None
            self.proxy_data[k]["success"] = None
            self.proxy_data[k]["error"] = ""
        self.refresh_tree()
        self.mark_dirty()
        self.set_status(
            "Test results cleared." if self.language == "en"
            else "نتایج تست پاک شد."
        )

    # ---------- Export ----------
    def export_results(self):
        if not self.proxy_data:
            messagebox.showinfo(
                "No data" if self.language == "en" else "داده‌ای موجود نیست",
                "There is nothing to export."
                if self.language == "en"
                else "چیزی برای خروجی گرفتن وجود ندارد.",
            )
            return

        default_name = f"proxyef_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            title="Export results" if self.language == "en" else "خروجی گرفتن",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[
                ("CSV", "*.csv"),
                ("JSON", "*.json"),
                ("Text", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            ext = os.path.splitext(path)[1].lower()
            rows = []
            for k, d in self.proxy_data.items():
                rows.append({
                    "proxy": k,
                    "protocol": d["protocol"],
                    "host": d["host"],
                    "port": d["port"],
                    "username": d.get("username", ""),
                    "status": d["status"],
                    "latency_ms": d["latency"],
                    "success_percent": d["success"],
                    "error": d["error"],
                })

            if ext == ".json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({
                        "app": APP_NAME,
                        "version": VERSION,
                        "exported_at": datetime.now().isoformat(),
                        "target": self.target_var.get(),
                        "results": rows,
                    }, f, indent=2, ensure_ascii=False)
            elif ext == ".txt":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"{APP_NAME} v{VERSION} Export - {datetime.now()}\n")
                    f.write(f"Target: {self.target_var.get()}\n")
                    f.write("=" * 90 + "\n")
                    f.write(f"{'PROXY':<45}{'PROTO':<9}{'STATUS':<12}{'LATENCY':<14}{'SUCCESS':<10}ERROR\n")
                    f.write("-" * 90 + "\n")
                    for r in rows:
                        lat = f"{r['latency_ms']:.1f} ms" if r["latency_ms"] is not None else "—"
                        suc = f"{r['success_percent']:.0f}%" if r["success_percent"] is not None else "—"
                        f.write(
                            f"{r['proxy']:<45}{r['protocol']:<9}{r['status']:<12}"
                            f"{lat:<14}{suc:<10}{r['error']}\n"
                        )
            else:
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(
                        f,
                        fieldnames=["proxy", "protocol", "host", "port",
                                    "username", "status", "latency_ms",
                                    "success_percent", "error"],
                    )
                    w.writeheader()
                    w.writerows(rows)

            self.set_status(
                f"Exported to {path}" if self.language == "en"
                else f"خروجی در {path} ذخیره شد"
            )
        except Exception as e:
            messagebox.showerror(
                "Export error" if self.language == "en" else "خطای خروجی",
                str(e),
            )

    # ---------- Save / Load state ----------
    def mark_dirty(self):
        self._dirty = True
        if self._auto_save_job is not None:
            try:
                self.root.after_cancel(self._auto_save_job)
            except Exception:
                pass
        self._auto_save_job = self.root.after(600, self._auto_save)

    def _auto_save(self):
        self._auto_save_job = None
        self.save_state(silent=True)

    def save_state(self, silent=False):
        try:
            payload = {
                "app": APP_NAME,
                "version": VERSION,
                "saved_at": datetime.now().isoformat(),
                "target": self.target_var.get(),
                "timeout": self.timeout_var.get(),
                "workers": self.workers_var.get(),
                "language": self.language,
                "dark": self.dark,
                "proxies": self.proxy_data,
            }
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, STATE_FILE)
            self._dirty = False
            if not silent:
                self.set_status(
                    f"Saved to {STATE_FILE}"
                    if self.language == "en"
                    else f"ذخیره شد در {STATE_FILE}"
                )
        except Exception as e:
            if not silent:
                messagebox.showerror(
                    "Save error" if self.language == "en" else "خطای ذخیره",
                    str(e),
                )

    def save_state_manual(self):
        self.save_state(silent=False)

    def _load_state(self):
        if not os.path.exists(STATE_FILE):
            return False
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return False

        try:
            proxies = payload.get("proxies") or {}
            for key, d in proxies.items():
                if not isinstance(d, dict):
                    continue
                if "host" not in d or "port" not in d:
                    continue
                self.proxy_data[key] = {
                    "protocol": d.get("protocol", "http"),
                    "host": d.get("host"),
                    "port": int(d.get("port")),
                    "username": d.get("username", ""),
                    "password": d.get("password", ""),
                    "status": d.get("status", "Not tested"),
                    "latency": d.get("latency"),
                    "success": d.get("success"),
                    "error": d.get("error", ""),
                }
            if not self.proxy_data:
                return False

            if payload.get("target"):
                self.target_var.set(payload["target"])
            try:
                if payload.get("timeout"):
                    self.timeout_var.set(float(payload["timeout"]))
                if payload.get("workers"):
                    self.workers_var.set(int(payload["workers"]))
            except Exception:
                pass
            if payload.get("language") in ("en", "fa"):
                self.language = payload["language"]
            if isinstance(payload.get("dark"), bool):
                self.dark = payload["dark"]
                self._apply_theme()
            return True
        except Exception:
            return False

    # ---------- System proxy ----------
    def set_as_system_proxy(self):
        if not IS_WINDOWS:
            messagebox.showinfo(
                "Windows only",
                "This feature is only available on Windows.",
            )
            return

        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning(
                "No selection" if self.language == "en" else "انتخابی وجود ندارد",
                "Select one proxy (or two) from the list first."
                if self.language == "en"
                else "ابتدا یک یا دو پروکسی از لیست انتخاب کنید.",
            )
            return

        selected_entries = []
        for key in selection[:2]:
            d = self.proxy_data.get(key)
            if d:
                selected_entries.append({**d, "key": key})

        # Windows' WinINET system proxy does not support SOCKS natively.
        supported = [e for e in selected_entries if e["protocol"] in ("http", "https")]
        unsupported = [e for e in selected_entries if e["protocol"] not in ("http", "https")]

        if unsupported and not supported:
            messagebox.showwarning(
                "Not supported" if self.language == "en" else "پشتیبانی نمی‌شود",
                "Windows system proxy only supports HTTP/HTTPS proxies.\n"
                "SOCKS proxies require third-party tools (e.g. Proxifier)."
                if self.language == "en"
                else "پروکسی سیستم ویندوز فقط از HTTP/HTTPS پشتیبانی می‌کند.\n"
                     "پروکسی‌های SOCKS نیازمند ابزار جانبی (مثل Proxifier) هستند.",
            )
            return

        server_string = build_proxy_server_string(supported)
        if not server_string:
            return

        # Confirm
        msg = (
            f"Set Windows system proxy to:\n{server_string}\n\n"
            "This will route all HTTP/HTTPS traffic of your Windows apps through this proxy.\n"
            "You can revert with 'Disable System Proxy'."
            if self.language == "en"
            else f"پروکسی سیستم ویندوز روی این مقدار تنظیم شود؟\n{server_string}\n\n"
                 "تمام ترافیک HTTP/HTTPS برنامه‌های ویندوز از این پروکسی عبور خواهد کرد.\n"
                 "برای بازگردانی از دکمه «غیرفعال کردن پروکسی سیستم» استفاده کنید."
        )
        if not messagebox.askyesno(
            "Confirm" if self.language == "en" else "تأیید", msg
        ):
            return

        ok, err = set_system_proxy(server_string)
        if ok:
            self._update_sysproxy_banner()
            messagebox.showinfo(
                "Success" if self.language == "en" else "موفق",
                (
                    f"System proxy is now ACTIVE: {server_string}\n\n"
                    "Note: Some apps (browsers, Electron apps, etc.) may need a restart "
                    "to pick up the new proxy setting."
                    if self.language == "en"
                    else f"پروکسی سیستم فعال شد: {server_string}\n\n"
                         "توجه: برخی برنامه‌ها (مرورگرها، اپ‌های Electron و...) ممکن است "
                         "برای اعمال تنظیمات جدید نیاز به restart داشته باشند."
                ),
            )
            self.set_status(
                "System proxy enabled." if self.language == "en"
                else "پروکسی سیستم فعال شد."
            )
        else:
            messagebox.showerror(
                "Failed" if self.language == "en" else "ناموفق",
                err,
            )

    def disable_system_proxy_action(self):
        if not IS_WINDOWS:
            messagebox.showinfo("Windows only", "This feature is only available on Windows.")
            return

        enabled, current = get_system_proxy()
        if not enabled:
            messagebox.showinfo(
                "Already disabled" if self.language == "en" else "قبلاً غیرفعال است",
                "System proxy is already disabled."
                if self.language == "en"
                else "پروکسی سیستم در حال حاضر غیرفعال است.",
            )
            return

        if not messagebox.askyesno(
            "Confirm" if self.language == "en" else "تأیید",
            (
                f"Disable system proxy (currently: {current}) and return to direct connection?"
                if self.language == "en"
                else f"پروکسی سیستم (فعلی: {current}) غیرفعال شود و به اتصال مستقیم برگردیم؟"
            ),
        ):
            return

        ok, err = disable_system_proxy()
        if ok:
            self._update_sysproxy_banner()
            messagebox.showinfo(
                "Success" if self.language == "en" else "موفق",
                "System proxy disabled. Internet is now direct."
                if self.language == "en"
                else "پروکسی سیستم غیرفعال شد. اتصال اینترنت مستقیم است.",
            )
            self.set_status(
                "System proxy disabled." if self.language == "en"
                else "پروکسی سیستم غیرفعال شد."
            )
        else:
            messagebox.showerror(
                "Failed" if self.language == "en" else "ناموفق",
                err,
            )

    # ---------- Testing ----------
    def start_test(self):
        if self.testing:
            return

        keys = list(self.proxy_data.keys())
        if not keys:
            messagebox.showinfo(
                "No proxy" if self.language == "en" else "پروکسی موجود نیست",
                "Add or import proxies first."
                if self.language == "en"
                else "ابتدا پروکسی اضافه یا ایمپورت کنید.",
            )
            return

        target = self.target_var.get().strip() or "http://httpbin.org/ip"

        try:
            timeout = max(1.0, float(self.timeout_var.get()))
            workers = max(1, min(300, int(self.workers_var.get())))
        except Exception:
            timeout = 8.0
            workers = 50

        self.testing = True
        self.stop_event.clear()
        self.progress["maximum"] = len(keys)
        self.progress["value"] = 0
        self.test_btn.configure(state="disabled")
        self.set_status("Testing..." if self.language == "en" else "در حال تست...")

        for k in keys:
            self.proxy_data[k]["status"] = "Testing"
            self.proxy_data[k]["error"] = ""
        self.refresh_tree()

        def run():
            completed = 0
            msg = "Test completed." if self.language == "en" else "تست تمام شد."
            try:
                self.executor = ThreadPoolExecutor(max_workers=workers)

                futures = {}
                for k in keys:
                    d = self.proxy_data[k]
                    proxy_entry = {
                        "protocol": d["protocol"],
                        "host": d["host"],
                        "port": d["port"],
                        "username": d.get("username", ""),
                        "password": d.get("password", ""),
                    }
                    futures[self.executor.submit(
                        test_proxy, proxy_entry, target, timeout
                    )] = k

                for future in as_completed(futures):
                    if self.stop_event.is_set():
                        break

                    k = futures[future]
                    try:
                        ok, latency, error = future.result()
                    except Exception as e:
                        ok, latency, error = False, None, str(e)[:120]

                    if k in self.proxy_data:
                        d = self.proxy_data[k]
                        if ok:
                            d["status"] = "ONLINE"
                            d["latency"] = latency
                            d["success"] = 100
                            d["error"] = ""
                        else:
                            d["status"] = "OFFLINE"
                            d["latency"] = latency
                            d["success"] = 0
                            d["error"] = (error or "")[:120]

                    completed += 1
                    self.root.after(0, self.refresh_tree)
                    self.root.after(
                        0,
                        lambda n=completed: self.progress.configure(value=n),
                    )

                if self.stop_event.is_set():
                    for k, d in self.proxy_data.items():
                        if d["status"] == "Testing":
                            d["status"] = "Not tested"
                    msg = "Test stopped." if self.language == "en" else "تست متوقف شد."
            finally:
                if self.executor:
                    self.executor.shutdown(wait=False, cancel_futures=True)
                    self.executor = None

                self.testing = False
                self.root.after(0, self.refresh_tree)
                self.root.after(0, lambda: self.test_btn.configure(state="normal"))
                self.root.after(0, lambda: self.set_status(msg))
                self.root.after(0, self.mark_dirty)

        threading.Thread(target=run, daemon=True).start()

    def stop_test(self):
        if not self.testing:
            return
        self.stop_event.set()
        self.set_status("Stopping..." if self.language == "en" else "در حال توقف...")

    # ---------- Sorting ----------
    def sort_column(self, column):
        items = []
        for key, d in self.proxy_data.items():
            if column == "proxy":
                v = key
            elif column == "protocol":
                v = d["protocol"]
            elif column == "status":
                v = d["status"]
            elif column == "latency":
                v = d["latency"] if d["latency"] is not None else 999999
            elif column == "success":
                v = d["success"] if d["success"] is not None else -1
            else:
                v = d["error"]
            items.append((v, key))

        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False

        items.sort(key=lambda x: x[0], reverse=self._sort_reverse)

        for index, (_, key) in enumerate(items):
            if self.tree.exists(key):
                self.tree.move(key, "", index)

    # ---------- Misc ----------
    def set_status(self, text):
        self.status_label.configure(text=text)

    def toggle_theme(self):
        self.dark = not self.dark
        self._apply_theme()
        self._rebuild_tree_tags()
        self._update_texts()

        for spin in (self.timeout_spin, self.workers_spin):
            spin.configure(
                bg=self.colors["panel2"],
                fg=self.colors["fg"],
                insertbackground=self.colors["fg"],
                buttonbackground=self.colors["panel2"],
            )
        self.mark_dirty()

    def _rebuild_tree_tags(self):
        self.tree.tag_configure("online", foreground=self.colors["good"])
        self.tree.tag_configure("offline", foreground=self.colors["bad"])
        self.tree.tag_configure("testing", foreground=self.colors["warn"])

    def toggle_language(self):
        self.language = "fa" if self.language == "en" else "en"
        self.refresh_tree()
        self._update_texts()
        self.mark_dirty()

    def open_support(self):
        webbrowser.open(SUPPORT_URL)

    def on_close(self):
        self.stop_event.set()
        try:
            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            if self._auto_save_job is not None:
                try:
                    self.root.after_cancel(self._auto_save_job)
                except Exception:
                    pass
                self._auto_save_job = None
            self.save_state(silent=True)
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = ProxyEFApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
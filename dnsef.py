# DNSEF - DNS Speed & Availability Tester
# Single-file Windows 10/11 GUI application
# Python 3.9+ / Standard Library only
#
# Features:
# - Fast parallel DNS query testing (real DNS query, not ICMP ping)
# - IPv4 and IPv6 DNS server support
# - ONLINE / OFFLINE status, latency, success rate
# - Import TXT / CSV / JSON files
# - Import DNS lists from URLs
# - Built-in public DNS list sources
# - Add/remove DNS servers (multi-line, IPv4 + IPv6)
# - Remove failed servers
# - Clear test results (keeps DNS list)
# - Stop running tests
# - Sort by latency/status
# - Export results (CSV / JSON / TXT)
# - Save / Load state (DNS list + results) automatically
# - Set selected DNS as Windows system DNS (needs admin)
# - Reset system DNS back to DHCP/automatic
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


APP_NAME = "DNSEF"
VERSION = "1.2.0"
SUPPORT_URL = "https://sajjadef.ir/support"

# State is stored next to the script if possible, otherwise in the user home.
def _default_state_path():
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        if os.access(base, os.W_OK):
            return os.path.join(base, "dnsef_state.json")
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "dnsef_state.json")


STATE_FILE = _default_state_path()

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

DEFAULT_SOURCES = [
    (
        "GitHub - Public DNS IPv4",
        "https://raw.githubusercontent.com/takuya/public_dns_list/master/dns-list-ipv4.txt",
    ),
    (
        "GitHub - Public DNS CSV",
        "https://gist.githubusercontent.com/evoknow/9e26202fdb208d530475bb6549e20aae/raw/public_dns_servers.csv",
    ),
    (
        "public-dns.info - valid nameservers",
        "https://public-dns.info/nameservers.txt",
    ),
    (
        "GitHub - Public DNS Servers",
        "https://raw.githubusercontent.com/DedBash/Public-DNS-List/master/README.md",
    ),
]

DEFAULT_DNS = [
    "1.1.1.1", "1.0.0.1",
    "8.8.8.8", "8.8.4.4",
    "9.9.9.9", "149.112.112.112",
    "208.67.222.222", "208.67.220.220",
    "94.140.14.14", "94.140.15.15",
    "45.159.149.19",
    "185.164.72.97",
    "185.8.174.140",
    "130.185.77.69",
    "195.177.255.170",
    "178.239.151.228",
]

IPV4_RE = re.compile(
    r"(?<![\w.])"
    r"(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?![\w.])"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def is_admin():
    """Return True if the current process has administrator privileges."""
    if not IS_WINDOWS:
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def is_valid_ip(s):
    """Return True if s is a valid IPv4 or IPv6 address."""
    s = s.strip()
    if not s:
        return False
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, s)
            return True
        except (OSError, socket.error):
            pass
    return False


def is_ipv6(s):
    return ":" in s


def extract_ips(text):
    """Extract IPv4 and IPv6 addresses from TXT/CSV/JSON/Markdown."""
    found = []
    seen = set()

    # IPv4 (regex handles URLs, markdown, CSV naturally)
    for ip in IPV4_RE.findall(text):
        if ip not in seen:
            seen.add(ip)
            found.append(ip)

    # IPv6 - tokenize hex:colon runs, then validate with inet_pton
    tokens = re.findall(r"[0-9a-fA-F:]{4,}", text)
    for tok in tokens:
        if ":" not in tok or tok in seen:
            continue
        try:
            socket.inet_pton(socket.AF_INET6, tok)
            seen.add(tok)
            found.append(tok)
        except (OSError, socket.error):
            pass

    return found


def dns_query(server, domain="example.com", timeout=2.0):
    """
    Send a real DNS A query directly to the specified DNS server over UDP.
    Supports both IPv4 and IPv6 DNS servers.
    Returns (success, latency_ms, error_text).
    """
    v6 = is_ipv6(server)
    family = socket.AF_INET6 if v6 else socket.AF_INET
    addr = (server, 53, 0, 0) if v6 else (server, 53)

    transaction_id = os.urandom(2)
    flags = b"\x01\x00"  # recursion desired
    qdcount = struct.pack("!H", 1)
    header = transaction_id + flags + qdcount + b"\x00\x00\x00\x00\x00\x00"

    question = b""
    for label in domain.split("."):
        encoded = label.encode("ascii", errors="ignore")
        if not encoded or len(encoded) > 63:
            return False, None, "Invalid domain"
        question += bytes([len(encoded)]) + encoded
    question += b"\x00" + struct.pack("!HH", 1, 1)  # A, IN

    packet = header + question
    start = time.perf_counter()

    sock = socket.socket(family, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, addr)
        data, _ = sock.recvfrom(4096)
        elapsed = (time.perf_counter() - start) * 1000

        if len(data) < 12:
            return False, elapsed, "Invalid DNS response"

        if data[:2] != transaction_id:
            return False, elapsed, "Transaction ID mismatch"

        flags_value = struct.unpack("!H", data[2:4])[0]
        rcode = flags_value & 0x000F
        if rcode != 0:
            return False, elapsed, f"DNS error RCODE={rcode}"

        return True, elapsed, ""
    except socket.timeout:
        return False, None, "Timeout"
    except OSError as e:
        return False, None, str(e)
    except Exception as e:
        return False, None, str(e)
    finally:
        sock.close()


def fetch_url(url, timeout=12):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{APP_NAME}/{VERSION} DNS list importer",
            "Accept": "text/plain,text/csv,application/json,text/html,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace")


# ---------------------------------------------------------------------------
# Windows system DNS integration
# ---------------------------------------------------------------------------
def get_network_interfaces():
    """Return a list of active network interface names (Windows)."""
    if not IS_WINDOWS:
        return []

    try:
        cmd = [
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | "
            "Select-Object -ExpandProperty Name"
        ]
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW
        )
        if r.returncode == 0:
            names = [line.strip() for line in r.stdout.splitlines() if line.strip()]
            if names:
                return names
    except Exception:
        pass

    try:
        cmd = ["netsh", "interface", "show", "interface"]
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            creationflags=CREATE_NO_WINDOW
        )
        names = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("-") or line.lower().startswith("admin"):
                continue
            parts = line.split()
            if len(parts) >= 4 and parts[0].lower() == "enabled" and parts[1].lower() == "connected":
                names.append(" ".join(parts[3:]))
        return names
    except Exception:
        return []


def get_current_dns(interface_name):
    """Return list of currently configured IPv4 DNS servers on interface."""
    if not IS_WINDOWS:
        return []
    try:
        cmd = [
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            f'(Get-DnsClientServerAddress -InterfaceAlias "{interface_name}" '
            f'-AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses -join ","'
        ]
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW
        )
        if r.returncode == 0:
            out = r.stdout.strip()
            return [s for s in out.split(",") if s.strip()]
    except Exception:
        pass
    return []


def set_system_dns(interface_name, servers):
    """Apply DNS servers to the given Windows interface."""
    if not IS_WINDOWS:
        return False, "This feature is only available on Windows."
    if not servers:
        return False, "No DNS servers provided."

    ipv4_servers = [s for s in servers if not is_ipv6(s)]
    if not ipv4_servers:
        return False, "Windows system DNS requires at least one IPv4 server."

    try:
        subprocess.run(
            ["netsh", "interface", "ipv4", "set", "dns",
             f"name={interface_name}", "dhcp"],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW
        )

        r = subprocess.run(
            ["netsh", "interface", "ipv4", "set", "dns",
             f"name={interface_name}", "static", ipv4_servers[0], "primary"],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW
        )
        if r.returncode != 0:
            return False, (r.stderr or r.stdout or "Failed to set primary DNS").strip()

        for i, srv in enumerate(ipv4_servers[1:], start=2):
            r = subprocess.run(
                ["netsh", "interface", "ipv4", "add", "dns",
                 f"name={interface_name}", srv, f"index={i}"],
                capture_output=True, text=True, timeout=15,
                creationflags=CREATE_NO_WINDOW
            )
            if r.returncode != 0:
                return False, (r.stderr or r.stdout or f"Failed to add DNS #{i}").strip()

        return True, "OK"
    except Exception as e:
        return False, str(e)


def reset_system_dns(interface_name):
    """Reset interface DNS to DHCP / automatic."""
    if not IS_WINDOWS:
        return False, "This feature is only available on Windows."
    try:
        r = subprocess.run(
            ["netsh", "interface", "ipv4", "set", "dns",
             f"name={interface_name}", "dhcp"],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW
        )
        if r.returncode != 0:
            return False, (r.stderr or r.stdout or "Failed to reset DNS").strip()
        return True, "OK"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class DNSEFApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} {VERSION}")
        self.root.geometry("1180x760")
        self.root.minsize(950, 620)

        self.language = "en"
        self.dark = True
        self.testing = False
        self._create_app_icon()
        self.stop_event = threading.Event()
        self.executor = None
        self.dns_data = {}  # ip -> dict
        self._dirty = False
        self._auto_save_job = None

        self.colors = {}
        self._sort_reverse = False
        self._sort_column = None

        self._setup_style()
        self._build_ui()

        # Load saved state if it exists; otherwise use defaults.
        loaded = self._load_state()
        if not loaded:
            self._load_defaults()

        # First render.
        self.refresh_tree()
        self._update_texts()

        # Auto-save on exit.
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
                "bg": "#15171a",
                "panel": "#1e2126",
                "panel2": "#252932",
                "fg": "#eeeeee",
                "muted": "#a7adb7",
                "accent": "#4ea1ff",
                "good": "#4fd18b",
                "bad": "#ff6b6b",
                "warn": "#ffc857",
                "border": "#343944",
                "select": "#294f77",
            }
        else:
            self.colors = {
                "bg": "#f4f5f7",
                "panel": "#ffffff",
                "panel2": "#e9ebef",
                "fg": "#1c1f24",
                "muted": "#5f6670",
                "accent": "#1769e0",
                "good": "#14804a",
                "bad": "#c62828",
                "warn": "#9a6700",
                "border": "#cbd0d8",
                "select": "#cfe1ff",
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
        self.style.configure("TNotebook", background=self.colors["bg"], borderwidth=0)
        self.style.configure(
            "TNotebook.Tab", background=self.colors["panel2"],
            foreground=self.colors["fg"], padding=(12, 7),
        )
        self.style.configure("TLabelframe", background=self.colors["panel"], foreground=self.colors["fg"])
        self.style.configure("TLabelframe.Label", background=self.colors["panel"], foreground=self.colors["fg"])
        self.style.configure("TCheckbutton", background=self.colors["panel"], foreground=self.colors["fg"])
        self.style.configure(
            "TCombobox", fieldbackground=self.colors["panel2"],
            foreground=self.colors["fg"], background=self.colors["panel2"],
        )
        self.style.configure("TScale", background=self.colors["panel"])

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
            text="Fast real DNS query tester — not ICMP ping.",
            style="Muted.TLabel",
        )
        self.desc_label.pack(anchor="w", pady=(0, 10))

        # Toolbar row 1
        toolbar = ttk.Frame(self.main)
        toolbar.pack(fill="x", pady=(0, 6))

        self.add_btn = ttk.Button(toolbar, command=self.add_dns)
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

        self.set_dns_btn = ttk.Button(
            toolbar2, command=self.set_as_system_dns, style="Success.TButton"
        )
        self.set_dns_btn.pack(side="left", padx=(0, 5))

        self.reset_dns_btn = ttk.Button(toolbar2, command=self.reset_system_dns_action)
        self.reset_dns_btn.pack(side="left", padx=5)

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

        self.domain_label = ttk.Label(options)
        self.domain_label.pack(side="left")

        self.domain_var = tk.StringVar(value="example.com")
        self.domain_entry = ttk.Entry(options, textvariable=self.domain_var, width=24)
        self.domain_entry.pack(side="left", padx=(6, 15))

        self.timeout_label = ttk.Label(options)
        self.timeout_label.pack(side="left")

        self.timeout_var = tk.DoubleVar(value=2.0)
        self.timeout_spin = tk.Spinbox(
            options, from_=0.5, to=10, increment=0.5,
            textvariable=self.timeout_var, width=7,
            bg=self.colors["panel2"], fg=self.colors["fg"],
            insertbackground=self.colors["fg"],
            buttonbackground=self.colors["panel2"], relief="flat",
        )
        self.timeout_spin.pack(side="left", padx=(6, 15))

        self.workers_label = ttk.Label(options)
        self.workers_label.pack(side="left")

        self.workers_var = tk.IntVar(value=25)
        self.workers_spin = tk.Spinbox(
            options, from_=1, to=100, increment=1,
            textvariable=self.workers_var, width=7,
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

        columns = ("dns", "type", "status", "latency", "success", "last_error")
        self.tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="extended"
        )
        self.tree.heading("dns", command=lambda: self.sort_column("dns"))
        self.tree.heading("type", command=lambda: self.sort_column("type"))
        self.tree.heading("status", command=lambda: self.sort_column("status"))
        self.tree.heading("latency", command=lambda: self.sort_column("latency"))
        self.tree.heading("success", command=lambda: self.sort_column("success"))
        self.tree.heading("last_error", command=lambda: self.sort_column("last_error"))

        self.tree.column("dns", width=200, anchor="w")
        self.tree.column("type", width=70, anchor="center")
        self.tree.column("status", width=120, anchor="center")
        self.tree.column("latency", width=120, anchor="center")
        self.tree.column("success", width=110, anchor="center")
        self.tree.column("last_error", width=400, anchor="w")

        self.tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.tag_configure("online", foreground=self.colors["good"])
        self.tree.tag_configure("offline", foreground=self.colors["bad"])
        self.tree.tag_configure("testing", foreground=self.colors["warn"])

        # Right-click context menu
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

    def _update_texts(self):
        fa = self.language == "fa"
        self.root.title(
            f"DNSEF — {'آزمایش سرعت و وضعیت DNS' if fa else 'DNS Speed & Availability Tester'}"
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
                "تست سریع واقعی DNS — بر اساس درخواست DNS، نه پینگ ICMP."
                if fa
                else "Fast real DNS query tester — not ICMP ping."
            )
        )

        self.add_btn.configure(text="افزودن DNS" if fa else "Add DNS")
        self.import_btn.configure(text="ایمپورت فایل" if fa else "Import File")
        self.url_btn.configure(text="ایمپورت از URL" if fa else "Import URL")
        self.sources_btn.configure(text="منابع پیش‌فرض" if fa else "Default Sources")
        self.test_btn.configure(text="تست همه" if fa else "Test All")
        self.stop_btn.configure(text="توقف" if fa else "Stop")
        self.set_dns_btn.configure(
            text="تنظیم به عنوان DNS سیستم" if fa else "Set as System DNS"
        )
        self.reset_dns_btn.configure(
            text="بازگردانی DNS سیستم" if fa else "Reset System DNS"
        )
        self.save_btn.configure(text="ذخیره" if fa else "Save")
        self.export_btn.configure(text="خروجی گرفتن" if fa else "Export")
        self.clear_results_btn.configure(
            text="پاک کردن نتایج" if fa else "Clear Results"
        )
        self.remove_failed_btn.configure(text="حذف ناموفق‌ها" if fa else "Remove Failed")
        self.clear_btn.configure(text="پاک کردن همه" if fa else "Clear All")

        self.domain_label.configure(text="دامنه تست:" if fa else "Test domain:")
        self.timeout_label.configure(text="مهلت (ثانیه):" if fa else "Timeout (s):")
        self.workers_label.configure(text="همزمان:" if fa else "Parallel:")
        self.only_failed_check.configure(text="فقط ناموفق‌ها" if fa else "Failed only")

        heads = {
            "dns": "DNS Server" if not fa else "سرور DNS",
            "type": "Type" if not fa else "نوع",
            "status": "Status" if not fa else "وضعیت",
            "latency": "DNS Query" if not fa else "زمان پاسخ DNS",
            "success": "Success" if not fa else "موفقیت",
            "last_error": "Last Error" if not fa else "آخرین خطا",
        }
        for col, text in heads.items():
            self.tree.heading(col, text=text)

        self._rebuild_context_menu()
        self._refresh_stats()
        self._update_admin_label()

    def _rebuild_context_menu(self):
        fa = self.language == "fa"
        self.context_menu.delete(0, "end")
        self.context_menu.add_command(
            label="Set as System DNS" if not fa else "تنظیم به عنوان DNS سیستم",
            command=self.set_as_system_dns,
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
        for ip in selection:
            self.dns_data.pop(ip, None)
        self.refresh_tree()
        self.mark_dirty()
        self.set_status(
            f"Removed {len(selection)} DNS servers."
            if self.language == "en"
            else f"{len(selection)} سرور DNS حذف شد."
        )

    # ---------- Data ----------
    def _load_defaults(self):
        for ip in DEFAULT_DNS:
            if ip not in self.dns_data:
                self.dns_data[ip] = self._blank_entry()

    @staticmethod
    def _blank_entry():
        return {
            "status": "Not tested",
            "latency": None,
            "success": None,
            "error": "",
        }

    def add_ip(self, ip, refresh=True):
        ip = ip.strip()
        if not is_valid_ip(ip):
            return False
        if ip not in self.dns_data:
            self.dns_data[ip] = self._blank_entry()
            self.mark_dirty()
            if refresh:
                self.refresh_tree()
        return True

    def refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        only_failed = self.only_failed_var.get()

        for ip, data in self.dns_data.items():
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
            type_text = "IPv6" if is_ipv6(ip) else "IPv4"

            tag = ""
            if status == "ONLINE":
                tag = "online"
            elif status == "OFFLINE":
                tag = "offline"
            elif status == "Testing":
                tag = "testing"

            self.tree.insert(
                "", "end", iid=ip,
                values=(ip, type_text, status_display, latency_text, success_text, error),
                tags=(tag,),
            )

        self._refresh_stats()

    def _refresh_stats(self):
        total = len(self.dns_data)
        online = sum(1 for d in self.dns_data.values() if d["status"] == "ONLINE")
        offline = sum(1 for d in self.dns_data.values() if d["status"] == "OFFLINE")
        tested = sum(
            1 for d in self.dns_data.values()
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
            title="Import DNS list",
            filetypes=[
                ("DNS lists", "*.txt *.csv *.json"),
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
            ips = extract_ips(text)
            added = 0
            for ip in ips:
                if ip not in self.dns_data:
                    self.add_ip(ip, refresh=False)
                    added += 1
            self.refresh_tree()
            self.mark_dirty()
            self.set_status(
                f"{added} DNS imported." if self.language == "en"
                else f"{added} DNS وارد شد."
            )
        except Exception as e:
            messagebox.showerror(
                "Error" if self.language == "en" else "خطا", str(e)
            )

    def import_url(self):
        self._url_dialog()

    def _url_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Import DNS from URL")
        win.geometry("680x480")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])

        label = ttk.Label(
            win,
            text=(
                "Paste a URL, then click Import."
                if self.language == "en"
                else "آدرس URL را وارد کنید و روی ایمپورت بزنید."
            ),
        )
        label.pack(anchor="w", padx=15, pady=(15, 8))

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
                    ips = extract_ips(text)
                    added = 0
                    for ip in ips:
                        if ip not in self.dns_data:
                            self.add_ip(ip, refresh=False)
                            added += 1
                    self.root.after(0, self.refresh_tree)
                    self.root.after(0, self.mark_dirty)
                    self.root.after(
                        0,
                        lambda: self.set_status(
                            f"Imported {added} DNS servers from URL."
                            if self.language == "en"
                            else f"{added} DNS از URL وارد شد."
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
        win.title("Default DNS Sources")
        win.geometry("920x460")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])

        ttk.Label(
            win,
            text=(
                "Select one or more public DNS sources:"
                if self.language == "en"
                else "یک یا چند منبع عمومی DNS را انتخاب کنید:"
            ),
        ).pack(anchor="w", padx=15, pady=(15, 8))

        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=15)

        vars_ = []
        for name, url in DEFAULT_SOURCES:
            v = tk.BooleanVar(value=True)
            vars_.append(v)
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=5)
            ttk.Checkbutton(row, variable=v).pack(side="left")
            ttk.Label(row, text=name, width=30).pack(side="left")
            e = ttk.Entry(row)
            e.insert(0, url)
            e.pack(side="left", fill="x", expand=True)

        def import_selected():
            selected = []
            for child, v in zip(frame.winfo_children(), vars_):
                if v.get():
                    entries = [w for w in child.winfo_children() if isinstance(w, ttk.Entry)]
                    if entries:
                        selected.append(entries[0].get().strip())

            if not selected:
                return

            def worker():
                total_added = 0
                errors = []
                for url in selected:
                    try:
                        text = fetch_url(url)
                        ips = extract_ips(text)
                        for ip in ips:
                            if ip not in self.dns_data:
                                self.add_ip(ip, refresh=False)
                                total_added += 1
                    except Exception as e:
                        errors.append(f"{url}: {e}")

                self.root.after(0, self.refresh_tree)
                self.root.after(0, self.mark_dirty)
                self.root.after(
                    0,
                    lambda: self.set_status(
                        f"Imported {total_added} DNS servers."
                        if self.language == "en"
                        else f"{total_added} DNS وارد شد."
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
    def add_dns(self):
        win = tk.Toplevel(self.root)
        win.title("Add DNS" if self.language == "en" else "افزودن DNS")
        win.geometry("560x420")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])

        ttk.Label(
            win,
            text=(
                "Enter one or more IPv4 / IPv6 addresses (one per line\n"
                "or separated by spaces, commas, or semicolons):"
                if self.language == "en"
                else "یک یا چند آدرس IPv4 / IPv6 وارد کنید (هر خط یکی\n"
                     "یا جدا شده با فاصله، ویرگول، یا نقطه‌ویرگول):"
            ),
        ).pack(anchor="w", padx=15, pady=(15, 8))

        text_frame = ttk.Frame(win)
        text_frame.pack(fill="both", expand=True, padx=15)

        text = tk.Text(
            text_frame, height=10, wrap="word",
            bg=self.colors["panel2"], fg=self.colors["fg"],
            insertbackground=self.colors["fg"], relief="flat",
        )
        text.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
        sb.pack(side="right", fill="y")
        text.configure(yscrollcommand=sb.set)

        hint = ttk.Label(
            win,
            text=(
                "Examples: 1.1.1.1, 8.8.8.8, 2606:4700:4700::1111"
                if self.language == "en"
                else "مثال: 1.1.1.1، 8.8.8.8، 2606:4700:4700::1111"
            ),
            style="Muted.TLabel",
        )
        hint.pack(anchor="w", padx=15, pady=(4, 0))

        def save():
            content = text.get("1.0", "end")
            ips = extract_ips(content)
            if not ips:
                messagebox.showerror(
                    "Invalid input" if self.language == "en" else "ورودی نامعتبر",
                    "No valid IPv4/IPv6 address was found."
                    if self.language == "en"
                    else "هیچ آدرس IPv4/IPv6 معتبری پیدا نشد.",
                    parent=win,
                )
                return

            added = 0
            for ip in ips:
                if ip not in self.dns_data:
                    self.dns_data[ip] = self._blank_entry()
                    added += 1
            self.refresh_tree()
            self.mark_dirty()
            self.set_status(
                f"Added {added} DNS servers."
                if self.language == "en"
                else f"{added} سرور DNS اضافه شد."
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
        failed = [ip for ip, d in self.dns_data.items() if d["status"] == "OFFLINE"]
        for ip in failed:
            del self.dns_data[ip]
        self.refresh_tree()
        self.mark_dirty()
        self.set_status(
            f"Removed {len(failed)} failed DNS servers."
            if self.language == "en"
            else f"{len(failed)} DNS ناموفق حذف شد."
        )

    def clear_all(self):
        if not self.dns_data:
            return
        ok = messagebox.askyesno(
            "Clear" if self.language == "en" else "پاک کردن",
            "Remove all DNS servers?"
            if self.language == "en"
            else "همه DNSها حذف شوند؟",
        )
        if ok:
            self.dns_data.clear()
            self.refresh_tree()
            self.mark_dirty()

    def clear_results(self):
        if not self.dns_data:
            return
        ok = messagebox.askyesno(
            "Clear results" if self.language == "en" else "پاک کردن نتایج",
            "Reset all test results? DNS servers are kept."
            if self.language == "en"
            else "همه نتایج تست پاک شوند؟ سرورهای DNS حفظ می‌شوند.",
        )
        if not ok:
            return
        for ip in self.dns_data:
            self.dns_data[ip] = self._blank_entry()
        self.refresh_tree()
        self.mark_dirty()
        self.set_status(
            "Test results cleared." if self.language == "en"
            else "نتایج تست پاک شد."
        )

    # ---------- Export ----------
    def export_results(self):
        if not self.dns_data:
            messagebox.showinfo(
                "No data" if self.language == "en" else "داده‌ای موجود نیست",
                "There is nothing to export."
                if self.language == "en"
                else "چیزی برای خروجی گرفتن وجود ندارد.",
            )
            return

        default_name = f"dnsef_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
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
            for ip, d in self.dns_data.items():
                rows.append({
                    "dns": ip,
                    "type": "IPv6" if is_ipv6(ip) else "IPv4",
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
                        "domain": self.domain_var.get(),
                        "results": rows,
                    }, f, indent=2, ensure_ascii=False)
            elif ext == ".txt":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"{APP_NAME} v{VERSION} Export - {datetime.now()}\n")
                    f.write(f"Domain: {self.domain_var.get()}\n")
                    f.write("=" * 80 + "\n")
                    f.write(f"{'DNS':<40}{'TYPE':<8}{'STATUS':<12}{'LATENCY':<14}{'SUCCESS':<10}ERROR\n")
                    f.write("-" * 80 + "\n")
                    for r in rows:
                        lat = f"{r['latency_ms']:.1f} ms" if r["latency_ms"] is not None else "—"
                        suc = f"{r['success_percent']:.0f}%" if r["success_percent"] is not None else "—"
                        f.write(
                            f"{r['dns']:<40}{r['type']:<8}{r['status']:<12}"
                            f"{lat:<14}{suc:<10}{r['error']}\n"
                        )
            else:  # csv
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(
                        f,
                        fieldnames=["dns", "type", "status", "latency_ms", "success_percent", "error"],
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
        """Mark state as changed and schedule an auto-save."""
        self._dirty = True
        if self._auto_save_job is not None:
            try:
                self.root.after_cancel(self._auto_save_job)
            except Exception:
                pass
        # Debounce: save 600 ms after the last change.
        self._auto_save_job = self.root.after(600, self._auto_save)

    def _auto_save(self):
        self._auto_save_job = None
        self.save_state(silent=True)

    def save_state(self, silent=False):
        """Write the DNS list + results to disk."""
        try:
            payload = {
                "app": APP_NAME,
                "version": VERSION,
                "saved_at": datetime.now().isoformat(),
                "domain": self.domain_var.get(),
                "timeout": self.timeout_var.get(),
                "workers": self.workers_var.get(),
                "language": self.language,
                "dark": self.dark,
                "dns": self.dns_data,
            }
            # Atomic write: write to temp then replace.
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
        """Load saved state. Returns True if a state file was loaded."""
        if not os.path.exists(STATE_FILE):
            return False
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return False

        try:
            dns = payload.get("dns") or {}
            for ip, d in dns.items():
                if not is_valid_ip(ip):
                    continue
                self.dns_data[ip] = {
                    "status": d.get("status", "Not tested"),
                    "latency": d.get("latency"),
                    "success": d.get("success"),
                    "error": d.get("error", ""),
                }
            if not self.dns_data:
                return False

            # Restore UI prefs if available.
            if payload.get("domain"):
                self.domain_var.set(payload["domain"])
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

    # ---------- System DNS ----------
    def set_as_system_dns(self):
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
                "Select one or two DNS servers from the list first."
                if self.language == "en"
                else "ابتدا یک یا دو سرور DNS از لیست انتخاب کنید.",
            )
            return

        ipv4_sel = [ip for ip in selection if not is_ipv6(ip)]
        if not ipv4_sel:
            messagebox.showwarning(
                "IPv4 required" if self.language == "en" else "نیاز به IPv4",
                "Windows system DNS configuration currently supports IPv4 only."
                if self.language == "en"
                else "تنظیم DNS سیستم ویندوز در حال حاضر فقط از IPv4 پشتیبانی می‌کند.",
            )
            return

        ipv4_sel = ipv4_sel[:2]

        win = tk.Toplevel(self.root)
        win.title("Set as System DNS" if self.language == "en" else "تنظیم به عنوان DNS سیستم")
        win.geometry("520x360")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])

        ttk.Label(
            win,
            text=(
                f"Selected DNS:  {', '.join(ipv4_sel)}"
                if self.language == "en"
                else f"DNS انتخابی:  {', '.join(ipv4_sel)}"
            ),
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=15, pady=(15, 8))

        if not is_admin():
            ttk.Label(
                win,
                text=(
                    "⚠ Administrator rights are required.\n"
                    "Run the script as administrator (see dnsef_admin.bat)."
                    if self.language == "en"
                    else "⚠ نیاز به دسترسی مدیر است.\n"
                         "اسکریپت را با دسترسی مدیر اجرا کنید (dnsef_admin.bat)."
                ),
                foreground=self.colors["warn"],
                justify="left",
            ).pack(anchor="w", padx=15, pady=(0, 10))

        ttk.Label(
            win,
            text="Network interface:" if self.language == "en" else "کارت شبکه:",
        ).pack(anchor="w", padx=15, pady=(4, 4))

        interfaces = get_network_interfaces()
        if not interfaces:
            ttk.Label(
                win,
                text="No active network interfaces found."
                if self.language == "en"
                else "هیچ کارت شبکه فعالی پیدا نشد.",
                foreground=self.colors["bad"],
            ).pack(anchor="w", padx=15)
            ttk.Button(
                win,
                text="Close" if self.language == "en" else "بستن",
                command=win.destroy,
            ).pack(pady=15)
            return

        iface_var = tk.StringVar(value=interfaces[0])
        combo = ttk.Combobox(win, textvariable=iface_var, values=interfaces, state="readonly")
        combo.pack(fill="x", padx=15)

        info = ttk.Label(win, text="", style="PanelMuted.TLabel", justify="left")
        info.pack(anchor="w", padx=15, pady=8)

        def refresh_info(*_):
            current = get_current_dns(iface_var.get())
            if current:
                info.configure(
                    text=(
                        f"Current DNS: {', '.join(current)}"
                        if self.language == "en"
                        else f"DNS فعلی: {', '.join(current)}"
                    ),
                )
            else:
                info.configure(
                    text="Current DNS: (automatic / DHCP)"
                    if self.language == "en"
                    else "DNS فعلی: (خودکار / DHCP)"
                )

        combo.bind("<<ComboboxSelected>>", refresh_info)
        refresh_info()

        def apply():
            iface = iface_var.get().strip()
            if not iface:
                return
            ok, msg = set_system_dns(iface, ipv4_sel)
            if ok:
                messagebox.showinfo(
                    "Success" if self.language == "en" else "موفق",
                    (
                        f"DNS set to {', '.join(ipv4_sel)} on {iface}."
                        if self.language == "en"
                        else f"DNS روی {iface} تنظیم شد: {', '.join(ipv4_sel)}"
                    ),
                    parent=win,
                )
                refresh_info()
            else:
                messagebox.showerror(
                    "Failed" if self.language == "en" else "ناموفق",
                    msg, parent=win,
                )

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=15, pady=15)

        ttk.Button(
            btns,
            text="Cancel" if self.language == "en" else "انصراف",
            command=win.destroy,
        ).pack(side="right", padx=(6, 0))

        ttk.Button(
            btns,
            text="Apply" if self.language == "en" else "اعمال",
            style="Accent.TButton",
            command=apply,
        ).pack(side="right")

    def reset_system_dns_action(self):
        if not IS_WINDOWS:
            messagebox.showinfo("Windows only", "This feature is only available on Windows.")
            return

        interfaces = get_network_interfaces()
        if not interfaces:
            messagebox.showinfo(
                "No interfaces" if self.language == "en" else "کارت شبکه‌ای یافت نشد",
                "No active network interfaces found."
                if self.language == "en"
                else "هیچ کارت شبکه فعالی پیدا نشد.",
            )
            return

        win = tk.Toplevel(self.root)
        win.title("Reset System DNS" if self.language == "en" else "بازگردانی DNS سیستم")
        win.geometry("520x260")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])

        ttk.Label(
            win,
            text=(
                "Reset DNS back to automatic (DHCP) for the selected interface:"
                if self.language == "en"
                else "بازگردانی DNS به حالت خودکار (DHCP) برای کارت شبکه انتخابی:"
            ),
            wraplength=480, justify="left",
        ).pack(anchor="w", padx=15, pady=(15, 8))

        iface_var = tk.StringVar(value=interfaces[0])
        ttk.Combobox(
            win, textvariable=iface_var, values=interfaces, state="readonly"
        ).pack(fill="x", padx=15)

        def do_reset():
            iface = iface_var.get().strip()
            if not iface:
                return
            ok, msg = reset_system_dns(iface)
            if ok:
                messagebox.showinfo(
                    "Success" if self.language == "en" else "موفق",
                    f"DNS reset to DHCP on {iface}."
                    if self.language == "en"
                    else f"DNS روی {iface} به حالت DHCP بازگردانده شد.",
                    parent=win,
                )
                win.destroy()
            else:
                messagebox.showerror(
                    "Failed" if self.language == "en" else "ناموفق",
                    msg, parent=win,
                )

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=15, pady=15)

        ttk.Button(
            btns,
            text="Cancel" if self.language == "en" else "انصراف",
            command=win.destroy,
        ).pack(side="right", padx=(6, 0))

        ttk.Button(
            btns,
            text="Reset" if self.language == "en" else "بازگردانی",
            style="Danger.TButton",
            command=do_reset,
        ).pack(side="right")

    # ---------- Testing ----------
    def start_test(self):
        if self.testing:
            return

        ips = list(self.dns_data.keys())
        if not ips:
            messagebox.showinfo(
                "No DNS" if self.language == "en" else "DNS وجود ندارد",
                "Add or import DNS servers first."
                if self.language == "en"
                else "ابتدا DNS اضافه یا ایمپورت کنید.",
            )
            return

        domain = self.domain_var.get().strip() or "example.com"

        try:
            timeout = max(0.5, float(self.timeout_var.get()))
            workers = max(1, min(100, int(self.workers_var.get())))
        except Exception:
            timeout = 2.0
            workers = 25

        self.testing = True
        self.stop_event.clear()
        self.progress["maximum"] = len(ips)
        self.progress["value"] = 0
        self.test_btn.configure(state="disabled")
        self.set_status("Testing..." if self.language == "en" else "در حال تست...")

        for ip in ips:
            self.dns_data[ip]["status"] = "Testing"
            self.dns_data[ip]["error"] = ""
        self.refresh_tree()

        def run():
            completed = 0
            msg = "Test completed." if self.language == "en" else "تست تمام شد."
            try:
                self.executor = ThreadPoolExecutor(max_workers=workers)
                futures = {
                    self.executor.submit(dns_query, ip, domain, timeout): ip
                    for ip in ips
                }

                for future in as_completed(futures):
                    if self.stop_event.is_set():
                        break

                    ip = futures[future]
                    try:
                        ok, latency, error = future.result()
                    except Exception as e:
                        ok, latency, error = False, None, str(e)

                    if ip in self.dns_data:
                        d = self.dns_data[ip]
                        if ok:
                            d["status"] = "ONLINE"
                            d["latency"] = latency
                            d["success"] = 100
                            d["error"] = ""
                        else:
                            d["status"] = "OFFLINE"
                            d["latency"] = latency
                            d["success"] = 0
                            d["error"] = error[:120]

                    completed += 1
                    self.root.after(0, self.refresh_tree)
                    self.root.after(
                        0,
                        lambda n=completed: self.progress.configure(value=n),
                    )

                if self.stop_event.is_set():
                    for ip, d in self.dns_data.items():
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
                # Persist results after every test.
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
        for ip, d in self.dns_data.items():
            if column == "dns":
                key = ip
            elif column == "type":
                key = "IPv6" if is_ipv6(ip) else "IPv4"
            elif column == "status":
                key = d["status"]
            elif column == "latency":
                key = d["latency"] if d["latency"] is not None else 999999
            elif column == "success":
                key = d["success"] if d["success"] is not None else -1
            else:
                key = d["error"]
            items.append((key, ip))

        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False

        items.sort(key=lambda x: x[0], reverse=self._sort_reverse)

        for index, (_, ip) in enumerate(items):
            if self.tree.exists(ip):
                self.tree.move(ip, "", index)

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
        # Final save before exit.
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
    app = DNSEFApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
# vpnef.py
# VPNEF 2.3 - تستر و اتصال VPN با پشتیبانی از TUN Mode و System Proxy
# فقط از ۴ فاصله استفاده می‌شود. هیچ Tab ای در این فایل نیست.

import csv
import ctypes
import json
import os
import socket
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from xray_helper import (
        download_xray, get_xray_path, XrayRunner, build_config,
        parse_subscription, parse_uri, merge_settings,
        wait_port, test_via_http,
        set_system_proxy, clear_system_proxy, get_system_proxy,
        read_log, clear_log, get_log_path, get_log_size_human,
        _xray_dir, DEFAULT_SETTINGS, cleanup_tun_routes,
    )
    from vpnconfig_sources import ALL_SOURCES, MIXED_SOURCES, PROTOCOL_SOURCES
except ImportError as e:
    print("FATAL: خطای import: " + str(e))
    print("مطمئن شوید xray_helper.py و vpnconfig_sources.py کنار این فایل هستند.")
    sys.exit(1)


APP_NAME = "VPNEF"
VERSION = "2.3.0"
SUPPORT_URL = "https://sajjadef.ir/support"
IS_WINDOWS = sys.platform == "win32"

DEFAULT_SOCKS_PORT = 10808
DEFAULT_HTTP_PORT = 10809
DEFAULT_TARGET = "http://cp.cloudflare.com/generate_204"


def _base_dir():
    """پوشه‌ی واقعی برنامه را برمی‌گرداند (حالت اسکریپت یا EXE)."""
    if getattr(sys, "frozen", False):
        # در حالت EXE، پوشه‌ای که فایل exe در آن است
        return os.path.dirname(os.path.abspath(sys.executable))
    # در حالت اسکریپت معمولی
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _base_dir()

def _state_path():
    base = BASE_DIR
    try:
        if os.access(base, os.W_OK):
            return os.path.join(base, "vpnef_state.json")
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "vpnef_state.json")


STATE_FILE = _state_path()


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



def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": APP_NAME + "/" + VERSION,
        "Accept": "text/plain,*/*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        cs = r.headers.get_content_charset() or "utf-8"
        return data.decode(cs, errors="replace")


def find_free_port(start=10808, end=11200):
    for p in range(start, end):
        try:
            s = socket.socket()
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            continue
    return start


class _TextVar:
    """شیء کمکی که مثل StringVar کار می‌کند اما از Text widget می‌خواند."""
    def __init__(self, text_widget):
        self.text = text_widget

    def get(self):
        return self.text.get("1.0", "end")

    def set(self, value):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)


class VPNEFApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME + " " + VERSION)
        self.root.geometry("1280x840")
        self.root.minsize(1020, 660)

        self.language = "fa"
        self.dark = True
        self.testing = False
        self._create_app_icon()
        self.stop_event = threading.Event()
        self.executor = None

        self.config_data = {}
        self.runner = None
        self.active_key = None
        self.socks_port = DEFAULT_SOCKS_PORT
        self.http_port = DEFAULT_HTTP_PORT
        self.sysproxy_on = False
        self.tun_active = False

        self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))

        self._dirty = False
        self._auto_save_job = None
        self.colors = {}
        self._sort_reverse = False
        self._sort_column = None

        self._setup_style()
        self._build_ui()

        if not self._load_state():
            self._load_defaults()

        self.refresh_tree()
        self._update_texts()
        self._update_banner()
        self._update_settings_indicator()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # ---------- آیکون برنامه ----------
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

	# ---------- تم ----------
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
                "bg": "#0f1115", "panel": "#181b21", "panel2": "#22262f",
                "fg": "#eaeaea", "muted": "#9aa3af", "accent": "#4ea1ff",
                "good": "#4fd18b", "bad": "#ff6b6b", "warn": "#ffc857",
                "border": "#2c313a", "select": "#294f77",
            }
        else:
            self.colors = {
                "bg": "#f3f4f6", "panel": "#ffffff", "panel2": "#e7e9ee",
                "fg": "#1b1f24", "muted": "#5a616b", "accent": "#1769e0",
                "good": "#15803d", "bad": "#b91c1c", "warn": "#a16207",
                "border": "#c9ced6", "select": "#cfe1ff",
            }
        self.root.configure(bg=self.colors["bg"])
        self.style.configure(".", background=self.colors["panel"],
                             foreground=self.colors["fg"],
                             fieldbackground=self.colors["panel2"],
                             bordercolor=self.colors["border"])
        self.style.configure("TFrame", background=self.colors["bg"])
        self.style.configure("TLabel", background=self.colors["bg"],
                             foreground=self.colors["fg"])
        self.style.configure("Title.TLabel", background=self.colors["bg"],
                             foreground=self.colors["fg"],
                             font=("Segoe UI", 18, "bold"))
        self.style.configure("Muted.TLabel", background=self.colors["bg"],
                             foreground=self.colors["muted"])
        self.style.configure("TButton", background=self.colors["panel2"],
                             foreground=self.colors["fg"], padding=(10, 6))
        self.style.map("TButton", background=[("active", self.colors["select"])])
        self.style.configure("Accent.TButton", background=self.colors["accent"],
                             foreground="#ffffff", padding=(12, 7),
                             font=("Segoe UI", 9, "bold"))
        self.style.map("Accent.TButton",
                       background=[("active", self.colors["accent"])])
        self.style.configure("Danger.TButton", background=self.colors["bad"],
                             foreground="#ffffff", padding=(10, 6),
                             font=("Segoe UI", 9, "bold"))
        self.style.map("Danger.TButton",
                       background=[("active", self.colors["bad"])])
        self.style.configure("Success.TButton", background=self.colors["good"],
                             foreground="#ffffff", padding=(10, 6),
                             font=("Segoe UI", 9, "bold"))
        self.style.map("Success.TButton",
                       background=[("active", self.colors["good"])])
        self.style.configure("Warn.TButton", background=self.colors["warn"],
                             foreground="#000000", padding=(10, 6),
                             font=("Segoe UI", 9, "bold"))
        self.style.map("Warn.TButton",
                       background=[("active", self.colors["warn"])])
        self.style.configure("TEntry", fieldbackground=self.colors["panel2"],
                             foreground=self.colors["fg"],
                             insertcolor=self.colors["fg"])
        self.style.configure("Treeview", background=self.colors["panel"],
                             fieldbackground=self.colors["panel"],
                             foreground=self.colors["fg"],
                             rowheight=28, bordercolor=self.colors["border"])
        self.style.map("Treeview",
                       background=[("selected", self.colors["select"])],
                       foreground=[("selected", self.colors["fg"])])
        self.style.configure("Treeview.Heading",
                             background=self.colors["panel2"],
                             foreground=self.colors["fg"],
                             relief="flat", padding=7)
        self.style.configure("TCheckbutton", background=self.colors["panel"],
                             foreground=self.colors["fg"])

    # ---------- UI ----------
    def _build_ui(self):
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=14, pady=12)
        self.main_frame = main

        # هدر
        top = ttk.Frame(main)
        top.pack(fill="x")
        ttk.Label(top, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="v" + VERSION, style="Muted.TLabel").pack(
            side="left", padx=8, pady=(7, 0))
        self.support_btn = ttk.Button(top, text="Support",
                                      command=self.open_support)
        self.support_btn.pack(side="right", padx=(6, 0))
        self.theme_btn = ttk.Button(top, text="☀", command=self.toggle_theme)
        self.theme_btn.pack(side="right", padx=(6, 0))
        self.lang_btn = ttk.Button(top, text="EN", command=self.toggle_language)
        self.lang_btn.pack(side="right")
        self.admin_label = ttk.Label(top, text="", style="Muted.TLabel")
        self.admin_label.pack(side="right", padx=(0, 12), pady=(7, 0))

        self.desc_label = ttk.Label(
            main,
            text="تست کانفیگ‌های رایگان VPN و اتصال از طریق Xray-core (System Proxy یا TUN).",
            style="Muted.TLabel")
        self.desc_label.pack(anchor="w", pady=(0, 8))

        # بنر وضعیت
        self.banner = tk.Frame(main, bg=self.colors["panel2"], height=44)
        self.banner.pack(fill="x", pady=(0, 8))
        self.banner.pack_propagate(False)
        self.banner_dot = tk.Label(self.banner, text="●",
                                   bg=self.colors["panel2"],
                                   fg=self.colors["muted"],
                                   font=("Segoe UI", 16))
        self.banner_dot.pack(side="left", padx=(12, 6))
        self.banner_text = tk.Label(self.banner, text="VPN: قطع",
                                    bg=self.colors["panel2"],
                                    fg=self.colors["fg"],
                                    font=("Segoe UI", 10, "bold"))
        self.banner_text.pack(side="left")
        self.banner_detail = tk.Label(self.banner, text="",
                                      bg=self.colors["panel2"],
                                      fg=self.colors["muted"],
                                      font=("Segoe UI", 9))
        self.banner_detail.pack(side="left", padx=(10, 0))
        self.disconnect_btn = ttk.Button(self.banner, text="قطع اتصال",
                                         command=self.disconnect_vpn)
        self.disconnect_btn.pack(side="right", padx=10, pady=6)

        # نوار تنظیمات
        self.settings_bar = tk.Frame(main, bg=self.colors["panel2"], height=28)
        self.settings_bar.pack(fill="x", pady=(0, 8))
        self.settings_bar.pack_propagate(False)
        self.settings_label = tk.Label(
            self.settings_bar, text="", bg=self.colors["panel2"],
            fg=self.colors["muted"], font=("Segoe UI", 8))
        self.settings_label.pack(side="left", padx=12)
        self.settings_btn = ttk.Button(self.settings_bar, text="⚙ تنظیمات",
                                       command=self.open_settings)
        self.settings_btn.pack(side="right", padx=6, pady=2)

        # ردیف ۱
        tb1 = ttk.Frame(main)
        tb1.pack(fill="x", pady=(0, 6))
        self.fetch_all_btn = ttk.Button(tb1, command=self.fetch_all_sources)
        self.fetch_all_btn.pack(side="left", padx=(0, 5))
        self.fetch_proto_btn = ttk.Button(tb1, command=self.fetch_by_protocol)
        self.fetch_proto_btn.pack(side="left", padx=5)
        self.import_btn = ttk.Button(tb1, command=self.import_file)
        self.import_btn.pack(side="left", padx=5)
        self.url_btn = ttk.Button(tb1, command=self.import_url)
        self.url_btn.pack(side="left", padx=5)
        self.add_btn = ttk.Button(tb1, command=self.add_manually)
        self.add_btn.pack(side="left", padx=5)
        self.sources_btn = ttk.Button(tb1, command=self.sources_dialog)
        self.sources_btn.pack(side="left", padx=5)

        # ردیف ۲
        tb2 = ttk.Frame(main)
        tb2.pack(fill="x", pady=(0, 6))
        self.download_core_btn = ttk.Button(tb2, command=self.download_core,
                                            style="Warn.TButton")
        self.download_core_btn.pack(side="left", padx=(0, 5))
        self.test_btn = ttk.Button(tb2, command=self.start_test,
                                   style="Accent.TButton")
        self.test_btn.pack(side="left", padx=(10, 5))
        self.stop_btn = ttk.Button(tb2, command=self.stop_test,
                                   style="Danger.TButton")
        self.stop_btn.pack(side="left", padx=5)
        self.connect_btn = ttk.Button(tb2, command=self.connect_selected,
                                      style="Success.TButton")
        self.connect_btn.pack(side="left", padx=(14, 5))

        # ردیف ۳
        tb3 = ttk.Frame(main)
        tb3.pack(fill="x", pady=(0, 10))
        self.sysproxy_btn = ttk.Button(tb3, command=self.apply_system_proxy)
        self.sysproxy_btn.pack(side="left", padx=(0, 5))
        self.sysproxy_off_btn = ttk.Button(tb3,
                                           command=self.disable_system_proxy)
        self.sysproxy_off_btn.pack(side="left", padx=5)
        self.save_btn = ttk.Button(tb3, command=self.save_state_manual)
        self.save_btn.pack(side="left", padx=5)
        self.export_btn = ttk.Button(tb3, command=self.export_results)
        self.export_btn.pack(side="left", padx=5)
        self.clear_results_btn = ttk.Button(tb3, command=self.clear_results)
        self.clear_results_btn.pack(side="left", padx=5)
        self.remove_failed_btn = ttk.Button(tb3, command=self.remove_failed)
        self.remove_failed_btn.pack(side="left", padx=5)
        self.clear_btn = ttk.Button(tb3, command=self.clear_all)
        self.clear_btn.pack(side="right")

        # گزینه‌ها
        opts = ttk.Frame(main)
        opts.pack(fill="x", pady=(0, 8))
        self.target_label = ttk.Label(opts)
        self.target_label.pack(side="left")
        self.target_var = tk.StringVar(value=DEFAULT_TARGET)
        ttk.Entry(opts, textvariable=self.target_var, width=32).pack(
            side="left", padx=(6, 15))
        self.timeout_label = ttk.Label(opts)
        self.timeout_label.pack(side="left")
        self.timeout_var = tk.DoubleVar(value=15.0)
        self.timeout_spin = tk.Spinbox(
            opts, from_=2, to=60, increment=1, textvariable=self.timeout_var,
            width=6, bg=self.colors["panel2"], fg=self.colors["fg"],
            insertbackground=self.colors["fg"],
            buttonbackground=self.colors["panel2"], relief="flat")
        self.timeout_spin.pack(side="left", padx=(6, 15))
        self.workers_label = ttk.Label(opts)
        self.workers_label.pack(side="left")
        self.workers_var = tk.IntVar(value=3)
        self.workers_spin = tk.Spinbox(
            opts, from_=1, to=20, increment=1, textvariable=self.workers_var,
            width=6, bg=self.colors["panel2"], fg=self.colors["fg"],
            insertbackground=self.colors["fg"],
            buttonbackground=self.colors["panel2"], relief="flat")
        self.workers_spin.pack(side="left", padx=(6, 15))

        # جدول
        table = ttk.Frame(main)
        table.pack(fill="both", expand=True)
        cols = ("name", "protocol", "server", "status", "latency",
                "success", "error")
        self.tree = ttk.Treeview(table, columns=cols, show="headings",
                                 selectmode="browse")
        for c in cols:
            self.tree.heading(c, command=lambda cc=c: self.sort_column(cc))
        self.tree.column("name", width=200, anchor="w")
        self.tree.column("protocol", width=90, anchor="center")
        self.tree.column("server", width=200, anchor="w")
        self.tree.column("status", width=100, anchor="center")
        self.tree.column("latency", width=100, anchor="center")
        self.tree.column("success", width=90, anchor="center")
        self.tree.column("error", width=340, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.tag_configure("online", foreground=self.colors["good"])
        self.tree.tag_configure("offline", foreground=self.colors["bad"])
        self.tree.tag_configure("testing", foreground=self.colors["warn"])
        self.tree.tag_configure("active", foreground=self.colors["accent"])

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<Double-1>", lambda e: self.connect_selected())

        # پایین
        bottom = ttk.Frame(main)
        bottom.pack(fill="x", pady=(9, 0))
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.stats_label = ttk.Label(bottom, text="", style="Muted.TLabel")
        self.stats_label.pack(side="right", padx=(12, 0))
        self.status_label = ttk.Label(main, text="", style="Muted.TLabel")
        self.status_label.pack(anchor="w", pady=(6, 0))

        self._update_admin_label()

    # ---------- متن‌ها ----------
    def _update_admin_label(self):
        if IS_WINDOWS:
            if is_admin():
                self.admin_label.configure(
                    text="مدیر" if self.language == "fa" else "Admin",
                    foreground=self.colors["good"])
            else:
                self.admin_label.configure(
                    text="بدون دسترسی مدیر" if self.language == "fa"
                    else "Non-admin",
                    foreground=self.colors["warn"])
        else:
            self.admin_label.configure(text="")

    def _update_texts(self):
        fa = (self.language == "fa")
        self.root.title("VPNEF — " + ("تستر و مدیریت پروکسی VPN" if fa
                                       else "VPN Tester & Proxy Manager"))
        self.support_btn.configure(text="پشتیبانی" if fa else "Support")
        self.theme_btn.configure(text="☀ روشن" if (fa and self.dark)
                                      else ("☾ تاریک" if fa
                                            else ("☀" if self.dark else "☾")))
        self.lang_btn.configure(text="EN" if fa else "FA")
        self.desc_label.configure(
            text="تست کانفیگ‌های رایگان VPN و اتصال از طریق Xray-core (System Proxy یا TUN)."
            if fa else
            "Test free VPN configs and connect via Xray-core (System Proxy or TUN).")

        self.fetch_all_btn.configure(text="دریافت همه منابع" if fa else "Fetch All")
        self.fetch_proto_btn.configure(
            text="دریافت بر اساس پروتکل" if fa else "By Protocol")
        self.import_btn.configure(text="ایمپورت فایل" if fa else "Import File")
        self.url_btn.configure(text="ایمپورت از URL" if fa else "Import URL")
        self.add_btn.configure(text="افزودن دستی" if fa else "Add Manually")
        self.sources_btn.configure(text="منابع پیش‌فرض" if fa else "Sources")
        self.download_core_btn.configure(
            text="دانلود هسته Xray" if fa else "Download Xray")
        self.test_btn.configure(text="تست همه" if fa else "Test All")
        self.stop_btn.configure(text="توقف" if fa else "Stop")
        self.connect_btn.configure(text="اتصال VPN" if fa else "Connect")
        self.sysproxy_btn.configure(
            text="فعال کردن پروکسی سیستم" if fa else "Enable Proxy")
        self.sysproxy_off_btn.configure(
            text="غیرفعال کردن پروکسی سیستم" if fa else "Disable Proxy")
        self.disconnect_btn.configure(text="قطع اتصال" if fa else "Disconnect")
        self.save_btn.configure(text="ذخیره" if fa else "Save")
        self.export_btn.configure(text="خروجی" if fa else "Export")
        self.clear_results_btn.configure(
            text="پاک کردن نتایج" if fa else "Clear Results")
        self.remove_failed_btn.configure(
            text="حذف ناموفق‌ها" if fa else "Remove Failed")
        self.clear_btn.configure(text="پاک کردن همه" if fa else "Clear All")
        self.settings_btn.configure(text="⚙ تنظیمات" if fa else "⚙ Settings")
        self.target_label.configure(text="آدرس تست:" if fa else "Target URL:")
        self.timeout_label.configure(
            text="مهلت (ثانیه):" if fa else "Timeout (s):")
        self.workers_label.configure(text="همزمان:" if fa else "Parallel:")

        heads = {
            "name": "نام" if fa else "Name",
            "protocol": "پروتکل" if fa else "Protocol",
            "server": "سرور" if fa else "Server",
            "status": "وضعیت" if fa else "Status",
            "latency": "زمان پاسخ" if fa else "Latency",
            "success": "موفقیت" if fa else "Success",
            "error": "خطا" if fa else "Error",
        }
        for c, t in heads.items():
            self.tree.heading(c, text=t)

        self._rebuild_context_menu()
        self._refresh_stats()
        self._update_admin_label()
        self._update_banner()
        self._update_settings_indicator()

    def _rebuild_context_menu(self):
        fa = (self.language == "fa")
        self.context_menu.delete(0, "end")
        self.context_menu.add_command(
            label="اتصال" if fa else "Connect",
            command=self.connect_selected)
        self.context_menu.add_command(
            label="تست انتخاب‌شده" if fa else "Test selected",
            command=self.test_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="نمایش کانفیگ Xray" if fa else "View Xray Config",
            command=self.view_selected_config)
        self.context_menu.add_command(
            label="کپی لینک کانفیگ" if fa else "Copy config URI",
            command=self.copy_selected)
        self.context_menu.add_command(
            label="کپی لاگ خطا" if fa else "Copy Error Log",
            command=self.copy_error_log)
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="حذف انتخاب‌شده" if fa else "Remove selected",
            command=self.remove_selected)

    def _show_context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _update_settings_indicator(self):
        s = self.settings
        parts = []
        if s.get("use_tun_mode"):
            parts.append("TUN✓")
        else:
            parts.append("Proxy")
        if s.get("bypass_private"):
            parts.append("Private✗")
        n = len(s.get("custom_direct_ips", []))
        if n:
            parts.append("DirectIP:" + str(n))
        n = len(s.get("custom_direct_domains", []))
        if n:
            parts.append("DirectDom:" + str(n))
        dns = ", ".join(s.get("dns_servers", [])[:2])
        parts.append("DNS:" + (dns or "—"))
        self.settings_label.configure(text="تنظیمات فعال: " + " | ".join(parts))

    # ---------- داده ----------
    def _load_defaults(self):
        pass

    @staticmethod
    def _blank_entry(parsed):
        return {
            "name": parsed.get("name", ""),
            "type": parsed.get("type", ""),
            "host": parsed.get("server", ""),
            "port": parsed.get("port", 0),
            "outbound": parsed["outbound"],
            "raw": parsed["raw"],
            "status": "Not tested",
            "latency": None,
            "success": None,
            "error": "",
        }

    def add_parsed(self, parsed, refresh=True):
        if not parsed:
            return False
        key = parsed["raw"]
        if key in self.config_data:
            return False
        self.config_data[key] = self._blank_entry(parsed)
        self.mark_dirty()
        if refresh:
            self.refresh_tree()
        return True

    def refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for key, data in self.config_data.items():
            status = data["status"]
            latency = data["latency"]
            success = data["success"]
            error = data["error"]
            if self.language == "fa":
                status_display = {
                    "Not tested": "تست نشده", "Testing": "در حال تست",
                    "ONLINE": "فعال", "OFFLINE": "قطع",
                }.get(status, status)
            else:
                status_display = status
            lat_text = ("%.0f ms" % latency) if latency is not None else "—"
            suc_text = ("%.0f%%" % success) if success is not None else "—"
            proto = (data.get("type") or "").upper()
            server = str(data.get("host", "")) + ":" + str(data.get("port", ""))
            name = (data.get("name", "") or "")[:40]
            tag = ""
            if key == self.active_key:
                tag = "active"
            elif status == "ONLINE":
                tag = "online"
            elif status == "OFFLINE":
                tag = "offline"
            elif status == "Testing":
                tag = "testing"
            self.tree.insert("", "end", iid=key,
                             values=(name, proto, server, status_display,
                                     lat_text, suc_text, error),
                             tags=(tag,))
        self._refresh_stats()

    def _refresh_stats(self):
        total = len(self.config_data)
        online = sum(1 for d in self.config_data.values()
                     if d["status"] == "ONLINE")
        offline = sum(1 for d in self.config_data.values()
                      if d["status"] == "OFFLINE")
        if self.language == "fa":
            self.stats_label.configure(
                text="کل: %d   فعال: %d   ناموفق: %d" %
                     (total, online, offline))
        else:
            self.stats_label.configure(
                text="Total: %d   Online: %d   Failed: %d" %
                     (total, online, offline))

    # ---------- دریافت ----------
    def fetch_all_sources(self):
        urls = [u for _, u in MIXED_SOURCES]
        self._fetch_async(urls, "همه منابع")

    def fetch_by_protocol(self):
        win = tk.Toplevel(self.root)
        win.title("دریافت بر اساس پروتکل" if self.language == "fa"
                  else "Fetch by Protocol")
        win.geometry("480x360")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])
        ttk.Label(win, text="پروتکل‌ها را انتخاب کنید:"
                  if self.language == "fa"
                  else "Select protocols:").pack(anchor="w", padx=15,
                                                 pady=(15, 10))
        vars_ = {}
        for proto in PROTOCOL_SOURCES.keys():
            v = tk.BooleanVar(value=(proto in ("vless", "vmess")))
            vars_[proto] = v
            ttk.Checkbutton(win, text=proto.upper(),
                            variable=v).pack(anchor="w", padx=20, pady=3)

        def go():
            urls = []
            for p, v in vars_.items():
                if v.get():
                    urls.extend(u for _, u in PROTOCOL_SOURCES[p])
            if not urls:
                return
            win.destroy()
            self._fetch_async(urls, "پروتکل‌های انتخابی")

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=15, pady=20)
        ttk.Button(btns, text="انصراف" if self.language == "fa" else "Cancel",
                   command=win.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="دریافت" if self.language == "fa" else "Fetch",
                   style="Accent.TButton", command=go).pack(side="right")

    def _fetch_async(self, urls, label=""):
        if not urls:
            return
        self.set_status("در حال دریافت %d منبع..." % len(urls)
                        if self.language == "fa"
                        else "Fetching %d source(s)..." % len(urls))

        def worker():
            total = 0
            errors = []
            for url in urls:
                try:
                    text = fetch_url(url)
                    parsed = parse_subscription(text)
                    for p in parsed:
                        if self.add_parsed(p, refresh=False):
                            total += 1
                except Exception as e:
                    errors.append(url[:60] + "...: " + str(e))
            self.root.after(0, self.refresh_tree)
            self.root.after(0, self.mark_dirty)
            self.root.after(0, lambda: self.set_status(
                "%d کانفیگ اضافه شد." % total if self.language == "fa"
                else "Added %d configs." % total))
            if errors:
                self.root.after(0, lambda: messagebox.showwarning(
                    "بعضی منابع ناموفق" if self.language == "fa"
                    else "Some sources failed",
                    "\n\n".join(errors[:4])))

        threading.Thread(target=worker, daemon=True).start()

    def import_file(self):
        path = filedialog.askopenfilename(
            title="Import config file",
            filetypes=[("همه", "*.txt *.json"), ("متنی", "*.txt"),
                       ("JSON", "*.json"), ("همه فایل‌ها", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig",
                      errors="replace") as f:
                text = f.read()
            parsed = parse_subscription(text)
            added = 0
            for p in parsed:
                if self.add_parsed(p, refresh=False):
                    added += 1
            self.refresh_tree()
            self.mark_dirty()
            self.set_status("%d کانفیگ وارد شد." % added
                            if self.language == "fa"
                            else "%d configs imported." % added)
        except Exception as e:
            messagebox.showerror("خطا" if self.language == "fa"
                                 else "Error", str(e))

    def import_url(self):
        win = tk.Toplevel(self.root)
        win.title("ایمپورت از URL" if self.language == "fa"
                  else "Import URL")
        win.geometry("600x180")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])
        ttk.Label(win, text="آدرس سابسکریپشن (Base64 یا متن ساده):"
                  if self.language == "fa"
                  else "Subscription URL (Base64 or plain):").pack(
                      anchor="w", padx=15, pady=(15, 8))
        var = tk.StringVar()
        e = ttk.Entry(win, textvariable=var)
        e.pack(fill="x", padx=15)

        def go():
            u = var.get().strip()
            if not u:
                return
            win.destroy()
            self._fetch_async([u], "URL")

        ttk.Button(win, text="ایمپورت" if self.language == "fa" else "Import",
                   style="Accent.TButton",
                   command=go).pack(side="right", padx=15, pady=15)
        e.focus_set()

    def add_manually(self):
        win = tk.Toplevel(self.root)
        win.title("افزودن دستی" if self.language == "fa" else "Add Manually")
        win.geometry("700x500")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])
        ttk.Label(win, text=(
            "یک یا چند لینک کانفیگ را وارد کنید\n"
            "(vless://, vmess://, trojan://, ss://)"
            if self.language == "fa" else
            "Paste one or more config URIs\n"
            "(vless://, vmess://, trojan://, ss://)"),
            justify="left").pack(anchor="w", padx=15, pady=(15, 8))
        tf = ttk.Frame(win)
        tf.pack(fill="both", expand=True, padx=15)
        text = tk.Text(tf, height=14, wrap="none",
                       bg=self.colors["panel2"], fg=self.colors["fg"],
                       insertbackground=self.colors["fg"], relief="flat")
        text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tf, orient="vertical", command=text.yview)
        sb.pack(side="right", fill="y")
        text.configure(yscrollcommand=sb.set)

        def save():
            content = text.get("1.0", "end")
            parsed = parse_subscription(content)
            added = 0
            for p in parsed:
                if self.add_parsed(p, refresh=False):
                    added += 1
            if added == 0:
                messagebox.showerror(
                    "کانفیگ معتبر نیست" if self.language == "fa"
                    else "No valid config",
                    "هیچ لینک معتبری پیدا نشد."
                    if self.language == "fa"
                    else "No valid config URI found.", parent=win)
                return
            self.refresh_tree()
            self.mark_dirty()
            self.set_status("%d کانفیگ اضافه شد." % added
                            if self.language == "fa"
                            else "Added %d configs." % added)
            win.destroy()

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=15, pady=15)
        ttk.Button(btns, text="انصراف" if self.language == "fa" else "Cancel",
                   command=win.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="افزودن" if self.language == "fa" else "Add",
                   style="Accent.TButton", command=save).pack(side="right")

    def sources_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("منابع پیش‌فرض" if self.language == "fa"
                  else "Default Sources")
        win.geometry("900x520")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])
        ttk.Label(win, text="منابع مورد نظر را انتخاب کنید:"
                  if self.language == "fa"
                  else "Select sources:").pack(anchor="w", padx=15,
                                               pady=(15, 8))
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=15)
        vars_ = []
        entries_ = []
        for name, url in ALL_SOURCES:
            v = tk.BooleanVar(value=False)
            vars_.append(v)
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=3)
            ttk.Checkbutton(row, variable=v).pack(side="left")
            ttk.Label(row, text=name, width=30).pack(side="left")
            e = ttk.Entry(row)
            e.insert(0, url)
            e.pack(side="left", fill="x", expand=True)
            entries_.append(e)

        def go():
            urls = [e.get().strip() for v, e in zip(vars_, entries_)
                    if v.get() and e.get().strip()]
            if not urls:
                return
            win.destroy()
            self._fetch_async(urls, "منابع انتخابی")

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=15, pady=15)
        ttk.Button(btns,
                   text="ایمپورت انتخاب‌شده" if self.language == "fa"
                   else "Import selected",
                   style="Accent.TButton", command=go).pack(side="right")

    # ---------- پنل تنظیمات ----------
    def open_settings(self):
        win = tk.Toplevel(self.root)
        fa = (self.language == "fa")
        win.title("تنظیمات پیشرفته" if fa else "Advanced Settings")
        win.geometry("820x680")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])

        temp = json.loads(json.dumps(self.settings))
        tvars = {}

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        tab_general = ttk.Frame(nb)
        nb.add(tab_general, text="عمومی" if fa else "General")
        self._settings_tab_general(tab_general, temp, tvars, fa)

        tab_tun = ttk.Frame(nb)
        nb.add(tab_tun, text="TUN Mode")
        self._settings_tab_tun(tab_tun, temp, tvars, fa)

        tab_routing = ttk.Frame(nb)
        nb.add(tab_routing, text="مسیریابی" if fa else "Routing")
        self._settings_tab_routing(tab_routing, temp, tvars, fa)

        tab_dns = ttk.Frame(nb)
        nb.add(tab_dns, text="DNS")
        self._settings_tab_dns(tab_dns, temp, tvars, fa)

        tab_adv = ttk.Frame(nb)
        nb.add(tab_adv, text="پیشرفته" if fa else "Advanced")
        self._settings_tab_advanced(tab_adv, temp, fa)

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=12, pady=(0, 12))

        def apply_and_close():
            for k, var in tvars.items():
                val = var.get()
                default_val = DEFAULT_SETTINGS.get(k)
                if isinstance(default_val, bool):
                    val = bool(val)
                elif isinstance(default_val, list):
                    if isinstance(val, str):
                        val = [line.strip() for line in val.splitlines()
                               if line.strip()]
                elif isinstance(default_val, (int, float)):
                    try:
                        val = type(default_val)(val)
                    except Exception:
                        val = default_val
                self.settings[k] = val
            self._update_settings_indicator()
            self.mark_dirty()
            self.set_status("تنظیمات ذخیره شد." if fa
                            else "Settings saved.")
            win.destroy()

        def reset_defaults():
            if not messagebox.askyesno(
                "بازنشانی" if fa else "Reset",
                "همه‌ی تنظیمات به حالت پیش‌فرض برگردند؟"
                if fa else "Reset all settings to defaults?", parent=win):
                return
            self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
            win.destroy()
            self.open_settings()
            self._update_settings_indicator()
            self.mark_dirty()

        ttk.Button(btns, text="بازنشانی" if fa else "Reset",
                   command=reset_defaults).pack(side="left")
        ttk.Button(btns, text="انصراف" if fa else "Cancel",
                   command=win.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="ذخیره" if fa else "Save",
                   style="Accent.TButton",
                   command=apply_and_close).pack(side="right")

    def _settings_tab_general(self, parent, temp, tvars, fa):
        pad = {"padx": 14, "pady": 8}
        row = ttk.Frame(parent)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="سطح لاگ:" if fa else "Log level:",
                  width=28).pack(side="left")
        v = tk.StringVar(value=temp.get("log_level", "warning"))
        ttk.Combobox(row, textvariable=v,
                     values=["none", "error", "warning", "info", "debug"],
                     state="readonly", width=15).pack(side="left")
        tvars["log_level"] = v

        ttk.Separator(parent).pack(fill="x", padx=14, pady=10)

        v = tk.BooleanVar(value=bool(temp.get("sniffing", True)))
        ttk.Checkbutton(parent, text="فعال‌سازی sniffing"
                        if fa else "Enable sniffing",
                        variable=v).pack(anchor="w", padx=14, pady=4)
        tvars["sniffing"] = v

        v = tk.BooleanVar(value=bool(temp.get("sniff_override", True)))
        ttk.Checkbutton(parent,
                        text="جایگزینی مقصد با دامنه‌ی sniff‌شده (override)"
                        if fa else "Override destination with sniffed domain",
                        variable=v).pack(anchor="w", padx=14, pady=4)
        tvars["sniff_override"] = v

        v = tk.BooleanVar(value=bool(temp.get("tcp_no_delay", True)))
        ttk.Checkbutton(parent, text="TCP No Delay"
                        if fa else "TCP No Delay",
                        variable=v).pack(anchor="w", padx=14, pady=4)
        tvars["tcp_no_delay"] = v

    def _settings_tab_tun(self, parent, temp, tvars, fa):
        pad = {"padx": 14, "pady": 8}

        warn = tk.Label(
            parent,
            text=("⚠ استفاده از TUN نیاز به دسترسی Administrator دارد.\n"
                  "در غیر این صورت Xray نمی‌تواند interface بسازد.")
            if fa else
            ("⚠ TUN mode requires Administrator privileges.\n"
             "Otherwise Xray cannot create the interface."),
            bg=self.colors["warn"], fg="#000000", justify="left",
            padx=10, pady=8)
        warn.pack(fill="x", padx=14, pady=(12, 8))

        v = tk.BooleanVar(value=bool(temp.get("use_tun_mode", False)))
        ttk.Checkbutton(parent,
                        text="استفاده از TUN Mode (تونل کامل کل سیستم)"
                        if fa else "Use TUN Mode (full system tunnel)",
                        variable=v).pack(anchor="w", padx=14, pady=8)
        tvars["use_tun_mode"] = v

        ttk.Label(parent, text=(
            "با فعال بودن TUN، تمام ترافیک سیستم (همه‌ی برنامه‌ها) "
            "از طریق VPN عبور می‌کند و نیازی به تنظیم پروکسی مرورگر نیست."
            if fa else
            "With TUN enabled, all system traffic (all apps) goes through "
            "the VPN; no browser proxy configuration needed."),
            foreground=self.colors["muted"], wraplength=700,
            justify="left").pack(anchor="w", padx=14, pady=(0, 10))

        row = ttk.Frame(parent)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="نام interface:", width=22).pack(side="left")
        e = ttk.Entry(row, width=20)
        e.insert(0, temp.get("tun_name", "vpn-tun"))
        e.pack(side="left")
        tvars["tun_name"] = e

        row = ttk.Frame(parent)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="MTU:", width=22).pack(side="left")
        e = ttk.Entry(row, width=10)
        e.insert(0, str(temp.get("tun_mtu", 1500)))
        e.pack(side="left")
        tvars["tun_mtu"] = e

        row = ttk.Frame(parent)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Gateway:", width=22).pack(side="left")
        e = ttk.Entry(row, width=20)
        e.insert(0, temp.get("tun_gateway", "10.0.0.1/16"))
        e.pack(side="left")
        tvars["tun_gateway"] = e

        lf = ttk.LabelFrame(parent,
                            text="DNS سرورهای TUN (هر خط یکی)"
                            if fa else "TUN DNS servers (one per line)")
        lf.pack(fill="x", padx=14, pady=6)
        txt = tk.Text(lf, height=3, bg=self.colors["panel2"],
                      fg=self.colors["fg"],
                      insertbackground=self.colors["fg"], relief="flat")
        txt.pack(fill="x", padx=6, pady=6)
        for item in temp.get("tun_dns", ["1.1.1.1", "8.8.8.8"]):
            txt.insert("end", item + "\n")
        tvars["tun_dns"] = _TextVar(txt)

        v = tk.BooleanVar(value=bool(temp.get("tun_auto_route", True)))
        ttk.Checkbutton(parent,
                        text="افزودن خودکار مسیر پیش‌فرض به جدول مسیریابی"
                        if fa else "Automatically add default route",
                        variable=v).pack(anchor="w", padx=14, pady=4)
        tvars["tun_auto_route"] = v

    def _settings_tab_routing(self, parent, temp, tvars, fa):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=14, pady=8)
        ttk.Label(row, text="استراتژی دامنه:" if fa else "Domain strategy:",
                  width=28).pack(side="left")
        v = tk.StringVar(value=temp.get("domain_strategy", "IPIfNonMatch"))
        ttk.Combobox(row, textvariable=v,
                     values=["AsIs", "IPIfNonMatch", "IPOnDemand"],
                     state="readonly", width=20).pack(side="left")
        tvars["domain_strategy"] = v

        v = tk.BooleanVar(value=bool(temp.get("bypass_private", True)))
        ttk.Checkbutton(parent, text="ترافیک IP های خصوصی مستقیم برود"
                        if fa else "Route private IPs directly",
                        variable=v).pack(anchor="w", padx=14, pady=4)
        tvars["bypass_private"] = v

        for label_fa, label_en, key in [
            ("IP / CIDR مستقیم (هر خط یکی)",
             "Direct IP / CIDR (one per line)", "custom_direct_ips"),
            ("دامنه‌های مستقیم (هر خط یکی)",
             "Direct domains (one per line)", "custom_direct_domains"),
            ("IP / CIDR مسدود (هر خط یکی)",
             "Blocked IP / CIDR (one per line)", "custom_block_ips"),
            ("دامنه‌های مسدود (هر خط یکی)",
             "Blocked domains (one per line)", "custom_block_domains"),
        ]:
            lf = ttk.LabelFrame(parent, text=label_fa if fa else label_en)
            lf.pack(fill="x", padx=14, pady=5)
            txt = tk.Text(lf, height=3, bg=self.colors["panel2"],
                          fg=self.colors["fg"],
                          insertbackground=self.colors["fg"], relief="flat")
            txt.pack(fill="x", padx=6, pady=6)
            for item in temp.get(key, []):
                txt.insert("end", item + "\n")
            tvars[key] = _TextVar(txt)

    def _settings_tab_dns(self, parent, temp, tvars, fa):
        lf = ttk.LabelFrame(parent, text="سرورهای DNS (هر خط یکی)"
                            if fa else "DNS servers (one per line)")
        lf.pack(fill="both", expand=True, padx=14, pady=10)
        txt = tk.Text(lf, height=8, bg=self.colors["panel2"],
                      fg=self.colors["fg"],
                      insertbackground=self.colors["fg"], relief="flat")
        txt.pack(fill="both", expand=True, padx=6, pady=6)
        for s in temp.get("dns_servers", ["1.1.1.1", "8.8.8.8"]):
            txt.insert("end", s + "\n")
        tvars["dns_servers"] = _TextVar(txt)

        row = ttk.Frame(parent)
        row.pack(fill="x", padx=14, pady=8)
        ttk.Label(row,
                  text="استراتژی کوئری DNS:" if fa else "DNS query strategy:",
                  width=28).pack(side="left")
        v = tk.StringVar(value=temp.get("dns_query_strategy", "UseIP"))
        ttk.Combobox(row, textvariable=v,
                     values=["UseIP", "UseIPv4", "UseIPv6"],
                     state="readonly", width=15).pack(side="left")
        tvars["dns_query_strategy"] = v

        v = tk.BooleanVar(value=bool(temp.get("dns_disable_cache", False)))
        ttk.Checkbutton(parent, text="غیرفعال کردن کش DNS"
                        if fa else "Disable DNS cache",
                        variable=v).pack(anchor="w", padx=14, pady=4)
        tvars["dns_disable_cache"] = v

    def _settings_tab_advanced(self, parent, temp, fa):
        lf = ttk.LabelFrame(parent, text="مسیرها" if fa else "Paths")
        lf.pack(fill="x", padx=14, pady=10)
        for label_fa, label_en, value in [
            ("پوشه Xray:", "Xray folder:", _xray_dir()),
            ("فایل لاگ:", "Log file:", get_log_path()),
        ]:
            row = ttk.Frame(lf)
            row.pack(fill="x", padx=8, pady=4)
            ttk.Label(row, text=label_fa if fa else label_en,
                      width=15).pack(side="left")
            e = ttk.Entry(row)
            e.insert(0, value)
            e.configure(state="readonly")
            e.pack(side="left", fill="x", expand=True)

        row = ttk.Frame(lf)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="اندازه لاگ:" if fa else "Log size:",
                  width=15).pack(side="left")
        size_lbl = ttk.Label(row, text=get_log_size_human())
        size_lbl.pack(side="left")

        btns = ttk.Frame(parent)
        btns.pack(fill="x", padx=14, pady=10)

        def view_log():
            self.show_text_dialog("لاگ Xray" if fa else "Xray Log",
                                  read_log(), width=900, height=600)

        def clear_log_now():
            if messagebox.askyesno(
                    "پاک کردن لاگ" if fa else "Clear log",
                    "محتوای فایل لاگ پاک شود؟" if fa
                    else "Clear log file?", parent=parent):
                clear_log()
                size_lbl.configure(text=get_log_size_human())
                self.set_status("لاگ پاک شد." if fa else "Log cleared.")

        def open_log_folder():
            try:
                if IS_WINDOWS:
                    os.startfile(_xray_dir())
                elif sys.platform == "darwin":
                    import subprocess as sp
                    sp.Popen(["open", _xray_dir()])
                else:
                    import subprocess as sp
                    sp.Popen(["xdg-open", _xray_dir()])
            except Exception as e:
                messagebox.showerror("خطا" if fa else "Error", str(e))

        def preview_config():
            sample = {
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": "example.com", "port": 443,
                        "users": [{
                            "id": "00000000-0000-0000-0000-000000000000",
                            "encryption": "none"}]}]},
                "streamSettings": {
                    "network": "tcp", "security": "tls",
                    "tlsSettings": {"serverName": "example.com"}},
            }
            cfg = build_config(sample, settings=self.settings)
            self.show_text_dialog(
                "پیش‌نمایش کانفیگ Xray" if fa else "Xray Config Preview",
                json.dumps(cfg, indent=2, ensure_ascii=False),
                width=800, height=600)

        def cleanup_tun():
            cleanup_tun_routes(self.settings.get("tun_name", "vpn-tun"))
            self.set_status("مسیرهای TUN پاک شد." if fa
                            else "TUN routes cleaned.")

        ttk.Button(btns, text="نمایش لاگ" if fa else "View Log",
                   command=view_log).pack(side="left", padx=3)
        ttk.Button(btns, text="پاک کردن لاگ" if fa else "Clear Log",
                   command=clear_log_now).pack(side="left", padx=3)
        ttk.Button(btns, text="باز کردن پوشه" if fa else "Open Folder",
                   command=open_log_folder).pack(side="left", padx=3)
        ttk.Button(btns,
                   text="پیش‌نمایش کانفیگ" if fa else "Preview Config",
                   style="Accent.TButton",
                   command=preview_config).pack(side="left", padx=3)
        ttk.Button(btns, text="پاک‌سازی TUN" if fa else "Cleanup TUN",
                   command=cleanup_tun).pack(side="left", padx=3)

    # ---------- نمایش متن ----------
    def show_text_dialog(self, title, content, width=800, height=600):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("%dx%d" % (width, height))
        win.transient(self.root)
        win.configure(bg=self.colors["bg"])
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        txt = tk.Text(frame, wrap="none", bg=self.colors["panel2"],
                      fg=self.colors["fg"],
                      insertbackground=self.colors["fg"], relief="flat")
        txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        sb.pack(side="right", fill="y")
        txt.configure(yscrollcommand=sb.set)
        txt.insert("1.0", content)
        txt.configure(state="disabled")
        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        def copy_all():
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.set_status("کپی شد." if self.language == "fa"
                            else "Copied.")

        ttk.Button(btns, text="کپی" if self.language == "fa" else "Copy",
                   command=copy_all).pack(side="left")
        ttk.Button(btns, text="بستن" if self.language == "fa" else "Close",
                   command=win.destroy).pack(side="right")

    # ---------- دانلود هسته ----------
    def download_core(self):
        existing = get_xray_path()
        if existing:
            ok = messagebox.askyesno(
                "دانلود مجدد؟" if self.language == "fa" else "Re-download?",
                "هسته Xray نصب است. مجدداً دانلود شود؟"
                if self.language == "fa"
                else "Xray is installed. Re-download?")
            if not ok:
                return
        win = tk.Toplevel(self.root)
        win.title("Downloading Xray...")
        win.geometry("460x140")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])
        win.resizable(False, False)
        lbl = ttk.Label(win,
                        text="شروع..." if self.language == "fa"
                        else "Starting...")
        lbl.pack(pady=(20, 10))
        pb = ttk.Progressbar(win, mode="determinate", maximum=100)
        pb.pack(fill="x", padx=20)

        def progress(pct, msg):
            self.root.after(0, lambda: (pb.configure(value=pct),
                                        lbl.configure(text=msg)))

        def worker():
            ok, msg = download_xray(progress_cb=progress)

            def done():
                win.destroy()
                if ok:
                    messagebox.showinfo(
                        "تمام" if self.language == "fa" else "Done",
                        msg, parent=self.root)
                    self.set_status(msg)
                else:
                    messagebox.showerror(
                        "ناموفق" if self.language == "fa" else "Failed",
                        msg, parent=self.root)
            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- تست ----------
    def start_test(self):
        if self.testing:
            return
        keys = list(self.config_data.keys())
        if not keys:
            messagebox.showinfo(
                "بدون کانفیگ" if self.language == "fa" else "No configs",
                "ابتدا کانفیگ دریافت یا ایمپورت کنید."
                if self.language == "fa" else
                "Fetch or import configs first.")
            return
        if not get_xray_path():
            messagebox.showwarning(
                "هسته موجود نیست" if self.language == "fa"
                else "Core missing",
                "ابتدا هسته Xray را دانلود کنید."
                if self.language == "fa" else
                "Download Xray core first.")
            return
        try:
            timeout = max(3.0, float(self.timeout_var.get()))
            workers = max(1, min(8, int(self.workers_var.get())))
        except Exception:
            timeout = 15.0
            workers = 3

        # ✅ پاک کردن رویداد توقف قبل از شروع تست جدید
        self.stop_event.clear()

        self.testing = True
        self.progress["maximum"] = len(keys)
        self.progress["value"] = 0
        self.test_btn.configure(state="disabled")
        self.set_status("در حال تست..." if self.language == "fa"
                        else "Testing...")

        for k in keys:
            self.config_data[k]["status"] = "Testing"
            self.config_data[k]["error"] = ""
        self.refresh_tree()

        def run():
            completed = 0
            msg = "تست تمام شد." if self.language == "fa" else "Test completed."
            try:
                self.executor = ThreadPoolExecutor(max_workers=workers)
                futures = {
                    self.executor.submit(self._test_one_config, k, timeout): k
                    for k in keys}
                for future in as_completed(futures):
                    if self.stop_event.is_set():
                        break
                    k = futures[future]
                    try:
                        ok, latency, error = future.result()
                    except Exception as e:
                        ok, latency, error = False, None, str(e)[:140]
                    if k in self.config_data:
                        d = self.config_data[k]
                        if ok:
                            d["status"] = "ONLINE"
                            d["latency"] = latency
                            d["success"] = 100
                            d["error"] = ""
                        else:
                            d["status"] = "OFFLINE"
                            d["latency"] = None
                            d["success"] = 0
                            d["error"] = (error or "")[:140]
                    completed += 1
                    self.root.after(0, self.refresh_tree)
                    self.root.after(
                        0,
                        lambda n=completed:
                        self.progress.configure(value=n))
                if self.stop_event.is_set():
                    for k, d in self.config_data.items():
                        if d["status"] == "Testing":
                            d["status"] = "Not tested"
                    msg = ("تست متوقف شد." if self.language == "fa"
                           else "Test stopped.")
            finally:
                if self.executor:
                    self.executor.shutdown(wait=False, cancel_futures=True)
                    self.executor = None
                self.testing = False
                self.root.after(0, self.refresh_tree)
                self.root.after(
                    0, lambda: self.test_btn.configure(state="normal"))
                self.root.after(0, lambda: self.set_status(msg))
                self.root.after(0, self.mark_dirty)

        threading.Thread(target=run, daemon=True).start()

    def _test_one_config(self, key, timeout):
        if self.stop_event.is_set():
            return False, None, "stopped"
        entry = self.config_data.get(key)
        if not entry:
            return False, None, "entry missing"
        try:
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            test_socks = s.getsockname()[1]
            s.close()
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            test_http = s.getsockname()[1]
            s.close()
        except Exception as e:
            return False, None, "port pick failed: " + str(e)

        # تست همیشه در حالت Proxy (نه TUN) انجام می‌شود تا سریع‌تر باشد
        test_settings = json.loads(json.dumps(self.settings))
        test_settings["use_tun_mode"] = False
        cfg = build_config(entry["outbound"],
                           socks_port=test_socks,
                           http_port=test_http,
                           settings=test_settings)
        runner = XrayRunner()
        ok, msg = runner.start(cfg)
        if not ok:
            try:
                runner.cleanup()
            except Exception:
                pass
            return False, None, "Xray: " + (msg or "")[:200]

        success = False
        try:
            if not wait_port("127.0.0.1", test_http,
                             timeout=min(5.0, timeout)):
                return False, None, "Xray did not open proxy port in time"
            target = self.target_var.get().strip() or DEFAULT_TARGET
            ok2, latency, err = test_via_http(test_http, target,
                                              timeout=timeout)
            if ok2:
                success = True
                return True, latency, ""
            else:
                return False, None, err or "connectivity test failed"
        finally:
            try:
                runner.stop()
            except Exception:
                pass
            try:
                runner.finalize_after_test(success)
            except Exception:
                pass
            try:
                runner.cleanup()
            except Exception:
                pass

    def test_selected(self):
        """تست یک کانفیگ انتخاب‌شده (بدون دخالت stop_event)."""
        sel = self.tree.selection()
        if not sel:
            return
        key = sel[0]
        if not get_xray_path():
            messagebox.showwarning(
                "هسته موجود نیست" if self.language == "fa"
                else "Core missing",
                "ابتدا هسته Xray را دانلود کنید."
                if self.language == "fa" else
                "Download Xray core first.")
            return

        # ✅ مهم: پاک کردن رویداد توقف قبل از تست جدید
        self.stop_event.clear()

        self.config_data[key]["status"] = "Testing"
        self.refresh_tree()
        self.set_status("در حال تست..." if self.language == "fa"
                        else "Testing...")

        def worker():
            try:
                timeout = max(3.0, float(self.timeout_var.get()))
            except Exception:
                timeout = 15.0
            ok, latency, err = self._test_one_config(key, timeout)

            def done():
                d = self.config_data.get(key)
                if d:
                    if ok:
                        d["status"] = "ONLINE"
                        d["latency"] = latency
                        d["success"] = 100
                        d["error"] = ""
                    else:
                        d["status"] = "OFFLINE"
                        d["latency"] = None
                        d["success"] = 0
                        d["error"] = (err or "")[:140]
                self.refresh_tree()
                self.mark_dirty()
                self.set_status(
                    "تست تمام شد." if self.language == "fa"
                    else "Test completed.")
            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def stop_test(self):
        if not self.testing:
            return
        self.stop_event.set()
        self.set_status("در حال توقف..." if self.language == "fa"
                        else "Stopping...")

    # ---------- اتصال / قطع ----------
    def connect_selected(self):
        # ✅ پاک کردن رویداد توقف قبل از اتصال جدید
        self.stop_event.clear()

        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning(
                "انتخابی وجود ندارد" if self.language == "fa"
                else "No selection",
                "ابتدا یک کانفیگ از لیست انتخاب کنید."
                if self.language == "fa" else
                "Select a config first.")
            return
        key = sel[0]
        entry = self.config_data.get(key)
        if not entry:
            return
        if not get_xray_path():
            messagebox.showwarning(
                "هسته موجود نیست" if self.language == "fa"
                else "Core missing",
                "ابتدا هسته Xray را دانلود کنید."
                if self.language == "fa" else
                "Download Xray core first.")
            return

        use_tun = bool(self.settings.get("use_tun_mode", False))
        if use_tun and IS_WINDOWS and not is_admin():
            ok = messagebox.askyesno(
                "نیاز به دسترسی مدیر" if self.language == "fa"
                else "Admin required",
                "TUN mode نیاز به دسترسی Administrator دارد.\n"
                "آیا می‌خواهید با دسترسی محدود (System Proxy) ادامه دهید؟"
                if self.language == "fa" else
                "TUN mode requires Administrator privileges.\n"
                "Continue with System Proxy mode instead?")
            if ok:
                use_tun = False
                self.settings["use_tun_mode"] = False
            else:
                return

        # قطع اتصال قبلی
        if self.runner and self.runner.is_running():
            self.runner.stop()
            self.runner.cleanup()
            self.runner = None

        self.socks_port = find_free_port(DEFAULT_SOCKS_PORT,
                                         DEFAULT_SOCKS_PORT + 200)
        self.http_port = self.socks_port + 1

        cfg = build_config(entry["outbound"],
                           socks_port=self.socks_port,
                           http_port=self.http_port,
                           settings=self.settings)

        win = tk.Toplevel(self.root)
        win.title("در حال اتصال..." if self.language == "fa"
                  else "Connecting...")
        win.geometry("420x120")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.colors["bg"])
        win.resizable(False, False)
        ttk.Label(win, text="در حال اجرای Xray..."
                  if self.language == "fa"
                  else "Starting Xray...").pack(pady=30)

        def worker():
            runner = XrayRunner()
            ok, msg = runner.start(cfg)
            if ok and not use_tun:
                if not wait_port("127.0.0.1", self.http_port, timeout=6.0):
                    runner.stop()
                    runner.cleanup()
                    ok, msg = False, (
                        "پورت پروکسی باز نشد" if self.language == "fa"
                        else "Proxy port did not open")
            if ok and use_tun:
                time.sleep(2.5)

            def done():
                win.destroy()
                if ok:
                    self.runner = runner
                    self.active_key = key
                    self.tun_active = use_tun
                    self._update_banner(connected_key=key)
                    self.refresh_tree()
                    if use_tun:
                        self.set_status("متصل شد (TUN)."
                                        if self.language == "fa"
                                        else "Connected (TUN).")
                    else:
                        self.set_status("متصل شد (پروکسی)."
                                        if self.language == "fa"
                                        else "Connected (Proxy).")
                        if IS_WINDOWS:
                            self.apply_system_proxy(silent=True)
                else:
                    try:
                        runner.cleanup()
                    except Exception:
                        pass
                    messagebox.showerror(
                        "اتصال ناموفق" if self.language == "fa"
                        else "Connection failed",
                        msg, parent=self.root)
            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def disconnect_vpn(self):
        if self.runner:
            try:
                self.runner.stop()
                self.runner.cleanup()
            except Exception:
                pass
            self.runner = None
        self.active_key = None
        if IS_WINDOWS and self.sysproxy_on:
            clear_system_proxy()
            self.sysproxy_on = False
        if self.tun_active:
            cleanup_tun_routes(self.settings.get("tun_name", "vpn-tun"))
            self.tun_active = False
        self._update_banner()
        self.refresh_tree()
        self.set_status("قطع شد." if self.language == "fa"
                        else "Disconnected.")

    def _update_banner(self, connected_key=None):
        if connected_key is None:
            connected_key = self.active_key
        if connected_key and self.runner and self.runner.is_running():
            entry = self.config_data.get(connected_key, {})
            name = entry.get("name", "?")
            proto = (entry.get("type") or "").upper()
            mode_str = "TUN" if self.tun_active else "Proxy"
            self.banner_dot.configure(fg=self.colors["good"])
            self.banner_text.configure(
                text="VPN: متصل (%s)" % mode_str
                if self.language == "fa"
                else "VPN: Connected (%s)" % mode_str)
            pid = self.runner.proc.pid if self.runner.proc else "-"
            if self.tun_active:
                detail = "%s  •  %s  •  PID %s" % (name, proto, pid)
            else:
                detail = "%s  •  %s  •  PID %s  •  HTTP:%d" % (
                    name, proto, pid, self.http_port)
            self.banner_detail.configure(text=detail)
        else:
            self.banner_dot.configure(fg=self.colors["muted"])
            self.banner_text.configure(
                text="VPN: قطع" if self.language == "fa"
                else "VPN: Disconnected")
            self.banner_detail.configure(text="")

    # ---------- پروکسی سیستم ----------
    def apply_system_proxy(self, silent=False):
        if not IS_WINDOWS:
            if not silent:
                messagebox.showinfo("فقط ویندوز",
                                    "این ویژگی فقط در ویندوز کار می‌کند.")
            return
        if not self.runner or not self.runner.is_running():
            if not silent:
                messagebox.showwarning(
                    "اتصال فعال نیست" if self.language == "fa"
                    else "Not connected",
                    "ابتدا یک کانفیگ را متصل کنید."
                    if self.language == "fa"
                    else "Connect to a config first.")
            return
        server = ("http=127.0.0.1:%d;https=127.0.0.1:%d"
                  % (self.http_port, self.http_port))
        ok, msg = set_system_proxy(server)
        if ok:
            self.sysproxy_on = True
            if not silent:
                messagebox.showinfo(
                    "موفق" if self.language == "fa" else "Success",
                    "پروکسی سیستم فعال شد:\n" + server +
                    "\n\nاگر IP تغییر نکرد، مرورگر را کامل ببندید و "
                    "دوباره باز کنید."
                    if self.language == "fa" else
                    "System proxy enabled:\n" + server +
                    "\n\nIf IP doesn't change, fully close and reopen "
                    "your browser.")
            self.set_status("پروکسی سیستم فعال شد."
                            if self.language == "fa"
                            else "System proxy enabled.")
        else:
            if not silent:
                messagebox.showerror(
                    "ناموفق" if self.language == "fa" else "Failed", msg)

    def disable_system_proxy(self):
        if not IS_WINDOWS:
            return
        ok, msg = clear_system_proxy()
        if ok:
            self.sysproxy_on = False
            self.set_status("پروکسی سیستم غیرفعال شد."
                            if self.language == "fa"
                            else "System proxy disabled.")
            messagebox.showinfo(
                "موفق" if self.language == "fa" else "Success",
                "پروکسی سیستم غیرفعال شد.\nاتصال اینترنت اکنون مستقیم است."
                if self.language == "fa" else
                "System proxy disabled.\nInternet is now direct.")
        else:
            messagebox.showerror(
                "ناموفق" if self.language == "fa" else "Failed", msg)

    # ---------- حذف و پاک‌سازی ----------
    def remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        for k in sel:
            self.config_data.pop(k, None)
            if k == self.active_key:
                self.disconnect_vpn()
        self.refresh_tree()
        self.mark_dirty()

    def remove_failed(self):
        failed = [k for k, d in self.config_data.items()
                  if d["status"] == "OFFLINE"]
        for k in failed:
            self.config_data.pop(k, None)
        self.refresh_tree()
        self.mark_dirty()
        self.set_status("%d کانفیگ ناموفق حذف شد." % len(failed)
                        if self.language == "fa"
                        else "Removed %d failed configs." % len(failed))

    def clear_results(self):
        for k in self.config_data:
            self.config_data[k]["status"] = "Not tested"
            self.config_data[k]["latency"] = None
            self.config_data[k]["success"] = None
            self.config_data[k]["error"] = ""
        self.refresh_tree()
        self.mark_dirty()

    def clear_all(self):
        if not self.config_data:
            return
        ok = messagebox.askyesno(
            "پاک کردن" if self.language == "fa" else "Clear",
            "همه کانفیگ‌ها حذف شوند؟" if self.language == "fa"
            else "Remove all configs?")
        if not ok:
            return
        self.disconnect_vpn()
        self.config_data.clear()
        self.refresh_tree()
        self.mark_dirty()

    def copy_error_log(self):
        log_text = ""
        try:
            log_text = read_log()
        except Exception as e:
            log_text = "<خطا در خواندن: %s>" % e
        sel = self.tree.selection()
        if sel:
            key = sel[0]
            entry = self.config_data.get(key, {})
            err = entry.get("error", "")
            if err:
                log_text = ("=== خطای کانفیگ انتخاب‌شده ===\n" + err +
                            "\n\n=== لاگ Xray ===\n" + log_text)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(log_text)
            self.set_status("لاگ خطا در کلیپ‌بورد کپی شد."
                            if self.language == "fa"
                            else "Error log copied to clipboard.")
        except Exception as e:
            messagebox.showerror(
                "خطای کلیپ‌بورد" if self.language == "fa"
                else "Clipboard error", str(e))

    def copy_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        key = sel[0]
        self.root.clipboard_clear()
        self.root.clipboard_append(key)
        self.set_status("کپی شد." if self.language == "fa" else "Copied.")

    def view_selected_config(self):
        sel = self.tree.selection()
        if not sel:
            return
        key = sel[0]
        entry = self.config_data.get(key)
        if not entry:
            return
        cfg = build_config(entry["outbound"],
                           socks_port=self.socks_port,
                           http_port=self.http_port,
                           settings=self.settings)
        self.show_text_dialog(
            "کانفیگ Xray" if self.language == "fa" else "Xray Config",
            json.dumps(cfg, indent=2, ensure_ascii=False),
            width=800, height=600)

    # ---------- خروجی ----------
    def export_results(self):
        if not self.config_data:
            messagebox.showinfo(
                "چیزی برای خروجی نیست" if self.language == "fa"
                else "Nothing to export",
                "ابتدا کانفیگ دریافت کنید." if self.language == "fa"
                else "Fetch configs first.")
            return
        default = ("vpnef_results_" +
                   datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv")
        path = filedialog.asksaveasfilename(
            title="Export results", defaultextension=".csv",
            initialfile=default,
            filetypes=[("CSV", "*.csv"), ("JSON", "*.json"),
                       ("Text", "*.txt")])
        if not path:
            return
        try:
            ext = os.path.splitext(path)[1].lower()
            rows = []
            for k, d in self.config_data.items():
                rows.append({
                    "name": d["name"], "protocol": d["type"],
                    "server": str(d["host"]) + ":" + str(d["port"]),
                    "status": d["status"], "latency_ms": d["latency"],
                    "success_percent": d["success"], "error": d["error"],
                    "uri": k})
            if ext == ".json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"app": APP_NAME, "version": VERSION,
                               "exported_at": datetime.now().isoformat(),
                               "results": rows}, f, indent=2,
                              ensure_ascii=False)
            elif ext == ".txt":
                with open(path, "w", encoding="utf-8") as f:
                    for r in rows:
                        f.write(str(r["status"]) + "\t" +
                                str(r["protocol"]) + "\t" +
                                str(r["latency_ms"]) + "\t" +
                                str(r["server"]) + "\t" +
                                str(r["name"]) + "\n")
            else:
                with open(path, "w", encoding="utf-8-sig",
                          newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
            self.set_status("خروجی در " + path if self.language == "fa"
                            else "Exported to " + path)
        except Exception as e:
            messagebox.showerror(
                "خطای خروجی" if self.language == "fa"
                else "Export error", str(e))

    # ---------- ذخیره ----------
    def mark_dirty(self):
        self._dirty = True
        if self._auto_save_job:
            try:
                self.root.after_cancel(self._auto_save_job)
            except Exception:
                pass
        self._auto_save_job = self.root.after(800, self._auto_save)

    def _auto_save(self):
        self._auto_save_job = None
        self.save_state(silent=True)

    def save_state(self, silent=False):
        try:
            payload = {
                "app": APP_NAME, "version": VERSION,
                "saved_at": datetime.now().isoformat(),
                "target": self.target_var.get(),
                "timeout": self.timeout_var.get(),
                "workers": self.workers_var.get(),
                "language": self.language, "dark": self.dark,
                "settings": self.settings,
                "configs": self.config_data}
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, STATE_FILE)
            self._dirty = False
            if not silent:
                self.set_status("ذخیره شد در " + STATE_FILE
                                if self.language == "fa"
                                else "Saved to " + STATE_FILE)
        except Exception as e:
            if not silent:
                messagebox.showerror(
                    "خطای ذخیره" if self.language == "fa"
                    else "Save error", str(e))

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
            cfgs = payload.get("configs") or {}
            for k, d in cfgs.items():
                if not isinstance(d, dict):
                    continue
                if "outbound" not in d:
                    continue
                self.config_data[k] = d
            if not self.config_data:
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
            if isinstance(payload.get("settings"), dict):
                self.settings = merge_settings(payload["settings"])
            return True
        except Exception:
            return False

    # ---------- مرتب‌سازی ----------
    def sort_column(self, col):
        items = []
        for k, d in self.config_data.items():
            if col == "name":
                v = d.get("name", "")
            elif col == "protocol":
                v = d.get("type", "")
            elif col == "server":
                v = str(d.get("host", "")) + ":" + str(d.get("port", ""))
            elif col == "status":
                v = d.get("status", "")
            elif col == "latency":
                v = (d.get("latency") if d.get("latency") is not None
                     else 999999)
            elif col == "success":
                v = (d.get("success") if d.get("success") is not None
                     else -1)
            else:
                v = d.get("error", "")
            items.append((v, k))
        if self._sort_column == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = col
            self._sort_reverse = False
        items.sort(key=lambda x: x[0], reverse=self._sort_reverse)
        for i, (_, k) in enumerate(items):
            if self.tree.exists(k):
                self.tree.move(k, "", i)

    def set_status(self, text):
        self.status_label.configure(text=text)

    def toggle_theme(self):
        self.dark = not self.dark
        self._apply_theme()
        self._rebuild_tree_tags()
        self._update_texts()
        for spin in (self.timeout_spin, self.workers_spin):
            spin.configure(bg=self.colors["panel2"],
                           fg=self.colors["fg"],
                           insertbackground=self.colors["fg"],
                           buttonbackground=self.colors["panel2"])
        self._update_banner()
        self.mark_dirty()

    def _rebuild_tree_tags(self):
        self.tree.tag_configure("online", foreground=self.colors["good"])
        self.tree.tag_configure("offline", foreground=self.colors["bad"])
        self.tree.tag_configure("testing", foreground=self.colors["warn"])
        self.tree.tag_configure("active", foreground=self.colors["accent"])

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
            if self.runner:
                self.runner.stop()
                self.runner.cleanup()
        except Exception:
            pass
        try:
            if self._auto_save_job:
                try:
                    self.root.after_cancel(self._auto_save_job)
                except Exception:
                    pass
                self._auto_save_job = None
            self.save_state(silent=True)
        except Exception:
            pass
        if IS_WINDOWS and self.sysproxy_on:
            try:
                clear_system_proxy()
            except Exception:
                pass
        if self.tun_active:
            try:
                cleanup_tun_routes(self.settings.get("tun_name", "vpn-tun"))
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = VPNEFApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
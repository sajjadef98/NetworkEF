# NetworkEF

<p align="center">
  <b>A collection of network tools for Windows — VPN config tester, DNS speed tester, and proxy tester.</b><br>
  <b>مجموعه‌ای از ابزارهای شبکه برای ویندوز — تستر VPN، تستر DNS و تستر پروکسی</b>
</p>

<p align="center">
  <a href="https://github.com/sajjadef98/NetworkEF/releases"><img src="https://img.shields.io/github/v/release/sajjadef98/NetworkEF" alt="Release"></a>
  <a href="https://github.com/sajjadef98/NetworkEF/blob/main/LICENSE"><img src="https://img.shields.io/github/license/sajjadef98/NetworkEF" alt="License"></a>
  <a href="https://sajjadef.ir/support"><img src="https://img.shields.io/badge/Support-Donate-blue" alt="Donate"></a>
</p>

---

## 🇬🇧 English

### About

**NetworkEF** is a collection of three Windows GUI applications built with Python's standard library (Tkinter). No external Python packages are required. The tools are:

| Tool | Purpose | Launcher |
|---|---|---|
| **VPNEF** | Fetch, test, and connect to free VPN configs using Xray-core | `vpnef_admin.bat` |
| **DNSEF** | Test DNS server speed and availability (real DNS queries, not ICMP ping) | `dnsef_admin.bat` |
| **ProxyEF** | Test HTTP/HTTPS/SOCKS proxies and manage the Windows system proxy | `proxyef_admin.bat` |

### Download

The easiest way to get started is to download the pre-built **EXE** from the [Releases page](https://github.com/sajjadef98/NetworkEF/releases).

1. Go to the [Releases](https://github.com/sajjadef98/NetworkEF/releases) section.
2. Download the latest `NetworkEF-vX.X.X.zip`.
3. Extract the ZIP file to any folder (e.g., `C:\NetworkEF\`).
4. Run the `.bat` launcher with administrator privileges.

### Running from Source

If you prefer to run from the source code, follow these steps:

#### Prerequisites

- **Windows 10 or 11** (64-bit)
- **Python 3.9 or newer** — download from [python.org](https://www.python.org/downloads/) and check **Add Python to PATH** during installation.

#### Steps

1. Clone the repository:
   ```cmd
   git clone https://github.com/sajjadef98/NetworkEF.git
   cd NetworkEF
   ```

2. (Optional) Create a virtual environment:
   ```cmd
   python -m venv venv
   venv\Scripts\activate
   ```

3. Run any of the tools:
   ```cmd
   python vpnef.py
   python dnsef.py
   python proxyef.py
   ```

4. Or use the provided admin launchers:
   ```cmd
   vpnef_admin.bat
   dnsef_admin.bat
   proxyef_admin.bat
   ```

### VPNEF — Detailed Guide

#### Preparing the Xray Core

VPNEF uses Xray-core to test and connect VPN configs. You can download it in two ways:

- **Automatic:** Run VPNEF and click the **"Download Xray Core"** button.
- **Manual:** Download `Xray-windows-64.zip` from [Xray Releases](https://github.com/XTLS/Xray-core/releases/latest) and place `xray.exe` in the `xray/` folder.

#### Preparing Wintun Driver (for TUN Mode)

If you want to use **TUN Mode** (system-wide tunnel), you also need `wintun.dll`:

1. Extract `wintun-0.14.1.zip` (bundled with the project).
2. Copy `wintun/bin/amd64/wintun.dll`.
3. Paste it into the `xray/` folder (next to `xray.exe`).

#### Usage

1. **Fetch configs:** Click **"Fetch All"** to download free VPN configs from GitHub.
2. **Test:** Click **"Test All"** to measure latency and availability.
3. **Connect:** Select a green (ONLINE) config and click **"Connect"**.
4. **Disconnect:** Click **"Disconnect"** in the top banner.

#### System Proxy vs. TUN Mode

| Feature | System Proxy | TUN Mode |
|---|---|---|
| Traffic coverage | HTTP/HTTPS only (browsers) | All system traffic |
| Admin required | No | Yes |
| Needs `wintun.dll` | No | Yes |
| Best for | Browsers, most sites | Games, Telegram, all apps |

### DNSEF — DNS Speed & Availability Tester

DNSEF performs real DNS queries (A records) to multiple DNS servers and measures response times. It supports importing DNS lists from TXT, CSV, JSON, and URLs.

### ProxyEF — Proxy Tester & System Proxy Manager

ProxyEF tests HTTP, HTTPS, SOCKS4, and SOCKS5 proxies, and can set a working proxy as the Windows system proxy.

### File Structure

```
NetworkEF/
├── vpnef.py                    # VPN tester / connector (Xray-based)
├── xray_helper.py              # Xray manager + config parsers
├── vpnconfig_sources.py        # GitHub config sources
├── dnsef.py                    # DNS speed tester
├── proxyef.py                  # Proxy tester
├── vpnef_admin.bat             # Admin launcher for VPNEF
├── dnsef_admin.bat             # Admin launcher for DNSEF
├── proxyef_admin.bat           # Admin launcher for ProxyEF
├── wintun-0.14.1.zip           # TUN driver (for VPNEF TUN Mode)
├── README.md                   # This file
├── LICENSE                     # License
└── xray/                       # Auto-created by VPNEF
    ├── xray.exe                # Auto-downloaded or manually placed
    ├── wintun.dll              # Manually extracted from zip
    ├── xray.log                # Log file
    └── cache.db                # Xray cache
```

### Support

If these tools are useful to you, consider supporting the developer:

👉 [https://sajjadef.ir/support](https://sajjadef.ir/support)

### License

This project is provided as-is for educational and personal use. Free VPN configs come from public community sources and their reliability/security is not guaranteed.

---

## 🇮🇷 فارسی

### درباره

**NetworkEF** مجموعه‌ای از سه برنامه‌ی گرافیکی ویندوز است که با کتابخانه‌ی استاندارد پایتون (Tkinter) ساخته شده و به هیچ پکیج خارجی نیاز ندارد. این ابزارها عبارتند از:

| ابزار | کاربرد | لانچر |
|---|---|---|
| **VPNEF** | دریافت، تست و اتصال به کانفیگ‌های رایگان VPN با Xray-core | `vpnef_admin.bat` |
| **DNSEF** | تست سرعت و وضعیت سرورهای DNS (کوئری واقعی DNS، نه پینگ ICMP) | `dnsef_admin.bat` |
| **ProxyEF** | تست پروکسی‌های HTTP/HTTPS/SOCKS و مدیریت پروکسی سیستم ویندوز | `proxyef_admin.bat` |

### دانلود

ساده‌ترین راه، دانلود فایل **EXE** آماده از [بخش Releases](https://github.com/sajjadef98/NetworkEF/releases) است.

1. به بخش [Releases](https://github.com/sajjadef98/NetworkEF/releases) بروید.
2. آخرین نسخه‌ی `NetworkEF-vX.X.X.zip` را دانلود کنید.
3. فایل ZIP را در هر پوشه‌ای (مثلاً `C:\NetworkEF\`) استخراج کنید.
4. فایل `.bat` مربوطه را با دسترسی Administrator اجرا کنید.

### اجرا از سورس کد

اگر می‌خواهید از سورس کد اجرا کنید، مراحل زیر را دنبال کنید:

#### پیش‌نیازها

- **ویندوز ۱۰ یا ۱۱** (۶۴ بیتی)
- **پایتون ۳.۹ یا بالاتر** — از [python.org](https://www.python.org/downloads/) دانلود کنید و در زمان نصب گزینه‌ی **Add Python to PATH** را تیک بزنید.

#### مراحل

1. مخزن را کلون کنید:
   ```cmd
   git clone https://github.com/sajjadef98/NetworkEF.git
   cd NetworkEF
   ```

2. (اختیاری) محیط مجازی بسازید:
   ```cmd
   python -m venv venv
   venv\Scripts\activate
   ```

3. هر یک از ابزارها را اجرا کنید:
   ```cmd
   python vpnef.py
   python dnsef.py
   python proxyef.py
   ```

4. یا از لانچرهای ادمین استفاده کنید:
   ```cmd
   vpnef_admin.bat
   dnsef_admin.bat
   proxyef_admin.bat
   ```

### VPNEF — راهنمای کامل

#### آماده‌سازی هسته‌ی Xray

VPNEF از Xray-core برای تست و اتصال کانفیگ‌ها استفاده می‌کند. دو راه برای دانلود آن دارید:

- **خودکار:** برنامه را اجرا کنید و روی دکمه‌ی **«دانلود هسته Xray»** کلیک کنید.
- **دستی:** فایل `Xray-windows-64.zip` را از [صفحه‌ی Releases پروژه Xray](https://github.com/XTLS/Xray-core/releases/latest) دانلود کنید و `xray.exe` را در پوشه‌ی `xray/` قرار دهید.

#### آماده‌سازی درایور Wintun (برای TUN Mode)

اگر می‌خواهید از **TUN Mode** (تونل کل سیستم) استفاده کنید، به `wintun.dll` هم نیاز دارید:

1. فایل `wintun-0.14.1.zip` (همراه پروژه) را از حالت فشرده خارج کنید.
2. فایل `wintun/bin/amd64/wintun.dll` را کپی کنید.
3. آن را در پوشه‌ی `xray/` (کنار `xray.exe`) پیست کنید.

#### نحوه‌ی استفاده

1. **دریافت کانفیگ‌ها:** روی دکمه‌ی **«دریافت همه منابع»** کلیک کنید تا کانفیگ‌های رایگان از GitHub دانلود شوند.
2. **تست:** روی دکمه‌ی **«تست همه»** کلیک کنید تا زمان پاسخ و وضعیت مشخص شود.
3. **اتصال:** یک کانفیگ سبز (ONLINE) را انتخاب کنید و روی **«اتصال VPN»** کلیک کنید.
4. **قطع اتصال:** روی دکمه‌ی **«قطع اتصال»** در نوار بالا کلیک کنید.

#### تفاوت System Proxy و TUN Mode

| ویژگی | System Proxy | TUN Mode |
|---|---|---|
| پوشش ترافیک | فقط HTTP/HTTPS (مرورگرها) | تمام ترافیک سیستم |
| نیاز به ادمین | خیر | بله |
| نیاز به `wintun.dll` | خیر | بله |
| مناسب برای | مرورگر و بیشتر سایت‌ها | بازی، تلگرام، هر برنامه |

### DNSEF — تستر سرعت و وضعیت DNS

DNSEF کوئری‌های واقعی DNS (رکورد A) به سرورهای مختلف می‌فرستد و زمان پاسخ را اندازه می‌گیرد. از ایمپورت لیست DNS از فایل‌های TXT، CSV، JSON و URL پشتیبانی می‌کند.

### ProxyEF — تستر پروکسی و مدیریت پروکسی سیستم

ProxyEF پروکسی‌های HTTP، HTTPS، SOCKS4 و SOCKS5 را تست می‌کند و می‌تواند یک پروکسی سالم را به‌عنوان پروکسی سیستم ویندوز تنظیم کند.

### ساختار فایل‌ها

```
NetworkEF/
├── vpnef.py                    # تستر / اتصال VPN (بر پایه Xray)
├── xray_helper.py              # مدیریت Xray + پارسر کانفیگ‌ها
├── vpnconfig_sources.py        # منابع کانفیگ از GitHub
├── dnsef.py                    # تستر سرعت DNS
├── proxyef.py                  # تستر پروکسی
├── vpnef_admin.bat             # لانچر ادمین VPNEF
├── dnsef_admin.bat             # لانچر ادمین DNSEF
├── proxyef_admin.bat           # لانچر ادمین ProxyEF
├── wintun-0.14.1.zip           # درایور TUN (برای TUN Mode در VPNEF)
├── README.md                   # همین فایل
├── LICENSE                     # مجوز
└── xray/                       # خودکار توسط VPNEF ساخته می‌شود
    ├── xray.exe                # خودکار دانلود یا دستی قرار داده می‌شود
    ├── wintun.dll              # دستی از zip استخراج می‌شود
    ├── xray.log                # فایل لاگ
    └── cache.db                # کش Xray
```

### حمایت

اگر این ابزارها برایتان مفید بود، از توسعه‌دهنده حمایت کنید:

👉 [https://sajjadef.ir/support](https://sajjadef.ir/support)

### مجوز

این پروژه به‌صورت «همان‌گونه که هست» برای استفاده‌ی آموزشی و شخصی ارائه شده است. کانفیگ‌های رایگان VPN از منابع عمومی جامعه جمع‌آوری می‌شوند و قابلیت اطمینان و امنیت آن‌ها تضمین نمی‌شود.

---

<p align="center">Made with ❤️ by <a href="https://github.com/sajjadef98">Sajjad</a></p>

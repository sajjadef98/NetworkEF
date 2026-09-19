# xray_helper.py
# VPNEF 2.2 - مدیریت Xray-core با پشتیبانی از System Proxy و TUN Mode
import base64
import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

APP_NAME = "VPNEF"
IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

if IS_WINDOWS:
    import winreg

XRAY_URL_WIN = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-windows-64.zip"
XRAY_URL_LINUX = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
XRAY_URL_MAC = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-macos-64.zip"

LOG_MAX_BYTES = 5 * 1024 * 1024

DEFAULT_SETTINGS = {
    "log_level": "warning",
    "sniffing": True,
    "sniff_override": True,
    "tcp_no_delay": True,
    "domain_strategy": "IPIfNonMatch",
    "bypass_private": True,
    "custom_direct_ips": [],
    "custom_direct_domains": [],
    "custom_block_ips": [],
    "custom_block_domains": [],
    "dns_servers": ["1.1.1.1", "8.8.8.8"],
    "dns_query_strategy": "UseIP",
    "dns_disable_cache": False,
    # تنظیمات TUN
    "use_tun_mode": False,
    "tun_name": "vpn-tun",
    "tun_mtu": 1500,
    "tun_gateway": "10.0.0.1/16",
    "tun_dns": ["1.1.1.1", "8.8.8.8"],
    "tun_auto_route": True,
}

_LOG_LOCK = threading.Lock()

def _base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def _xray_dir():
    base = _base_dir()
    path = os.path.join(base, "xray")
    os.makedirs(path, exist_ok=True)
    return path


def get_xray_path():
    name = "xray.exe" if IS_WINDOWS else "xray"
    p = os.path.join(_xray_dir(), name)
    return p if os.path.isfile(p) else None


def get_log_path():
    return os.path.join(_xray_dir(), "xray.log")


# =============================================================================
# لاگ واحد با چرخش
# =============================================================================
def _rotate_log_if_needed():
    try:
        path = get_log_path()
        if not os.path.isfile(path):
            return
        if os.path.getsize(path) < LOG_MAX_BYTES:
            return
        with open(path, "rb") as f:
            f.seek(-LOG_MAX_BYTES // 2, 2)
            f.readline()
            tail = f.read()
        with open(path, "wb") as f:
            f.write(b"----- [log rotated] -----\n")
            f.write(tail)
    except Exception:
        pass


def append_log(text, section=None):
    if not text:
        return
    with _LOG_LOCK:
        try:
            _rotate_log_if_needed()
            with open(get_log_path(), "a", encoding="utf-8", errors="replace") as f:
                if section:
                    f.write("\n\n===== " + section + " =====\n")
                f.write(text)
                if not text.endswith("\n"):
                    f.write("\n")
        except Exception:
            pass


def clear_log():
    with _LOG_LOCK:
        try:
            with open(get_log_path(), "w", encoding="utf-8") as f:
                f.write("")
            return True
        except Exception:
            return False


def read_log(max_bytes=200_000):
    try:
        path = get_log_path()
        if not os.path.isfile(path):
            return "<لاگ خالی است>"
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()
            return f.read()
    except Exception as e:
        return "<خطا در خواندن لاگ: " + str(e) + ">"


def get_log_size_human():
    try:
        size = os.path.getsize(get_log_path())
        if size < 1024:
            return str(size) + " B"
        if size < 1024 * 1024:
            return "%.1f KB" % (size / 1024)
        return "%.2f MB" % (size / (1024 * 1024))
    except Exception:
        return "—"


# =============================================================================
# دانلود Xray-core
# =============================================================================
def download_xray(progress_cb=None):
    try:
        if IS_WINDOWS:
            url = XRAY_URL_WIN
        elif sys.platform == "darwin":
            url = XRAY_URL_MAC
        else:
            url = XRAY_URL_LINUX

        if progress_cb:
            progress_cb(3, "در حال دانلود Xray-core...")

        tmp = tempfile.mkdtemp(prefix="vpnef_xray_")
        arc = os.path.join(tmp, "xray.zip")
        req = urllib.request.Request(url, headers={"User-Agent": APP_NAME + "/2.2"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            got = 0
            with open(arc, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total > 0 and progress_cb:
                        pct = 3 + int(got / total * 87)
                        progress_cb(pct, "در حال دانلود... %d KB" % (got // 1024))

        if progress_cb:
            progress_cb(92, "در حال استخراج...")

        target_name = "xray.exe" if IS_WINDOWS else "xray"
        found = False
        with zipfile.ZipFile(arc, "r") as z:
            for name in z.namelist():
                if os.path.basename(name) == target_name:
                    data = z.read(name)
                    dest = os.path.join(_xray_dir(), target_name)
                    with open(dest, "wb") as f:
                        f.write(data)
                    if not IS_WINDOWS:
                        os.chmod(dest, 0o755)
                    found = True
                    break

        shutil.rmtree(tmp, ignore_errors=True)
        if not found:
            return False, "فایل xray در آرشیو پیدا نشد"
        if progress_cb:
            progress_cb(100, "Xray-core نصب شد")
        append_log("Xray-core downloaded successfully.", "download")
        return True, "Xray-core با موفقیت نصب شد."
    except Exception as e:
        append_log(str(e), "download error")
        return False, str(e)


# =============================================================================
# پارسرها
# =============================================================================
def _b64(s):
    s = (s or "").strip().replace("-", "+").replace("_", "/")
    s += "=" * ((-len(s)) % 4)
    try:
        return base64.b64decode(s).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _qs(q):
    out = {}
    for k, v in urllib.parse.parse_qsl(q, keep_blank_values=True):
        if k not in out:
            out[k] = v
    return out


def _frag(uri):
    if "#" in uri:
        try:
            return urllib.parse.unquote(uri.rsplit("#", 1)[1])
        except Exception:
            return uri.rsplit("#", 1)[1]
    return ""


def _hostport(hp):
    hp = (hp or "").strip()
    if hp.startswith("["):
        end = hp.find("]")
        if end == -1:
            return None, 0
        host = hp[1:end]
        rest = hp[end + 1:]
        try:
            port = int(rest[1:]) if rest.startswith(":") else 0
        except ValueError:
            port = 0
        return host, port
    if hp.count(":") == 1:
        h, p = hp.rsplit(":", 1)
        try:
            return h, int(p)
        except ValueError:
            return h, 0
    return hp, 0


def parse_vless(uri):
    try:
        body = uri[8:]
        name = _frag(body)
        if "#" in body:
            body = body.split("#", 1)[0]
        if "?" in body:
            main, q = body.split("?", 1)
        else:
            main, q = body, ""
        if "@" not in main:
            return None
        uid, hp = main.rsplit("@", 1)
        host, port = _hostport(hp)
        if not host or not port:
            return None
        p = _qs(q)
        net = p.get("type", "tcp")
        sec = p.get("security", "none")
        stream = {"network": net}
        if sec == "tls":
            stream["security"] = "tls"
            tls = {"serverName": p.get("sni", "") or host,
                   "allowInsecure": p.get("allowInsecure", "0") in ("1", "true")}
            if p.get("fp"):
                tls["fingerprint"] = p["fp"]
            if p.get("alpn"):
                tls["alpn"] = [a for a in p["alpn"].split(",") if a]
            stream["tlsSettings"] = tls
        elif sec == "reality":
            stream["security"] = "reality"
            stream["realitySettings"] = {
                "serverName": p.get("sni", "") or host,
                "fingerprint": p.get("fp", "chrome"),
                "publicKey": p.get("pbk", ""),
                "shortId": p.get("sid", ""),
                "spiderX": p.get("spx", "/"),
            }
        if net == "ws":
            ws = {"path": p.get("path", "/")}
            if p.get("host"):
                ws["headers"] = {"Host": p["host"]}
            stream["wsSettings"] = ws
        elif net == "grpc":
            stream["grpcSettings"] = {"serviceName": p.get("serviceName", "") or p.get("path", "")}
        elif net == "tcp" and p.get("headerType") == "http":
            stream["tcpSettings"] = {"header": {"type": "http",
                "request": {"path": [p.get("path", "/")],
                            "headers": {"Host": [p.get("host", "")]} if p.get("host") else {}}}}
        elif net in ("http", "h2", "xhttp"):
            stream["network"] = "tcp"
            stream["tcpSettings"] = {"header": {"type": "http",
                "request": {"path": [p.get("path", "/")],
                            "headers": {"Host": [p.get("host", "")]} if p.get("host") else {}}}}
        user = {"id": uid, "encryption": "none"}
        if p.get("flow"):
            user["flow"] = p["flow"]
        outbound = {"protocol": "vless",
                    "settings": {"vnext": [{"address": host, "port": port, "users": [user]}]},
                    "streamSettings": stream}
        return {"name": name or (host + ":" + str(port)), "type": "vless",
                "outbound": outbound, "raw": uri, "server": host, "port": port}
    except Exception:
        return None


def parse_vmess(uri):
    try:
        body = uri[8:]
        name = _frag(body)
        if "#" in body:
            body = body.split("#", 1)[0]
        decoded = _b64(body)
        if not decoded or not decoded.lstrip().startswith("{"):
            return None
        cfg = json.loads(decoded)
        host = str(cfg.get("add", "")).strip()
        try:
            port = int(cfg.get("port", 0))
        except (ValueError, TypeError):
            return None
        if not host or not port:
            return None
        net = cfg.get("net", "tcp") or "tcp"
        stream = {"network": net}
        tls = (cfg.get("tls", "") or "").lower()
        if tls == "tls":
            stream["security"] = "tls"
            tls_cfg = {"serverName": cfg.get("sni", "") or cfg.get("host", "") or host,
                       "allowInsecure": False}
            if cfg.get("fp"):
                tls_cfg["fingerprint"] = cfg["fp"]
            stream["tlsSettings"] = tls_cfg
        if net == "ws":
            ws = {"path": cfg.get("path", "/") or "/"}
            if cfg.get("host"):
                ws["headers"] = {"Host": cfg["host"]}
            stream["wsSettings"] = ws
        elif net == "grpc":
            stream["grpcSettings"] = {"serviceName": cfg.get("path", "") or ""}
        elif net == "h2":
            stream["network"] = "h2"
            stream["httpSettings"] = {"path": cfg.get("path", "/") or "/",
                                       "host": [cfg["host"]] if cfg.get("host") else []}
        elif net == "tcp" and cfg.get("type") == "http":
            stream["tcpSettings"] = {"header": {"type": "http",
                "request": {"path": [cfg.get("path", "/") or "/"],
                            "headers": {"Host": [cfg["host"]]} if cfg.get("host") else {}}}}
        try:
            aid = int(cfg.get("aid", 0))
        except (ValueError, TypeError):
            aid = 0
        user = {"id": cfg.get("id", ""), "alterId": aid,
                "security": cfg.get("scy", "auto") or "auto"}
        outbound = {"protocol": "vmess",
                    "settings": {"vnext": [{"address": host, "port": port, "users": [user]}]},
                    "streamSettings": stream}
        return {"name": name or cfg.get("ps", host + ":" + str(port)),
                "type": "vmess", "outbound": outbound, "raw": uri,
                "server": host, "port": port}
    except Exception:
        return None


def parse_trojan(uri):
    try:
        body = uri[9:]
        name = _frag(body)
        if "#" in body:
            body = body.split("#", 1)[0]
        if "?" in body:
            main, q = body.split("?", 1)
        else:
            main, q = body, ""
        if "@" not in main:
            return None
        pw, hp = main.rsplit("@", 1)
        pw = urllib.parse.unquote(pw)
        host, port = _hostport(hp)
        if not host or not port:
            return None
        p = _qs(q)
        net = p.get("type", "tcp")
        stream = {"network": net, "security": "tls"}
        tls = {"serverName": p.get("sni", "") or host,
               "allowInsecure": p.get("allowInsecure", "0") in ("1", "true")}
        if p.get("fp"):
            tls["fingerprint"] = p["fp"]
        if p.get("alpn"):
            tls["alpn"] = [a for a in p["alpn"].split(",") if a]
        stream["tlsSettings"] = tls
        if net == "ws":
            ws = {"path": p.get("path", "/")}
            if p.get("host"):
                ws["headers"] = {"Host": p["host"]}
            stream["wsSettings"] = ws
        elif net == "grpc":
            stream["grpcSettings"] = {"serviceName": p.get("serviceName", "") or p.get("path", "")}
        outbound = {"protocol": "trojan",
                    "settings": {"servers": [{"address": host, "port": port, "password": pw}]},
                    "streamSettings": stream}
        return {"name": name or (host + ":" + str(port)), "type": "trojan",
                "outbound": outbound, "raw": uri, "server": host, "port": port}
    except Exception:
        return None


def parse_ss(uri):
    try:
        body = uri[5:]
        name = _frag(body)
        if "#" in body:
            body = body.split("#", 1)[0]
        if "?" in body:
            body = body.split("?", 1)[0]
        method = pw = host = ""
        port = 0
        if "@" in body:
            ui, hp = body.rsplit("@", 1)
            dec = _b64(ui)
            if dec and ":" in dec:
                ui = dec
            if ":" not in ui:
                return None
            method, pw = ui.split(":", 1)
            host, port = _hostport(hp)
        else:
            dec = _b64(body)
            if not dec or "@" not in dec:
                return None
            ui, hp = dec.rsplit("@", 1)
            if ":" not in ui:
                return None
            method, pw = ui.split(":", 1)
            host, port = _hostport(hp)
        if not host or not port:
            return None
        pw = urllib.parse.unquote(pw)
        outbound = {"protocol": "shadowsocks",
                    "settings": {"servers": [{"address": host, "port": port,
                                              "method": method, "password": pw}]}}
        return {"name": name or (host + ":" + str(port)), "type": "ss",
                "outbound": outbound, "raw": uri, "server": host, "port": port}
    except Exception:
        return None


PARSERS = {"vless://": parse_vless, "vmess://": parse_vmess,
           "trojan://": parse_trojan, "ss://": parse_ss}


def parse_uri(uri):
    uri = (uri or "").strip()
    if not uri or uri.startswith("#"):
        return None
    low = uri.lower()
    for prefix, fn in PARSERS.items():
        if low.startswith(prefix):
            return fn(uri)
    return None


def parse_subscription(text):
    text = (text or "").strip()
    if not text:
        return []
    if "://" not in text[:500]:
        dec = _b64(text)
        if dec and "://" in dec:
            text = dec
    results = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for token in re.split(r"\s+", line):
            if "://" not in token:
                continue
            p = parse_uri(token)
            if p and p["raw"] not in seen:
                seen.add(p["raw"])
                results.append(p)
    return results


# =============================================================================
# ساخت کانفیگ Xray (System Proxy + TUN)
# =============================================================================
_PRIVATE_CIDRS = [
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10",
    "::1/128", "fc00::/7", "fe80::/10",
]


def _clean_list(items):
    out = []
    seen = set()
    for it in items or []:
        s = str(it).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def merge_settings(user):
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    if isinstance(user, dict):
        for k, v in user.items():
            if k in out:
                try:
                    if isinstance(out[k], list) and isinstance(v, str):
                        out[k] = [line.strip() for line in v.splitlines() if line.strip()]
                    elif isinstance(out[k], bool):
                        out[k] = bool(v)
                    elif isinstance(out[k], str):
                        out[k] = str(v)
                    else:
                        out[k] = v
                except Exception:
                    pass
    return out


def build_config(outbound, socks_port=10808, http_port=10809, settings=None):
    """
    اگر settings["use_tun_mode"] == True باشد، کانفیگ TUN ساخته می‌شود.
    در غیر این صورت، کانفیگ System Proxy (SOCKS + HTTP) ساخته می‌شود.
    """
    s = merge_settings(settings)
    ob = json.loads(json.dumps(outbound))
    ob["tag"] = "proxy"

    if s.get("tcp_no_delay", True):
        stream = ob.setdefault("streamSettings", {})
        sockopt = stream.setdefault("sockopt", {})
        sockopt["tcpNoDelay"] = True

    use_tun = bool(s.get("use_tun_mode", False))

    # ---------- Inbounds ----------
    if use_tun:
        # در حالت TUN، یک inbound از نوع tun + یک inbound DNS محلی
        tun_inbound = {
            "tag": "tun-in",
            "protocol": "tun",
            "settings": {
                "name": s.get("tun_name", "vpn-tun"),
                "mtu": int(s.get("tun_mtu", 1500)),
                "gateway": [s.get("tun_gateway", "10.0.0.1/16")],
                "dns": list(s.get("tun_dns", ["1.1.1.1", "8.8.8.8"])),
                "autoSystemRoutingTable": ["0.0.0.0/0", "::/0"]
                if s.get("tun_auto_route", True) else [],
                "autoOutboundsInterface": "auto",
            },
        }
        inbounds = [tun_inbound]
        # در TUN mode، sniffing هم فعال است
        tun_inbound["sniffing"] = {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"],
            "routeOnly": bool(s.get("sniff_override", True)),
        }
    else:
        sniffing_cfg = None
        if s.get("sniffing", True):
            sniffing_cfg = {
                "enabled": True,
                "destOverride": ["http", "tls", "quic"],
                "routeOnly": bool(s.get("sniff_override", True)),
            }
        inbounds = [
            {"tag": "socks-in", "port": socks_port, "listen": "127.0.0.1",
             "protocol": "socks", "settings": {"udp": True, "auth": "noauth"}},
            {"tag": "http-in", "port": http_port, "listen": "127.0.0.1",
             "protocol": "http"},
        ]
        if sniffing_cfg:
            for ib in inbounds:
                ib["sniffing"] = json.loads(json.dumps(sniffing_cfg))

    # ---------- Routing ----------
    rules = []
    if s.get("bypass_private", True):
        rules.append({"type": "field", "ip": list(_PRIVATE_CIDRS),
                      "outboundTag": "direct"})
    direct_ips = _clean_list(s.get("custom_direct_ips"))
    if direct_ips:
        rules.append({"type": "field", "ip": direct_ips, "outboundTag": "direct"})
    direct_domains = _clean_list(s.get("custom_direct_domains"))
    if direct_domains:
        rules.append({"type": "field", "domain": direct_domains, "outboundTag": "direct"})
    block_ips = _clean_list(s.get("custom_block_ips"))
    if block_ips:
        rules.append({"type": "field", "ip": block_ips, "outboundTag": "block"})
    block_domains = _clean_list(s.get("custom_block_domains"))
    if block_domains:
        rules.append({"type": "field", "domain": block_domains, "outboundTag": "block"})

    # ---------- DNS ----------
    dns_servers = _clean_list(s.get("dns_servers")) or ["1.1.1.1", "8.8.8.8"]
    dns_cfg = {
        "servers": dns_servers,
        "queryStrategy": s.get("dns_query_strategy", "UseIP"),
        "disableCache": bool(s.get("dns_disable_cache", False)),
    }

    # ---------- Outbounds ----------
    # در TUN mode، direct باید interface فیزیکی را bind کند
    direct_outbound = {"tag": "direct", "protocol": "freedom"}
    if use_tun:
        direct_outbound["streamSettings"] = {
            "sockopt": {"interface": "auto"}
        }

    return {
        "log": {"loglevel": s.get("log_level", "warning")},
        "dns": dns_cfg,
        "inbounds": inbounds,
        "outbounds": [
            ob,
            direct_outbound,
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": s.get("domain_strategy", "IPIfNonMatch"),
            "rules": rules,
        },
    }


def write_config(cfg, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)
    return path


# =============================================================================
# اجراکننده Xray
# =============================================================================
class XrayRunner:
    def __init__(self, uid=None):
        self.uid = uid or uuid.uuid4().hex[:8]
        self.config_path = os.path.join(
            tempfile.gettempdir(), "vpnef_cfg_" + self.uid + ".json")
        self.tmp_log_path = os.path.join(
            tempfile.gettempdir(), "vpnef_log_" + self.uid + ".txt")
        self.proc = None
        self._log_fh = None
        self.started_at = None

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, config):
        if self.is_running():
            return False, "already running"
        exe = get_xray_path()
        if not exe:
            return False, "Xray نصب نیست"
        try:
            write_config(config, self.config_path)
        except Exception as e:
            return False, "خطا در نوشتن کانفیگ: " + str(e)
        try:
            self._log_fh = open(self.tmp_log_path, "w", encoding="utf-8")
        except Exception:
            self._log_fh = None
        try:
            self.proc = subprocess.Popen(
                [exe, "run", "-c", self.config_path],
                stdout=self._log_fh or subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                cwd=_xray_dir(),
                creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0,
            )
            self.started_at = time.time()
            # زمان بیشتر برای TUN
            time.sleep(2.5)
            if self.proc.poll() is not None:
                err = self._read_tmp_log()
                self._finalize_log(err, "Xray start failed")
                return False, err or "Xray exited immediately"
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def _read_tmp_log(self, max_lines=80):
        try:
            if self._log_fh:
                self._log_fh.flush()
            if os.path.isfile(self.tmp_log_path):
                with open(self.tmp_log_path, "r", encoding="utf-8",
                          errors="replace") as f:
                    content = f.read()
                lines = content.splitlines()[-max_lines:]
                return "\n".join(_strip_ansi(x) for x in lines)
        except Exception:
            pass
        return ""

    def _finalize_log(self, content, section):
        if content:
            append_log(content, section)

    def stop(self):
        if not self.proc:
            return
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=2)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self.proc = None
            if self._log_fh:
                try:
                    self._log_fh.close()
                except Exception:
                    pass
                self._log_fh = None

    def cleanup(self):
        for p in (self.config_path, self.tmp_log_path):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass

    def finalize_after_test(self, success):
        if success:
            return
        err = self._read_tmp_log()
        if err:
            self._finalize_log(err, "test failed at " + time.strftime("%Y-%m-%d %H:%M:%S"))


def _strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s or "")


# =============================================================================
# ابزارهای شبکه
# =============================================================================
def wait_port(host, port, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except Exception:
            time.sleep(0.15)
    return False


def test_via_http(http_port, target="http://httpbin.org/ip", timeout=8.0):
    start = time.perf_counter()
    try:
        proxy = "http://127.0.0.1:" + str(http_port)
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request(target, headers={"User-Agent": APP_NAME})
        with opener.open(req, timeout=timeout) as resp:
            resp.read(128)
        return True, (time.perf_counter() - start) * 1000, ""
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - start) * 1000
        if 100 <= e.code < 600:
            return True, elapsed, ""
        return False, elapsed, "HTTP " + str(e.code)
    except Exception as e:
        return False, None, str(e)[:150]


def get_latest_error():
    return read_log()


# =============================================================================
# تنظیم پروکسی سیستم ویندوز (WinINET + WinHTTP)
# =============================================================================
INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def _refresh_wininet():
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
        ctypes.windll.wininet.InternetSetOptionW(0, 37, 0, 0)
    except Exception:
        pass


def set_system_proxy(server, bypass="<local>"):
    """
    تنظیم پروکسی در HKCU (WinINET) و همچنین netsh winhttp.
    server: مثلاً "127.0.0.1:10809" یا "http=127.0.0.1:10809;https=127.0.0.1:10809"
    """
    if not IS_WINDOWS:
        return False, "فقط ویندوز"
    try:
        # 1) WinINET (HKCU)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS, 0,
                            winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, server)
            winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ, bypass)
        _refresh_wininet()
        # 2) WinHTTP (نیاز به ادمین)
        try:
            subprocess.run(
                ["netsh", "winhttp", "set", "proxy",
                 "proxy-server=" + server,
                 "bypass-list=" + bypass],
                capture_output=True, timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception:
            pass
        return True, "OK"
    except Exception as e:
        return False, str(e)


def clear_system_proxy():
    if not IS_WINDOWS:
        return False, "فقط ویندوز"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS, 0,
                            winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        _refresh_wininet()
        try:
            subprocess.run(["netsh", "winhttp", "reset", "proxy"],
                           capture_output=True, timeout=10,
                           creationflags=CREATE_NO_WINDOW)
        except Exception:
            pass
        return True, "OK"
    except Exception as e:
        return False, str(e)


def get_system_proxy():
    if not IS_WINDOWS:
        return False, ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS, 0,
                            winreg.KEY_READ) as k:
            try:
                en = winreg.QueryValueEx(k, "ProxyEnable")[0]
            except FileNotFoundError:
                en = 0
            try:
                srv = winreg.QueryValueEx(k, "ProxyServer")[0]
            except FileNotFoundError:
                srv = ""
        return bool(en), srv
    except Exception:
        return False, ""


# =============================================================================
# پاک‌سازی TUN (اختیاری)
# =============================================================================
def cleanup_tun_routes(interface_name="vpn-tun"):
    """
    حذف مسیرهای TUN و ریست کردن DNS در صورت باقی‌مانده.
    (برای مواقعی که Xray به‌درستی بسته نشده)
    """
    if not IS_WINDOWS:
        return
    try:
        # حذف routeهای مربوطه
        subprocess.run(
            ["powershell", "-Command",
             "Get-NetRoute -InterfaceAlias '" + interface_name +
             "' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false"],
            capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass
    try:
        # ریست DNS
        subprocess.run(["ipconfig", "/flushdns"],
                       capture_output=True, timeout=10,
                       creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass
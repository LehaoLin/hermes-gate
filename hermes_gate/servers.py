"""服务器历史记录管理"""

import json
import os
from pathlib import Path


def _config_dir() -> Path:
    """配置目录"""
    d = Path.home() / ".hermes-gate"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _servers_file() -> Path:
    return _config_dir() / "servers.json"


def load_servers() -> list[dict]:
    """加载服务器列表，每项 {"user": "root", "host": "1.2.3.4", "label": "myserver"}"""
    f = _servers_file()
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def save_servers(servers: list[dict]) -> None:
    """保存服务器列表"""
    f = _servers_file()
    f.write_text(json.dumps(servers, indent=2, ensure_ascii=False))


def add_server(user: str, host: str) -> dict:
    """添加服务器并返回，如果已存在则返回已有项"""
    servers = load_servers()
    # 去重
    for s in servers:
        if s["user"] == user and s["host"] == host:
            return s
    entry = {"user": user, "host": host}
    servers.append(entry)
    save_servers(servers)
    return entry


def remove_server(user: str, host: str) -> None:
    """移除服务器"""
    servers = load_servers()
    servers = [s for s in servers if not (s["user"] == user and s["host"] == host)]
    save_servers(servers)


def _resolve_from_hosts(host: str) -> str | None:
    for path in ("/host/etc/hosts", "/etc/hosts"):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        ip = parts[0]
                        names = parts[1:]
                        if host in names:
                            return ip
        except OSError:
            pass
    return None


def resolve_host(host: str) -> tuple[str, str | None]:
    """
    解析 host：
    - 如果是 IP，返回 (ip, None)
    - 如果是 hostname，查找 /host/etc/hosts → /etc/hosts 得到 IP，返回 (hostname, ip)
    如果找不到，返回 (host, None)
    """
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return host, None

    ip = _resolve_from_hosts(host)
    if ip:
        return host, ip

    return host, None


def resolve_to_ip(host: str) -> str:
    """将 hostname 解析为 IP，用于 SSH/ping 连接。无法解析则原样返回。"""
    _, ip = resolve_host(host)
    return ip or host


def display_name(server: dict) -> str:
    """
    生成显示名：
    - IP 登录 → root@1.2.3.4
    - hostname 登录且 /etc/hosts 有解析 → admin@hostname (1.2.3.4)
    """
    user = server["user"]
    host = server["host"]
    hostname, ip = resolve_host(host)
    if ip:
        return f"{user}@{hostname} ({ip})"
    return f"{user}@{host}"

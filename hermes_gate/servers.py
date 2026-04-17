"""服务器历史记录管理 + SSH config 解析"""

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


def ssh_config_path() -> Path:
    """Return the SSH config path used by Hermes Gate."""
    configured = os.environ.get("HERMES_GATE_SSH_CONFIG")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ssh" / "config"


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


def add_server(
    user: str, host: str, port: str = "22", ssh_alias: str | None = None
) -> dict:
    """添加服务器并返回，如果已存在则返回已有项"""
    servers = load_servers()
    for s in servers:
        if s["user"] == user and s["host"] == host and s.get("port", "22") == port:
            if ssh_alias and s.get("ssh_alias") != ssh_alias:
                s["ssh_alias"] = ssh_alias
                save_servers(servers)
            return s
    entry = {"user": user, "host": host, "port": port}
    if ssh_alias:
        entry["ssh_alias"] = ssh_alias
    servers.append(entry)
    save_servers(servers)
    return entry


def remove_server(user: str, host: str, port: str = "22") -> None:
    """移除服务器"""
    servers = load_servers()
    servers = [
        s
        for s in servers
        if not (s["user"] == user and s["host"] == host and s.get("port", "22") == port)
    ]
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
    - 非 22 端口 → 附加 :port
    """
    user = server["user"]
    host = server["host"]
    port = server.get("port", "22")
    hostname, ip = resolve_host(host)
    if ip:
        name = f"{user}@{hostname} ({ip})"
    else:
        name = f"{user}@{host}"
    if port != "22":
        name += f":{port}"
    return name


def _parse_ssh_config_hosts() -> list[dict]:
    """Parse simple ~/.ssh/config Host stanzas used by this app."""
    ssh_config = ssh_config_path()
    if not ssh_config.exists():
        return []

    try:
        content = ssh_config.read_text()
    except OSError:
        return []

    blocks: list[dict] = []
    aliases: list[str] = []
    options: dict[str, str] = {}

    def flush() -> None:
        if not aliases:
            return
        for alias in aliases:
            if "*" in alias or "?" in alias:
                continue
            host_name = options.get("hostname", alias)
            blocks.append(
                {
                    "alias": alias,
                    "host": host_name,
                    "user": options.get("user", "root"),
                    "port": options.get("port", "22"),
                }
            )

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        key = parts[0].lower()
        value = parts[1].strip() if len(parts) > 1 else ""
        if key == "host":
            flush()
            aliases = value.split()
            options = {}
        elif aliases:
            options[key] = value

    flush()
    return blocks


def resolve_ssh_config(host_alias: str) -> dict | None:
    """从 ~/.ssh/config 解析 Host 别名，返回 {user, host, port} 或 None。"""
    for block in _parse_ssh_config_hosts():
        if block["alias"] == host_alias:
            return {
                "user": block["user"],
                "host": block["host"],
                "port": block["port"],
                "ssh_alias": block["alias"],
            }
    return None


def find_ssh_alias(user: str, host: str, port: str = "22") -> str | None:
    """Find a config alias matching a concrete user/host/port target."""
    port = str(port)
    for block in _parse_ssh_config_hosts():
        if block["user"] == user and block["host"] == host and block["port"] == port:
            return block["alias"]
    return None

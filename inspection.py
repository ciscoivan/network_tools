#!/usr/bin/env python3
"""
网络设备巡检脚本
支持 Cisco IOS/IOS-XE · Cisco IOS-XR · Cisco NX-OS · Juniper JunOS · Huawei VRP · Fortinet FortiOS
使用 netmiko SSH 连接设备采集信息，生成 HTML 报告并备份配置。

设备清单格式 (devices.csv):
  ip,username,password,port,device_type
  device_type: cisco_ios | cisco_xr | cisco_nxos | juniper | huawei | fortinet
"""

import csv
import re
import sys
import io
import time
import ipaddress
import html as html_module
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException

# =========================== 配置 ===========================
BASE_DIR = Path(__file__).resolve().parent
DEVICES_FILE = BASE_DIR / "devices.csv"
REPORT_DIR = BASE_DIR / "reports"
CONFIG_DIR = BASE_DIR / "configs"
MAX_WORKERS = 10
CONN_TIMEOUT = 30
CMD_TIMEOUT = 60
CONN_RETRIES = 2
RETRY_DELAY = 3

# 所有设备类型共用同一套中文描述键, 便于从结果集中按 key 直接取值
DESC_VERSION = "设备版本/型号/运行时间"
DESC_CPU = "CPU 使用率"
DESC_MEM = "内存使用率"
DESC_CONFIG = "运行配置"


# ═══════════════════════════ 巡检命令 ═══════════════════════════
# 格式: { 分类名: { 命令: 描述 } }

CISCO_IOS_COMMANDS = {
    "基本信息": {"show version": DESC_VERSION, "show inventory": "硬件清单(序列号)",
                 "show platform": "平台硬件详情(槽位/板卡/模块)",
                 "show running-config": DESC_CONFIG},
    "性能状态": {"show processes cpu sorted": DESC_CPU, "show processes memory sorted": DESC_MEM,
                  "show environment": "环境状态(电源/风扇/温度)"},
    "接口状态": {"show ip interface brief": "IP 接口汇总", "show interfaces": "接口详情(错误/丢包)",
                  "show interfaces description": "接口描述"},
    "光模块信息": {"show interfaces transceiver": "光模块诊断(光功率/温度/电压)"},
    "邻居信息": {"show cdp neighbors detail": "CDP 邻居", "show lldp neighbors detail": "LLDP 邻居"},
    "日志与路由": {"show logging": "系统日志", "show ip route summary": "路由表摘要"},
}

CISCO_XR_COMMANDS = {
    "基本信息": {"show version": DESC_VERSION, "show inventory": "硬件清单(序列号)",
                 "show platform": "平台硬件详情(槽位/板卡/模块)",
                 "show running-config": DESC_CONFIG},
    "性能状态": {"show processes cpu": DESC_CPU, "show memory summary": DESC_MEM,
                  "show environment all": "环境状态(电源/风扇/温度)"},
    "接口状态": {"show ip interface brief": "IP 接口汇总", "show interfaces": "接口详情(错误/丢包)",
                  "show interfaces description": "接口描述"},
    "光模块信息": {"show controllers optics all | include \"Port|Tx Power|Rx Power\"": "光模块诊断(光功率/温度/电压)"},
    "邻居信息": {"show lldp neighbors": "LLDP 邻居"},
    "日志与路由": {"show logging": "系统日志", "show route summary": "路由表摘要"},
}

CISCO_NXOS_COMMANDS = {
    "基本信息": {"show version": DESC_VERSION, "show inventory": "硬件清单(序列号)",
                 "show platform": "平台硬件详情(槽位/板卡/模块)",
                 "show running-config": DESC_CONFIG},
    # NX-OS 的 show system resources 同时包含 CPU + 内存, 只需执行一次
    "性能状态": {"show system resources": "系统资源(CPU/内存)"},
    "接口状态": {"show ip interface brief": "IP 接口汇总", "show interface": "接口详情(错误/丢包)",
                  "show interface description": "接口描述"},
    "邻居信息": {"show cdp neighbors": "CDP 邻居", "show lldp neighbors": "LLDP 邻居"},
    "光模块信息": {"show interface transceiver details": "光模块诊断(光功率/温度/电压)"},
    "日志与路由": {"show logging last 200": "系统日志(最近200条)", "show ip route summary": "路由表摘要"},
}

JUNIPER_COMMANDS = {
    "基本信息": {"show version": DESC_VERSION, "show chassis hardware": "硬件清单(序列号)",
                 "show configuration | display set": DESC_CONFIG},
    "性能状态": {"show chassis routing-engine": "CPU/内存(路由引擎)"},
    "接口状态": {"show interfaces terse": "IP 接口汇总", "show interfaces descriptions": "接口描述"},
    "邻居信息": {"show lldp neighbors": "LLDP 邻居"},
    "光模块信息": {"show interfaces diagnostics optics": "光模块诊断(光功率/温度/电压)"},
    "日志与路由": {"show log messages | last 200": "系统日志(最近200条)",
                    "show route summary": "路由表摘要"},
}

HUAWEI_COMMANDS = {
    "基本信息": {"display version": DESC_VERSION, "display device": "硬件清单",
                 "display esn": "设备序列号", "display current-configuration": DESC_CONFIG},
    "性能状态": {"display cpu-usage": DESC_CPU, "display memory-usage": DESC_MEM,
                  "display health": "健康状态(电源/风扇/温度)"},
    "接口状态": {"display ip interface brief": "IP 接口汇总", "display interface brief": "接口简要状态",
                  "display interface": "接口详情(错误/丢包)"},
    "邻居信息": {"display lldp neighbor brief": "LLDP 邻居"},
    "光模块信息": {"display transceiver diagnosis": "光模块诊断(光功率/温度/电压)"},
    "日志与路由": {"display logbuffer": "系统日志", "display ip routing-table statistics": "路由表统计"},
}

FORTINET_COMMANDS = {
    "基本信息": {"get system status": DESC_VERSION, "show full-configuration": DESC_CONFIG},
    "性能状态": {"get system performance status": DESC_CPU},
    "接口状态": {"get system interface physical": "IP 接口汇总",
                  "get system ha status": "HA 高可用状态"},
    "光模块信息": {"get system interface transceiver": "光模块诊断(光功率/温度/电压)"},
    "邻居信息": {"get system lldp neighbors": "LLDP 邻居"},
    "日志与路由": {"get router info routing-table all": "路由表",
                    "get system session status": "会话统计"},
}

H3C_COMMANDS = {
    "基本信息": {"display version": DESC_VERSION, "display device manuinfo": "硬件清单(序列号)",
                 "display current-configuration": DESC_CONFIG},
    "性能状态": {"display cpu-usage": DESC_CPU, "display memory-usage": DESC_MEM,
                  "display environment": "环境状态(电源/风扇/温度)"},
    "接口状态": {"display ip interface brief": "IP 接口汇总", "display interface brief": "接口简要状态",
                  "display interface": "接口详情(错误/丢包)"},
    "光模块信息": {"display transceiver diagnosis": "光模块诊断(光功率/温度/电压)"},
    "邻居信息": {"display lldp neighbor brief": "LLDP 邻居"},
    "日志与路由": {"display logbuffer": "系统日志", "display ip routing-table statistics": "路由表统计"},
}


# ═══════════════════════════ 解析函数 ═══════════════════════════

# --- Cisco IOS ---

def parse_cisco_ios_cpu(output):
    m = re.search(r"CPU utilization.*?five seconds:\s*(\d+)%", output, re.DOTALL)
    return f"{m.group(1)}%" if m else "N/A"

def parse_cisco_ios_mem(output):
    # 格式 1: "Processor Pool Total: 123456 Used: 23456 Free: 100000"
    m = re.search(r"Processor Pool Total:\s*(\d+)\s+Used:\s*(\d+)\s+Free:\s*\d+", output)
    if m:
        t, u = int(m.group(1)), int(m.group(2))
        if t > 0: return f"{u / t * 100:.1f}%"
    # 格式 2: IOS-XE 17.x "Processor memory: 12345678 total, 2345678 used, ..."
    m = re.search(r"Processor memory:\s*(\d+)\s+total,\s*(\d+)\s+used", output)
    if m:
        t, u = int(m.group(1)), int(m.group(2))
        if t > 0: return f"{u / t * 100:.1f}%"
    return "N/A"

def parse_cisco_ios_uptime(output):
    m = re.search(r"uptime is (.+)", output)
    return m.group(1).strip() if m else "N/A"

# --- Cisco XR ---

def parse_cisco_xr_cpu(output):
    m = re.search(r"CPU utilization for five seconds:\s*(\d+)%", output)
    return f"{m.group(1)}%" if m else "N/A"

def parse_cisco_xr_mem(output):
    m = re.search(r"(?:Physical|System)\s+[Mm]emory:\s*(\d+)M?\s*(?:total|MB total).*?(\d+)M?\s*(?:used|MB used)", output, re.DOTALL)
    if m:
        t, u = int(m.group(1)), int(m.group(2))
        if t > 0: return f"{u / t * 100:.1f}%"
    m2 = re.search(r"(?:Physical|System)\s+[Mm]emory:\s*(\d+)M?\s*(?:total|MB).*?(\d+)M?\s*(?:available|free|avail)", output, re.DOTALL)
    if m2:
        t, a = int(m2.group(1)), int(m2.group(2))
        if t > 0: return f"{(t - a) / t * 100:.1f}%"
    return "N/A"

def parse_cisco_xr_uptime(output):
    m = re.search(r"System uptime is (.+)", output)
    return m.group(1).strip() if m else "N/A"

# --- Cisco NX-OS ---

def parse_nxos_cpu(output):
    """从 show system resources 提取 CPU: 'CPU states  : 2.0% user, 3.0% kernel, 95.0% idle' → 100-idle"""
    m = re.search(r"CPU states\s*:.*?(\d+\.?\d*)%\s*idle", output)
    return f"{100 - float(m.group(1)):.1f}%" if m else "N/A"

def parse_nxos_mem(output):
    """从 show system resources 提取内存: 'Memory usage: 4194304K total, 2097152K used, ...'"""
    m = re.search(r"Memory usage:\s*(\d+)K?\s+total,\s*(\d+)K?\s+used", output)
    if m:
        t, u = int(m.group(1)), int(m.group(2))
        if t > 0: return f"{u / t * 100:.1f}%"
    return "N/A"

def parse_nxos_uptime(output):
    """从 show version 提取运行时间 (Nexus 有多种格式)"""
    m = re.search(r"uptime is (.+?)(?:\r?\n|$)", output)
    if m: return m.group(1).strip()
    m = re.search(r"Kernel uptime is (.+?)(?:\r?\n|$)", output)
    if m: return m.group(1).strip()
    return "N/A"

# --- Juniper JunOS ---

def parse_juniper_cpu(output):
    """从 show chassis routing-engine 提取 CPU: 'Idle   92 percent' → 8%"""
    m = re.search(r"Idle\s+(\d+)\s+percent", output)
    return f"{100 - int(m.group(1))}%" if m else "N/A"

def parse_juniper_mem(output):
    """从 show chassis routing-engine 提取内存: 'Memory utilization 25 percent'"""
    m = re.search(r"Memory utilization\s+(\d+)\s+percent", output)
    return f"{m.group(1)}%" if m else "N/A"

def parse_juniper_uptime(output):
    """从 show system uptime 提取: 'System booted: 2026-... (4d 13:30 ago)'"""
    m = re.search(r"System booted:.*?\((.+?) ago\)", output)
    if m: return m.group(1)
    m = re.search(r"uptime.*?:\s*(.+?)(?:\r?\n|$)", output, re.IGNORECASE)
    if m: return m.group(1).strip()
    return "N/A"

# --- Huawei VRP ---

def parse_huawei_cpu(output):
    m = re.search(r"CPU Usage\s*:\s*([\d.]+%)", output)
    return m.group(1) if m else "N/A"

def parse_huawei_mem(output):
    m = re.search(r"Memory (?:utilization|using percentage|using|usage)", output, re.IGNORECASE)
    if m:
        tail = output[m.end():]
        pct_m = re.search(r"([\d.]+%)", tail)
        if pct_m: return pct_m.group(1)
    return "N/A"

def parse_huawei_uptime(output):
    m = re.search(r"System (?:up\s*time|uptime).*?:\s*(.+?)(?:\r?\n|$)", output)
    if m: return m.group(1).strip()
    m = re.search(r"uptime is (.+?)(?:\r?\n|$)", output)
    if m: return m.group(1).strip()
    return "N/A"

# --- Fortinet FortiOS ---

def parse_fortinet_cpu(output):
    """从 get system performance status 提取 CPU: 'CPU states: 2% user ... 98% idle' → 100-idle"""
    m = re.search(r"CPU states:.*?(\d+)% idle", output)
    return f"{100 - int(m.group(1))}%" if m else "N/A"

def parse_fortinet_mem(output):
    """从 get system performance status 提取内存, 兼容 FortiOS 6.x/7.x"""
    # 格式 1: 直接提取百分比 "(23.1%)" — FortiOS 7.x
    m = re.search(r"used\s*\(([\d.]+)%\)", output)
    if m: return f"{m.group(1)}%"
    # 格式 2: 按 total/used 计算 — FortiOS 6.x "Memory states: ... used, ... total"
    m = re.search(r"Memory (?:states:)?.*?(\d+)\s*kB?\s+used.*?(\d+)\s*kB?\s+total", output)
    if m:
        u, t = int(m.group(1)), int(m.group(2))
        if t > 0: return f"{u / t * 100:.1f}%"
    return "N/A"

def parse_fortinet_uptime(output):
    """从 get system status 提取: 'Uptime: 120 days, 5 hours, 30 minutes'"""
    m = re.search(r"Uptime:\s*(.+?)(?:\r?\n|$)", output)
    return m.group(1).strip() if m else "N/A"

# --- H3C Comware ---

def parse_h3c_cpu(output):
    """从 display cpu-usage 提取 CPU: 兼容多种 H3C 输出格式"""
    # 格式 1: "CPU Usage  : 15%" 或 "CPU usage: 15%" (先匹配更精确的模式)
    m = re.search(r"CPU [Uu]sage\s*:\s*([\d.]+%)", output)
    if m: return m.group(1)
    # 格式 2: "5% in last 5 seconds" (H3C 槽位型输出)
    m = re.search(r"(\d+)% in last 5 seconds", output)
    if m: return f"{m.group(1)}%"
    return "N/A"

def parse_h3c_mem(output):
    """从 display memory-usage 提取内存"""
    # 格式 1: "Memory usage: 45%"
    m = re.search(r"Memory usage:\s*([\d.]+%)", output)
    if m: return m.group(1)
    # 格式 2: 与华为格式兼容
    m = re.search(r"Memory (?:utilization|using percentage|using|usage)", output, re.IGNORECASE)
    if m:
        tail = output[m.end():]
        pct_m = re.search(r"([\d.]+%)", tail)
        if pct_m: return pct_m.group(1)
    return "N/A"

def parse_h3c_uptime(output):
    """从 display version 提取运行时间"""
    m = re.search(r"System (?:up\s*time|uptime).*?:\s*(.+?)(?:\r?\n|$)", output)
    if m: return m.group(1).strip()
    m = re.search(r"uptime is (.+?)(?:\r?\n|$)", output)
    if m: return m.group(1).strip()
    return "N/A"


# ═══════════════════════════ 设备配置档案 ═══════════════════════════

DEVICE_PROFILES = {
    "cisco_ios": {
        "name": "Cisco IOS/IOS-XE", "commands": CISCO_IOS_COMMANDS,
        "backup_cmd": "show running-config",
        "cpu_parser": parse_cisco_ios_cpu, "mem_parser": parse_cisco_ios_mem,
        "uptime_parser": parse_cisco_ios_uptime, "hostname_re": r"hostname\s+(\S+)",
    },
    "cisco_xr": {
        "name": "Cisco IOS-XR", "commands": CISCO_XR_COMMANDS,
        "backup_cmd": "show running-config",
        "cpu_parser": parse_cisco_xr_cpu, "mem_parser": parse_cisco_xr_mem,
        "uptime_parser": parse_cisco_xr_uptime, "hostname_re": r"hostname\s+(\S+)",
    },
    "cisco_nxos": {
        "name": "Cisco NX-OS (Nexus)", "commands": CISCO_NXOS_COMMANDS,
        "backup_cmd": "show running-config",
        "cpu_parser": parse_nxos_cpu, "mem_parser": parse_nxos_mem,
        "uptime_parser": parse_nxos_uptime, "hostname_re": r"hostname\s+(\S+)",
        "cpu_mem_single_output": True,   # show system resources 同时产出 CPU+内存
    },
    "juniper": {
        "name": "Juniper JunOS", "commands": JUNIPER_COMMANDS,
        "backup_cmd": "show configuration | display set",
        "cpu_parser": parse_juniper_cpu, "mem_parser": parse_juniper_mem,
        "uptime_parser": parse_juniper_uptime, "hostname_re": r"Hostname:\s*(\S+)",
        "cpu_mem_single_output": True,   # show chassis routing-engine 同时产出 CPU+内存
    },
    "huawei": {
        "name": "Huawei VRP", "commands": HUAWEI_COMMANDS,
        "backup_cmd": "display current-configuration",
        "cpu_parser": parse_huawei_cpu, "mem_parser": parse_huawei_mem,
        "uptime_parser": parse_huawei_uptime, "hostname_re": r"sysname\s+(\S+)",
    },
    "fortinet": {
        "name": "Fortinet FortiOS", "commands": FORTINET_COMMANDS,
        "backup_cmd": "show full-configuration",
        "cpu_parser": parse_fortinet_cpu, "mem_parser": parse_fortinet_mem,
        "uptime_parser": parse_fortinet_uptime, "hostname_re": r"Hostname:\s*(\S+)",
        "cpu_mem_single_output": True,   # get system performance status 同时产出 CPU+内存
    },
    "hp_comware": {
        "name": "H3C Comware", "commands": H3C_COMMANDS,
        "backup_cmd": "display current-configuration",
        "cpu_parser": parse_h3c_cpu, "mem_parser": parse_h3c_mem,
        "uptime_parser": parse_h3c_uptime, "hostname_re": r"sysname\s+(\S+)",
    },
}

# ═══════════════════════════ 工具函数 ═══════════════════════════

def read_devices(filepath):
    devices = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    if lines and any(kw in lines[0].lower() for kw in ("ip", "username", "device_type")):
        print(f"[提示] 检测到 CSV 表头行, 已自动跳过: {lines[0]}")
        lines = lines[1:]
    reader = csv.DictReader(lines, fieldnames=["ip", "username", "password", "port", "device_type"])
    for idx, row in enumerate(reader, start=1):
        try:
            row["port"] = int(row.get("port") or 22)
        except (ValueError, TypeError):
            print(f"[跳过] 第 {idx} 行端口值无效: {row.get('port')!r}, 使用默认 22")
            row["port"] = 22
        missing = [f for f in ["ip", "username", "password", "device_type"] if not row.get(f)]
        if missing:
            print(f"[跳过] 第 {idx} 行缺少必填字段: {missing} -> {row.get('ip', '?')}")
            continue
        if row["device_type"] not in DEVICE_PROFILES:
            print(f"[跳过] 不支持的设备类型: {row['ip']} -> {row['device_type']}")
            continue
        devices.append(row)
    return devices


def backup_config(device_ip, config_output):
    if not config_output:
        print(f"  [{device_ip}] 配置备份跳过: 输出为空")
        return None
    try:
        host = device_ip.replace(".", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{host}_{ts}.cfg"
        filepath = CONFIG_DIR / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(config_output)
        return filepath.name
    except Exception as e:
        print(f"  [{device_ip}] 配置备份写入失败: {e}")
        return None


def connect_with_retry(conn_params, retries=CONN_RETRIES, delay=RETRY_DELAY):
    for attempt in range(1, retries + 1):
        try:
            return ConnectHandler(**conn_params)
        except NetmikoAuthenticationException:
            raise
        except (NetmikoTimeoutException, OSError) as e:
            if attempt < retries:
                print(f"  重试 {attempt}/{retries} — {delay}秒后重连...")
                time.sleep(delay)
            else:
                raise


def extract_hostname(version_output, config_output, hostname_re):
    for output in (version_output, config_output):
        if output:
            m = re.search(hostname_re, output, re.IGNORECASE)
            if m: return m.group(1)
    # 兜底: 从输出结尾提示符提取
    for output in (version_output, config_output):
        if output:
            m = re.search(r"(\S+)[#>]\s*$", output, re.MULTILINE)
            if m:
                candidate = m.group(1)
                if len(candidate) >= 2 and not candidate.isdigit():
                    return candidate
    return "N/A"


def escape_html(text):
    return html_module.escape(text, quote=True)


# ═══════════════════════════ 单设备巡检 ═══════════════════════════

def inspect_device(device_info):
    profile = DEVICE_PROFILES[device_info["device_type"]]
    result = {
        "ip": device_info["ip"], "device_type": device_info["device_type"],
        "device_name": profile["name"], "hostname": "N/A",
        "cpu": "N/A", "memory": "N/A", "uptime": "N/A",
        "status": "error", "error": None, "config_backup": None,
        "sections": {},
    }
    conn_params = {
        "device_type": device_info["device_type"], "host": device_info["ip"],
        "username": device_info["username"], "password": device_info["password"],
        "port": device_info["port"],
        "conn_timeout": CONN_TIMEOUT, "auth_timeout": CONN_TIMEOUT,
        "banner_timeout": CONN_TIMEOUT,
    }
    conn = None
    try:
        print(f"[连接] {device_info['ip']}:{device_info['port']} ({profile['name']})")
        conn = connect_with_retry(conn_params)
        result["status"] = "connected"

        # 执行所有巡检命令
        for category, cmds in profile["commands"].items():
            result["sections"][category] = {}
            for cmd, desc in cmds.items():
                print(f"  [{device_info['ip']}] 执行: {cmd}")
                try:
                    output = conn.send_command(cmd, read_timeout=CMD_TIMEOUT, strip_prompt=False)
                except Exception as e:
                    output = f"[错误] 命令执行失败: {e}"
                result["sections"][category][desc] = output

        # 提取关键指标输出
        version_output = result["sections"].get("基本信息", {}).get(DESC_VERSION, "")
        config_output = result["sections"].get("基本信息", {}).get(DESC_CONFIG, "")

        # NX-OS / Juniper: CPU 和内存来自同一个命令, 复用输出
        cpu_output = result["sections"].get("性能状态", {}).get(DESC_CPU, "")
        if profile.get("cpu_mem_single_output"):
            mem_output = cpu_output   # 复用, 无额外命令
        else:
            mem_output = result["sections"].get("性能状态", {}).get(DESC_MEM, "")

        result["cpu"] = profile["cpu_parser"](cpu_output)
        result["memory"] = profile["mem_parser"](mem_output)
        result["uptime"] = profile["uptime_parser"](version_output)
        # Fortinet 的 Uptime 在 get system performance status 中, 若 version 没提取到则回退
        if result["uptime"] == "N/A" and profile.get("cpu_mem_single_output"):
            result["uptime"] = profile["uptime_parser"](cpu_output)
        result["hostname"] = extract_hostname(version_output, config_output, profile["hostname_re"])

        cfg_file = backup_config(device_info["ip"], config_output)
        if cfg_file:
            result["config_backup"] = cfg_file

    except NetmikoTimeoutException:
        result["status"] = "timeout"
        result["error"] = "连接超时 — 设备不可达或 SSH 端口未开放"
    except NetmikoAuthenticationException:
        result["status"] = "auth_failed"
        result["error"] = "认证失败 — 用户名或密码错误"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        if conn:
            conn.disconnect()
    return result


# ═══════════════════════════ HTML 报告 ═══════════════════════════

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>网络设备巡检报告</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; background: #f0f2f5; color: #333; padding: 20px; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  h1 {{ text-align: center; color: #1a1a2e; margin-bottom: 5px; }}
  .subtitle {{ text-align: center; color: #666; margin-bottom: 30px; font-size: 14px; }}
  .summary {{ background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  .summary h2 {{ margin-bottom: 15px; color: #1a1a2e; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #e8e8e8; font-size: 13px; }}
  th {{ background: #1a1a2e; color: #fff; font-weight: 500; }}
  tr:hover {{ background: #fafafa; }}
  .status-ok {{ color: #52c41a; font-weight: bold; }}
  .status-err {{ color: #f5222d; font-weight: bold; }}
  .device-section {{ background: #fff; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); overflow: hidden; }}
  .device-header {{ background: #1a1a2e; color: #fff; padding: 15px 20px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }}
  .device-header:hover {{ background: #16213e; }}
  .device-header h3 {{ font-size: 16px; }}
  .device-body {{ padding: 20px; }}
  .device-meta {{ display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 20px; }}
  .meta-item {{ background: #f6f8fa; border-radius: 6px; padding: 12px 16px; min-width: 120px; }}
  .meta-item .label {{ font-size: 12px; color: #888; margin-bottom: 4px; }}
  .meta-item .value {{ font-size: 18px; font-weight: 600; color: #1a1a2e; }}
  .category {{ margin-bottom: 15px; }}
  .category-title {{ background: #e6f7ff; color: #1890ff; padding: 8px 12px; border-radius: 4px; font-weight: 600; font-size: 14px; margin-bottom: 8px; cursor: pointer; user-select: none; }}
  .category-title:hover {{ background: #bae7ff; }}
  .category-content {{ display: none; }}
  .category-content.open {{ display: block; }}
  pre {{ background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 4px; overflow-x: auto; font-size: 12px; line-height: 1.5; max-height: 400px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }}
  .cmd-desc {{ font-size: 12px; color: #888; margin-bottom: 5px; }}
  .issues {{ background: #fff1f0; border: 1px solid #ffa39e; border-radius: 4px; padding: 10px 15px; margin-bottom: 15px; }}
  .issues::before {{ content: "⚠ 发现的问题"; display: block; color: #f5222d; font-weight: bold; margin-bottom: 5px; }}
  .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 30px; padding: 20px; }}
</style>
</head>
<body>
<div class="container">
<h1>网络设备巡检报告</h1>
<p class="subtitle">生成时间: {report_time} &nbsp;|&nbsp; 设备总数: {total} &nbsp;|&nbsp; 成功: {success_count} &nbsp;|&nbsp; 失败: {fail_count}</p>
<div class="summary">
<h2>设备概览</h2>
<table>
<thead><tr><th>IP</th><th>主机名</th><th>平台</th><th>CPU</th><th>内存</th><th>运行时间</th><th>状态</th><th>配置备份</th></tr></thead>
<tbody>{summary_rows}</tbody>
</table>
</div>
{device_sections}
<div class="footer">网络设备自动巡检系统 &copy; {year}</div>
</div>
<script>
document.querySelectorAll('.device-header').forEach(function(h) {{
  h.addEventListener('click', function() {{
    var body = this.nextElementSibling;
    body.style.display = body.style.display === 'none' ? 'block' : 'none';
  }});
}});
document.querySelectorAll('.category-title').forEach(function(t) {{
  t.addEventListener('click', function() {{
    var content = this.nextElementSibling;
    content.classList.toggle('open');
  }});
}});
</script>
</body>
</html>"""

STATUS_LABELS = {"connected": "成功", "timeout": "超时", "auth_failed": "认证失败", "error": "异常"}


def generate_report(results, filepath):
    total = len(results)
    success_count = sum(1 for r in results if r["status"] == "connected")
    fail_count = total - success_count
    e = escape_html

    summary_parts = []
    for r in results:
        cls = "status-ok" if r["status"] == "connected" else "status-err"
        st = STATUS_LABELS.get(r["status"], r["status"])
        summary_parts.append(
            f"<tr><td>{e(r['ip'])}</td><td>{e(r['hostname'])}</td><td>{e(r['device_name'])}</td>"
            f"<td>{e(r['cpu'])}</td><td>{e(r['memory'])}</td><td>{e(r['uptime'])}</td>"
            f'<td class="{cls}">{e(st)}</td><td>{e(r["config_backup"] or "-")}</td></tr>'
        )
    summary_rows = "\n".join(summary_parts)

    device_parts = []
    for r in results:
        err = f'<div class="issues">{e(r["error"])}</div>' if r["error"] else ""
        meta = (
            f'<div class="device-meta">'
            f'<div class="meta-item"><div class="label">CPU</div><div class="value">{e(r["cpu"])}</div></div>'
            f'<div class="meta-item"><div class="label">内存</div><div class="value">{e(r["memory"])}</div></div>'
            f'<div class="meta-item"><div class="label">运行时间</div><div class="value" style="font-size:14px;">{e(r["uptime"])}</div></div>'
            f'<div class="meta-item"><div class="label">配置备份</div><div class="value" style="font-size:14px;">{e(r["config_backup"] or "无")}</div></div>'
            f"</div>"
        )
        cat_parts = []
        for cat, cmds in r["sections"].items():
            cmd_parts = []
            for desc, output in cmds.items():
                cmd_parts.append(f'<div class="cmd-desc">▸ {e(desc)}</div><pre>{e(output)}</pre>')
            cat_parts.append(
                f'<div class="category"><div class="category-title">📂 {e(cat)}</div>'
                f'<div class="category-content">{"".join(cmd_parts)}</div></div>'
            )
        icon = "✅" if r["status"] == "connected" else "❌"
        device_parts.append(
            f'<div class="device-section"><div class="device-header">'
            f'<h3>{e(r["ip"])} — {e(r["hostname"])} ({e(r["device_name"])})</h3><span>{icon}</span>'
            f'</div><div class="device-body">{err}{meta}{"".join(cat_parts)}</div></div>'
        )
    device_sections = "\n".join(device_parts)

    html = HTML_TEMPLATE.format(
        report_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total=total, success_count=success_count, fail_count=fail_count,
        summary_rows=summary_rows, device_sections=device_sections,
        year=datetime.now().year,
    )
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)


# ═══════════════════════════ 主流程 ═══════════════════════════

def main():
    if not DEVICES_FILE.exists():
        print(f"[错误] 设备文件不存在: {DEVICES_FILE}")
        print("请创建 devices.csv，格式: ip,username,password,port,device_type")
        print("支持的 device_type: " + ", ".join(DEVICE_PROFILES.keys()))
        sys.exit(1)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    devices = read_devices(DEVICES_FILE)
    if not devices:
        print("[错误] 没有有效的设备条目，请检查 devices.csv")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  网络设备巡检开始 — {len(devices)} 台设备")
    print(f"{'='*60}\n")

    results = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(devices))) as executor:
        future_map = {executor.submit(inspect_device, d): d for d in devices}
        for future in as_completed(future_map):
            try:
                results.append(future.result())
            except Exception as e:
                d = future_map[future]
                results.append({
                    "ip": d["ip"], "device_type": d["device_type"],
                    "device_name": DEVICE_PROFILES.get(d["device_type"], {}).get("name", "?"),
                    "hostname": "N/A", "cpu": "N/A", "memory": "N/A", "uptime": "N/A",
                    "status": "error", "error": f"巡检线程异常: {e}",
                    "config_backup": None, "sections": {},
                })

    def _ip_key(r):
        try: return ipaddress.ip_address(r["ip"])
        except ValueError: return ipaddress.IPv4Address("255.255.255.255")
    results.sort(key=_ip_key)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"inspection_report_{ts}.html"
    generate_report(results, report_path)

    success = sum(1 for r in results if r["status"] == "connected")
    print(f"\n{'='*60}")
    print(f"  巡检完成: 成功 {success}/{len(devices)}")
    for r in results:
        icon = "[OK]" if r["status"] == "connected" else "[FAIL]"
        extra = r.get("error", "") or ""
        print(f"  {icon} {r['ip']:15s} {r['hostname']:15s} CPU:{r['cpu']:>6s}  MEM:{r['memory']:>6s}  {extra}")
    print(f"\n  报告: {report_path}")
    print(f"  配置备份: {CONFIG_DIR}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

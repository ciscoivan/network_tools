# network_tools
# 网络设备巡检系统

Python 多厂商网络设备自动化巡检工具。通过 SSH 连接设备，采集运行状态、性能指标、光模块诊断数据，生成 HTML 报告并备份配置文件。

---

## 环境要求

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Python | **3.8 ~ 3.12** | CPython，推荐 3.10+ |
| netmiko | **4.0.0 ~ 4.5.x** | SSH 多厂商连接库 |
| paramiko | 3.x（netmiko 自动安装） | SSH 协议实现 |
| ntc-templates | （netmiko 自动安装） | TextFSM 解析模板 |
| textfsm | （netmiko 自动安装） | 结构化输出解析 |
| pyyaml | （netmiko 自动安装） | YAML 配置解析 |
| scp | （netmiko 自动安装） | SCP 文件传输 |
| pyserial | （netmiko 自动安装） | 串口连接支持 |

> **测试环境**: Python 3.11.7 + netmiko 4.3.0 + paramiko 3.4.0

---

## 环境完整配置过程

以下从零开始，适用于 **Windows / macOS / Linux** 三平台。

### 第一步：安装 Python

#### Windows

1. 打开 [python.org/downloads](https://www.python.org/downloads/)，下载 **Python 3.10+** 64-bit 安装包
2. 运行安装程序，**务必勾选** `Add Python to PATH`
3. 安装完成后打开 **命令提示符** 或 **PowerShell**，验证：

```powershell
python --version
# Python 3.11.7

pip --version
# pip 24.0
```

#### macOS

```bash
# 方式一: 官方安装包 (python.org)
# 下载 .pkg 文件双击安装即可

# 方式二: Homebrew (推荐)
brew install python@3.11

# 验证
python3 --version
pip3 --version
```

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y

# 验证
python3 --version
pip3 --version
```

### 第二步：创建虚拟环境（推荐）

虚拟环境可以隔离项目依赖，避免与系统其他 Python 项目冲突。

```bash
# 进入项目目录
cd network-inspection

# 创建虚拟环境
python -m venv venv
# Windows: python -m venv venv
# macOS/Linux: python3 -m venv venv

# 激活虚拟环境
# Windows (命令提示符):
venv\Scripts\activate
# Windows (PowerShell):
venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate

# 激活成功后，终端前缀会显示 (venv)
# (venv) C:\network-inspection>
```

### 第三步：安装依赖

```bash
# 确保虚拟环境已激活 (终端前缀有 (venv))

# 方式一: 一键安装 (推荐)
pip install -r requirements.txt

# 方式二: 手动安装
pip install netmiko
# 依赖 paramiko / scp / pyserial / PyYAML / textfsm / ntc-templates 自动安装

# 验证安装
python -c "import netmiko; print('netmiko', netmiko.__version__)"
# netmiko 4.3.0
```

### `requirements.txt` 内容

| 模块 | 版本范围 | 说明 |
|------|---------|------|
| `netmiko` | ≥4.0.0, <5.0.0 | SSH 多厂商网络设备连接库（核心） |
| `paramiko` | ≥3.0.0, <4.0.0 | SSHv2 协议实现（netmiko 底层依赖） |
| `scp` | ≥0.14.0 | SCP 文件传输 |
| `pyserial` | ≥3.5 | 串口连接支持 |
| `PyYAML` | ≥6.0 | YAML 配置解析 |
| `textfsm` | ≥1.1.0 | 结构化 CLI 输出解析 |
| `ntc-templates` | ≥3.0.0 | TextFSM 解析模板库 |

> **测试通过版本**: Python 3.11.7 · netmiko 4.3.0 · paramiko 3.4.0 · scp 0.15.0 · pyserial 3.5 · textfsm 1.1.3 · ntc-templates 5.1.0

### 第四步：编辑设备清单

用文本编辑器（VS Code / Notepad++ / vim）打开 `devices.csv`：

```csv
# device_type:  cisco_ios | cisco_xr | cisco_nxos | juniper | huawei | hp_comware | fortinet
# 格式: ip,username,password,port,device_type
192.168.1.1,admin,cisco123,22,cisco_ios
192.168.1.2,admin,Admin@123,22,huawei
```

### 第五步：运行

```bash
python inspection.py
```

### 退出虚拟环境

```bash
deactivate
```

---

## 一键安装脚本

### Windows (PowerShell)

```powershell
# 以管理员身份运行 PowerShell，执行:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
# 然后 cd 到项目目录，执行:
python -m venv venv
venv\Scripts\Activate.ps1
pip install netmiko
python inspection.py
```

### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
pip install netmiko
python inspection.py
```

---

## 快速开始

### 1. 编辑 `devices.csv`

```csv
# device_type:  cisco_ios | cisco_xr | cisco_nxos | juniper | huawei | hp_comware | fortinet
# 格式: ip,username,password,port,device_type
192.168.1.1,admin,cisco123,22,cisco_ios
192.168.1.2,admin,juniper9,22,juniper
192.168.1.3,admin,Admin@123,22,huawei
192.168.1.4,admin,password,22,fortinet
192.168.1.100,admin,pass,22,hp_comware
```

- `#` 开头 = 注释，自动跳过
- 带 `ip`, `username` 关键字的表头行自动跳过
- 端口为空自动补 `22`，无效端口回退 `22`
- 不支持的类型打印 `[跳过]` 提示，不会中断巡检
- **UTF-8 BOM** 自动处理（Windows 记事本/Excel 导出的 CSV 可直接使用）

### 2. 运行

```bash
python inspection.py
```

### 3. 查看结果

```
reports/inspection_report_20260604_221852.html   ← 浏览器打开
configs/172_16_1_1_20260604_221852.cfg            ← 配置备份
```

---

## 支持的平台

| device_type | 平台 | 厂商 | 命令数 |
|---|---|---|---|
| `cisco_ios` | Cisco IOS / IOS-XE | Cisco | 13 |
| `cisco_xr` | Cisco IOS-XR | Cisco | 12 |
| `cisco_nxos` | Cisco NX-OS (Nexus) | Cisco | 12 |
| `juniper` | Juniper JunOS | Juniper | 10 |
| `huawei` | Huawei VRP | 华为 | 13 |
| `hp_comware` | H3C Comware | H3C | 12 |
| `fortinet` | Fortinet FortiOS | Fortinet | 9 |

---

## 各平台巡检命令

### Cisco IOS / IOS-XE (`cisco_ios`)

| 类别 | 命令 |
|---|---|
| 基本信息 | `show version` `show inventory` `show platform` `show running-config` |
| 性能状态 | `show processes cpu sorted` `show processes memory sorted` `show environment` |
| 接口状态 | `show ip interface brief` `show interfaces` `show interfaces description` |
| 光模块信息 | `show interfaces transceiver` |
| 邻居信息 | `show cdp neighbors detail` `show lldp neighbors detail` |
| 日志与路由 | `show logging` `show ip route summary` |

### Cisco IOS-XR (`cisco_xr`)

| 类别 | 命令 |
|---|---|
| 基本信息 | `show version` `show inventory` `show platform` `show running-config` |
| 性能状态 | `show processes cpu` `show memory summary` `show environment all` |
| 接口状态 | `show ip interface brief` `show interfaces` `show interfaces description` |
| 光模块信息 | `show controllers optics all \| include "Port\|Tx Power\|Rx Power"` |
| 邻居信息 | `show lldp neighbors` |
| 日志与路由 | `show logging` `show route summary` |

### Cisco NX-OS / Nexus (`cisco_nxos`)

| 类别 | 命令 |
|---|---|
| 基本信息 | `show version` `show inventory` `show platform` `show running-config` |
| 性能状态 | `show system resources` |
| 接口状态 | `show ip interface brief` `show interface` `show interface description` |
| 光模块信息 | `show interface transceiver details` |
| 邻居信息 | `show cdp neighbors` `show lldp neighbors` |
| 日志与路由 | `show logging last 200` `show ip route summary` |

### Juniper JunOS (`juniper`)

| 类别 | 命令 |
|---|---|
| 基本信息 | `show version` `show chassis hardware` `show configuration \| display set` |
| 性能状态 | `show chassis routing-engine` |
| 接口状态 | `show interfaces terse` `show interfaces descriptions` |
| 光模块信息 | `show interfaces diagnostics optics` |
| 邻居信息 | `show lldp neighbors` |
| 日志与路由 | `show log messages \| last 200` `show route summary` |

### Huawei VRP (`huawei`)

| 类别 | 命令 |
|---|---|
| 基本信息 | `display version` `display device` `display esn` `display current-configuration` |
| 性能状态 | `display cpu-usage` `display memory-usage` `display health` |
| 接口状态 | `display ip interface brief` `display interface brief` `display interface` |
| 光模块信息 | `display transceiver diagnosis` |
| 邻居信息 | `display lldp neighbor brief` |
| 日志与路由 | `display logbuffer` `display ip routing-table statistics` |

### H3C Comware (`hp_comware`)

| 类别 | 命令 |
|---|---|
| 基本信息 | `display version` `display device manuinfo` `display current-configuration` |
| 性能状态 | `display cpu-usage` `display memory-usage` `display environment` |
| 接口状态 | `display ip interface brief` `display interface brief` `display interface` |
| 光模块信息 | `display transceiver diagnosis` |
| 邻居信息 | `display lldp neighbor brief` |
| 日志与路由 | `display logbuffer` `display ip routing-table statistics` |

### Fortinet FortiOS (`fortinet`)

| 类别 | 命令 |
|---|---|
| 基本信息 | `get system status` `show full-configuration` |
| 性能状态 | `get system performance status` |
| 接口状态 | `get system interface physical` `get system ha status` |
| 光模块信息 | `get system interface transceiver` |
| 邻居信息 | `get system lldp neighbors` |
| 日志与路由 | `get router info routing-table all` `get system session status` |

---

## 输出结构

```
inspection/
├── inspection.py          # 主程序
├── devices.csv            # 设备清单
├── README.md
├── reports/               # HTML 巡检报告
│   └── inspection_report_20260604_221852.html
└── configs/               # 设备运行配置备份
    ├── 172_16_1_1_20260604_221852.cfg
    ├── 172_16_1_5_20260604_221852.cfg
    └── 192_168_55_2_20260604_221852.cfg
```

### HTML 报告内容

| 区域 | 内容 |
|------|------|
| **设备概览表** | IP、主机名、平台、CPU、内存、运行时间、状态、配置备份 |
| **元数据卡片** | CPU / 内存 / 运行时间 / 配置备份 四大指标 |
| **基本信息** | 版本、硬件清单、平台详情、运行配置 |
| **性能状态** | CPU 使用率、内存使用率、环境状态 |
| **接口状态** | IP 接口汇总、接口详情（含错误/丢包计数） |
| **光模块信息** | 收发光功率、温度、电压等 DOM 诊断数据 |
| **邻居信息** | CDP / LLDP 邻居表 |
| **日志与路由** | 系统日志、路由表摘要 |
| **异常高亮** | 红色卡片醒目展示连接/认证/超时等错误 |

> 所有面板支持**点击折叠/展开**，设备详情可整块折叠。

---

## 配置参数

在 [inspection.py](inspection.py) 顶部：

```python
MAX_WORKERS  = 10     # SSH 最大并发数
CONN_TIMEOUT = 30     # 连接超时 (秒)
CMD_TIMEOUT  = 60     # 命令执行超时 (秒)
CONN_RETRIES = 2      # 连接失败重试次数
RETRY_DELAY  = 3      # 重试间隔 (秒)
```

> **重试策略**: 超时 / DNS / socket 错误自动重试；**认证失败不重试**（避免触发账户锁定）。

---

## 新增平台

三步添加一个新平台（以添加 `new_os` 为例）：

### 1. 定义命令集

```python
NEW_OS_COMMANDS = {
    "基本信息": {"show version": DESC_VERSION, "show running-config": DESC_CONFIG},
    "性能状态": {"show system resources": DESC_CPU},
    "接口状态": {"show ip interface brief": "IP 接口汇总"},
    "光模块信息": {"show optics": "光模块诊断"},
    "邻居信息": {"show lldp neighbors": "LLDP 邻居"},
    "日志与路由": {"show logging": "系统日志"},
}
```

### 2. 编写解析器（至少 3 个，空输入必须返回 `"N/A"`）

```python
def parse_new_cpu(output):
    m = re.search(r"CPU:\s*(\d+)%", output)
    return f"{m.group(1)}%" if m else "N/A"

def parse_new_mem(output):
    m = re.search(r"Memory:\s*(\d+)%", output)
    return f"{m.group(1)}%" if m else "N/A"

def parse_new_uptime(output):
    m = re.search(r"Uptime:\s*(.+?)(?:\r?\n|$)", output)
    return m.group(1).strip() if m else "N/A"
```

### 3. 注册档案

```python
DEVICE_PROFILES["new_os"] = {
    "name": "NewOS",
    "commands": NEW_OS_COMMANDS,
    "backup_cmd": "show running-config",
    "cpu_parser": parse_new_cpu,
    "mem_parser": parse_new_mem,
    "uptime_parser": parse_new_uptime,
    "hostname_re": r"hostname\s+(\S+)",
    # 如果 CPU 和内存来自同一条命令:
    "cpu_mem_single_output": True,
}
```

---

## 常见问题

**Q: 连接超时？**
A: 检查 IP 可达 (`ping`) 和 SSH 端口 (`telnet ip 22`)；可调大 `CONN_TIMEOUT`。

**Q: 认证失败？**
A: 确认用户名密码正确；认证失败**不会重试**（防锁定）。

**Q: CPU/内存/运行时间显示 N/A？**
A: 解析器正则未命中输出格式。手动 SSH 登录执行对应命令，用 Python 测试正则：

```python
import re
output = "CPU states: 2.0% user, 3.0% kernel, 95.0% idle"
m = re.search(r"CPU states:.*?(\d+\.?\d*)%\s*idle", output)
print(f"CPU = {100 - float(m.group(1)):.1f}%" if m else "N/A")
```

**Q: 支持 telnet 吗？**
A: 默认 SSH。需 telnet 时修改 `device_type` 为 `cisco_ios_telnet` 等，端口改为 `23`。

**Q: CSV 乱码或第一台设备 IP 异常？**
A: 已自动处理 UTF-8 BOM（`utf-8-sig`），Windows 记事本/Excel 导出的 CSV 可直接使用。

**Q: 如何只巡检部分设备？**
A: 用 `#` 注释掉不需要的行，或创建多个 CSV 文件切换使用。也可直接编辑 `devices.csv`。

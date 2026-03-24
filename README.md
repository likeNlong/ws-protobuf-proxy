# 🔌 WS-Protobuf-Proxy









> **让 Burp Suite 像看 JSON 一样看 WebSocket Protobuf 流量**





<img src="https://mc-imgup.oss-cn-beijing.aliyuncs.com/%E6%89%AB%E7%A0%81_%E6%90%9C%E7%B4%A2%E8%81%94%E5%90%88%E4%BC%A0%E6%92%AD%E6%A0%B7%E5%BC%8F-%E6%A0%87%E5%87%86%E8%89%B2%E7%89%88.png" alt="扫码_搜索联合传播样式-标准色版" style="zoom: 25%;" />



Cursor Agent Skill —— 自动从前端代码 ZIP 中提取 Protobuf 定义，生成双层 mitmproxy 代理脚本，Protobuf ↔ JSON 实时互转，Burp 中直接查看、编辑、重放。



---

## 🤔 解决什么问题



WebSocket + Protobuf 是游戏/IM/实时应用的常见方案，但 Burp 里只能看到一坨二进制——看不懂、改不了、测不动。

本工具在客户端和 Burp 之间插入两层 mitmproxy，自动双向转换，Burp 中全程 JSON 明文。



## 🏗️ 架构

```
APP ──(PB)──> mitmproxy_A [:8888] ──(JSON)──> Burp Suite ──(JSON)──> mitmproxy_B [:9999] ──(PB)──> 服务器
```

| 节点 | 端口 | 职责 |
|------|------|------|
| **mitmproxy_A** | 8888 | 上游指向 Burp，PB↔JSON 互转 |
| **mitmproxy_B** | 9999 | 直连服务器，JSON↔PB 互转 |



## ⚠️ 前置准备



### 1️⃣ 安装依赖

```bash
pip install mitmproxy grpcio-tools protobuf
```



### 2️⃣ 证书！证书！证书！

这是最关键的一步：

- 运行一次 `mitmdump` 自动生成 CA 证书（位于 `~/.mitmproxy/`）
- **mitmproxy 证书** + **Burp 证书** 都要装到电脑和手机
- 别忘记处理证书信任（Android 7+ 需 root 装系统证书）

### 3️⃣ 启动 Burp Suite

确保 Burp 已监听代理端口（如 `127.0.0.1:8080`）。

## 🚀 使用方法

### Step 1：获取 Skill

```bash
git clone <repo-url> ~/.cursor/skills/ws-protobuf-proxy
```

### Step 2：调用 Skill

在 Cursor Agent 对话中引用 skill，给出两个参数：

```
/ws-protobuf-proxy

前端代码包：https://example.com/game-frontend.zip
Burp代理地址：127.0.0.1:8080
```



| 参数 | 说明 | 示例 |
|------|------|------|
| **ZIP 地址** | 前端代码下载链接 | `https://example.com/frontend.zip` |
| **Burp 代理地址** | Burp 监听的 host:port | `127.0.0.1:8080` |

### Step 3：等待自动生成

开启自动授权的话几乎不用管，最终产出 **3 个文件**：

| 文件 | 说明 |
|------|------|
| `*.proto` | 还原的 Protobuf 定义 |
| `*.md` | 消息结构说明文档 |
| `auto_proxy.py` | 一键启动双层代理的主控脚本 |

### Step 4：启动代理

```bash
python auto_proxy.py
```

会自动编译 proto、生成代理脚本、启动 8888 和 9999 两个端口。

### Step 5：配置代理链路

```
APP → :8888 → Burp → :9999 → 服务器
```

1. 📱 **客户端/APP 代理** → `127.0.0.1:8888`
2. 🔧 **Burp 上游代理**（Upstream Proxy）→ `127.0.0.1:9999`
3. 👀 打开 Burp **WebSocket History**，看到 JSON 明文，开测！

## ❓ 常见问题

**端口 8888/9999 被占用？** → 改 `auto_proxy.py` 顶部的 `PORT_A` / `PORT_B`

**证书错误 / SSL 握手失败？** → 确认两套证书都已安装并信任，Android 7+ 需装系统证书，脚本已默认 `--ssl-insecure`

## 📁 文件结构

```
ws-protobuf-proxy/
├── SKILL.md          # Skill 定义（Agent 读取）
├── auto_proxy.py     # 代理主控脚本模板
├── reference.md      # Proto 提取参考指南
└── README.md         # 本文档
```

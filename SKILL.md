---
name: ws-protobuf-proxy
description: 解决WebSocket+Protobuf在Burp Suite中二进制数据难以查看编辑的问题。从前端代码ZIP中自动分析提取.proto定义，生成双mitmproxy代理链脚本实现Protobuf与JSON自动互转，使Burp中流量变为可读可编辑的JSON明文。当用户提到WS protobuf抓包、protobuf Burp代理、WebSocket二进制协议分析、proto明文转换时触发。用户必须提供两个参数：前端代码ZIP地址和Burp代理地址。
---

# WS + Protobuf Burp 明文代理方案

## 架构

```
客户端 →(PB)→ mitmproxy_A[8888] →(JSON)→ Burp[用户指定端口] →(JSON)→ mitmproxy_B[9999] →(PB)→ 服务器
响应方向相反，同样经过双层转换，Burp中始终看到可编辑的JSON
```

- **mitmproxy_A (c_burp.py)**：监听8888，上游指向Burp。客户端请求PB→JSON，Burp响应JSON→PB
- **mitmproxy_B (s_server.py)**：监听9999，直连服务器。Burp请求JSON→PB，服务器响应PB→JSON

## ⚠️ 最高优先级：错误处理规则

**在整个执行过程中，遇到任何错误、异常、不确定的情况时：**

1. **立即停止**操作
2. 向用户清晰说明：发生了什么、可能的原因、建议的解决方案
3. **等待用户审批**同意后才能继续下一步
4. **绝不**自行猜测、产生幻觉或尝试未经确认的修复



## 参数校验

用户**必须**提供两个参数，缺一不可。如果缺少任何一个（分析用户是否给了两个参数值，用户可能不会非常严谨的说明，可能用户就给了个代理地址和zip链接过来，这个判断你不要太死板），**立即中断并提醒用户补充**：

| 参数 | 说明 | 示例 |
|------|------|------|
| **ZIP地址** | 前端代码下载链接 | `https://example.com/game-frontend.zip` |
| **Burp代理地址** | Burp Suite监听的 host:port | `127.0.0.1:8080` 或 `192.168.1.11:8080` |

## 执行流程

以下所有操作在用户当前工作目录（称为 now）中进行，如果在分析过程中你需要依赖一些脚本文件以及下载一些zip包和解压文件，那么你需要在now目录下创建一个cache目录将那些工作中产生的文件放在里面（放进去就可以，工作完成不需要清理），保持now目录下干净整洁，最后now目录下的文件仅仅只有3个：proto文件、md说明文档、auto_proxy.py

### Step 1: 检查Python依赖

```bash
pip show mitmproxy grpcio-tools protobuf
```

如有缺失，向用户说明缺少哪些包，询问是否自动安装：
```bash
pip install mitmproxy grpcio-tools protobuf
```

### Step 2: 下载ZIP到当前目录

```bash
curl -L -o source.zip "<ZIP_URL>"
```

如果 curl 不可用，使用 Python：
```python
import urllib.request
urllib.request.urlretrieve("<ZIP_URL>", "source.zip")
```

下载完成后验证文件存在且大小合理。

### Step 3: 解压到 code/ 子目录

在当前目录创建 `code/` 子目录并解压：

```python
import zipfile, os
os.makedirs("code", exist_ok=True)
zipfile.ZipFile("source.zip").extractall("code")
```

### Step 4: 分析前端代码，提取Proto定义并生成md文档

**核心步骤，利用自身分析能力完成，不要使用固定脚本。**

**流程：**

1. **搜索 `code/` 中的protobuf相关文件**
   - 搜索关键词：`protobuf`, `proto`, `Writer`, `Reader`, `encode`, `decode`, `$root`, `jspb`, `serialize`, `Message`
   - 优先搜索文件类型：`.proto`, `.js`, `.ts`, `.json`

2. **如果直接找到 `.proto` 文件 → 优先使用，复制到当前目录，跳到 Step 5**

3. **否则，分析前端JS代码提取protobuf定义**
   - 详细的库识别方法和提取技巧见 [reference.md](reference.md)
   - 需要提取：所有 message 定义（名称、字段名、类型、编号）、所有 enum 定义、package 名称

4. **重建为标准 `.proto` 文件**，使用 `syntax = "proto3";`，保存到当前目录

5. 在now目录生成一个md文档，将分析出来的当前所有消息保存在md文档里，用于辅助用户后续的使用


### Step 5: 拷贝 auto_proxy.py

从本skill资源目录拷贝 `auto_proxy.py` 到当前工作目录：

```python
import shutil
# skill_dir 就是本 SKILL.md 所在的目录
shutil.copy("<skill_dir>/auto_proxy.py", "./auto_proxy.py")
```

**关键约束：后续所有修改只操作当前目录的副本，绝不修改skill资源目录的原始文件。**

### Step 6: 分析信封结构

从 `.proto` 文件中识别**信封（envelope）消息**。

**信封消息的特征：**
- 包含一个**数值字段**作为消息类型ID（如 `msg_no`, `cmd`, `cmd_id`, `type`, `opcode`）
- 包含一个 **bytes 字段**作为内层载荷（如 `data`, `body`, `payload`）
- 可能包含元数据字段（时间戳、用户ID、序列号等）
- 是 WebSocket 通信中最外层直接序列化/反序列化的消息

**根据分析结果判断信封模式：**

#### 模式A：单信封
请求和响应共用一个信封消息（如 `Packet`, `Frame`, `Message`）。
→ 仅需修改信封名称和字段引用。

#### 模式B：双信封
请求和响应使用不同的信封消息（如 `RequestPacket`/`ResponsePacket`, `C2SPacket`/`S2CPacket`）。
→ 需要较大改动，按消息方向使用不同信封：

| 代码位置 | 方向 | 使用的信封 |
|----------|------|-----------|
| ScriptA `from_client` | App→Burp | 请求信封（解码） |
| ScriptA `else` | Burp→App | 响应信封（编码） |
| ScriptB `from_client` | Burp→Server | 请求信封（编码） |
| ScriptB `else` | Server→Burp | 响应信封（解码） |

#### 模式C：其他模式
→ **停下来**，向用户展示检测到的结构，讨论适配方案后再继续。

### Step 7: 修改 auto_proxy.py

根据 Step 6 的分析结果，修改**当前目录**中的 `auto_proxy.py` 副本。

**必改项：**

| 修改点 | 说明 |
|--------|------|
| `PROTO_FILE` | 改为实际 proto 文件名 |
| `BURP_PROXY` | 改为用户提供的 Burp 代理地址 |
| `ENVELOPE` | 改为实际信封名。双信封模式则拆分为 `ENVELOPE_REQ` 和 `ENVELOPE_RESP` |
| 模板中字段引用 | `msg_no`, `data`, `unix_milli`, `user_id` 等改为实际字段名 |
| `extract_mappings()` | 适配实际的消息枚举名（如 `CmdId` 而非 `MsgNo`）、枚举值前缀、属性提取逻辑 |

**双信封或其他模式额外修改：**

| 修改点 | 说明 |
|--------|------|
| `generate_scripts()` 模板 | ScriptA/ScriptB 中根据方向使用不同信封类 |
| JSON结构 | `burp_json` 中的字段名适配各信封的实际字段 |
| `ENVELOPE` 变量 | 拆分为 `ENVELOPE_REQ` / `ENVELOPE_RESP` |

### Step 8: 结束

当你生成脚本后，一定不要自己去运行，这个交给用户自己在客户端运行



工作完成后后向用户说明代理配置方式并提醒用户注意mitm证书问题：

```
✅ 脚本已生成

1. 客户端/App代理设置 → 127.0.0.1:8888（mitmproxy_A）
2. Burp Suite 上游代理设置 → 127.0.0.1:9999（mitmproxy_B）
3. 完整链路：App → A(8888) → Burp → B(9999) → 目标服务器

现在在Burp的WebSocket History中可以看到JSON明文，并可直接编辑后转发。
```

## 注意事项

- 用户可能需要安装mitmproxy的CA证书才能代理HTTPS流量
- 如果目标使用WSS（WebSocket over TLS），mitmproxy的 `--ssl-insecure` 参数已在脚本中设置
- 端口8888和9999如果被占用，需在脚本中调整 `PORT_A` 和 `PORT_B`

import os
import sys
import subprocess
import re
import time

# ==========================================
# 核心配置区python
# ==========================================
PROTO_FILE = "fishing.proto"  # 你保存的新 proto 文件名
BURP_PROXY = "192.168.1.11:8080"  # Burp Suite 的代理地址
PORT_A = 8888  # 节点A 端口
PORT_B = 9999  # 节点B 端口
ENVELOPE = "Packet"  # 统一的外壳名称


# ==========================================

def compile_proto(proto_filename):
    print(f"[*] 正在编译 Protobuf 文件: {proto_filename}")
    if not os.path.exists(proto_filename):
        print(f"[!] 找不到文件 {proto_filename}，请检查路径！")
        sys.exit(1)

    cmd = [sys.executable, "-m", "grpc_tools.protoc", "-I.", f"--python_out=.", proto_filename]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("[!] Protoc 编译失败:\n", result.stderr)
        sys.exit(1)

    pb2_name = proto_filename.replace(".proto", "_pb2")
    print(f"[+] 编译成功，生成 {pb2_name}.py")
    return pb2_name


def extract_mappings(proto_filename):
    """新版智能路由：直接提取 MsgNo_ 后面的名字作为类名，单字典映射"""
    with open(proto_filename, "r", encoding="utf-8") as f:
        content = f.read()

    enum_match = re.search(r'enum\s+MsgNo\s*\{([^}]+)\}', content)
    if not enum_match: return "{}"

    msg_entries = []
    for line in enum_match.group(1).split('\n'):
        # 匹配: MsgNo_FishingLoginC2S = 655386;
        match = re.search(r'(MsgNo_([a-zA-Z0-9_]+))\s*=\s*(\d+)', line)
        if match:
            _, msg_name, msg_id = match.groups()
            msg_entries.append(f"    {msg_id}: getattr(pb, '{msg_name}', None)")
    return "{\n" + ",\n".join(msg_entries) + "\n}"


def generate_scripts(pb2_name, map_str):
    print("[*] 正在生成新版代理脚本 c_burp.py 和 s_server.py...")

    base_template = f"""import json
import base64
from mitmproxy import http, ctx
import {pb2_name} as pb
from google.protobuf.json_format import MessageToDict, ParseDict

MSG_MAP_RAW = {map_str}
# 过滤掉 proto 里未定义的类
MSG_MAP = {{k: v for k, v in MSG_MAP_RAW.items() if v is not None}}

def decode_payload(msg_no, data_bytes):
    if not data_bytes: return {{}}
    if msg_no in MSG_MAP:
        try:
            inner = MSG_MAP[msg_no]()
            inner.ParseFromString(data_bytes)
            return MessageToDict(inner, preserving_proto_field_name=True)
        except Exception as e:
            ctx.log.error(f"❌ 解析 payload 失败 (MsgNo: {{msg_no}}): {{e}}")
    return {{"__raw_b64__": base64.b64encode(data_bytes).decode('utf-8')}}

def encode_payload(msg_no, payload_dict):
    if "__raw_b64__" in payload_dict:
        return base64.b64decode(payload_dict["__raw_b64__"])
    if msg_no in MSG_MAP:
        inner = MSG_MAP[msg_no]()
        ParseDict(payload_dict, inner)
        return inner.SerializeToString()
    return b""
"""

    script_a = base_template + f"""
class ScriptA:
    def websocket_message(self, flow: http.HTTPFlow):
        if not flow.websocket: return
        message = flow.websocket.messages[-1]

        if message.from_client:
            # App -> Burp
            if isinstance(message.content, bytes):
                try:
                    print('分析')
                    outer = pb.{ENVELOPE}()
                    outer.ParseFromString(message.content)
                    burp_json = {{
                        "direction": "request",
                        "msg_no": outer.msg_no,
                        "unix_milli": outer.unix_milli,
                        "user_id": outer.user_id,
                        "payload": decode_payload(outer.msg_no, outer.data)
                    }}
                    message.content = json.dumps(burp_json, ensure_ascii=False, indent=2).encode("utf-8")
                    ctx.log.info(f"✅ [App->Burp] 请求解包成功 | MsgNo: {{outer.msg_no}}")
                except Exception as e:
                    ctx.log.error(f"❌ [App->Burp] 外壳解析崩溃: {{e}}")
        else:
            # Burp -> App
            try:
                burp_json = json.loads(message.content.decode("utf-8"))
                outer = pb.{ENVELOPE}()
                outer.msg_no = burp_json.get("msg_no", 0)
                outer.unix_milli = burp_json.get("unix_milli", 0)
                outer.user_id = burp_json.get("user_id", "")
                outer.data = encode_payload(outer.msg_no, burp_json.get("payload", {{}}))
                message.content = outer.SerializeToString()
                ctx.log.info(f"✅ [Burp->App] 响应还原成功 | MsgNo: {{outer.msg_no}}")
            except Exception as e:
                ctx.log.error(f"❌ [Burp->App] JSON还原PB崩溃: {{e}}")

addons = [ScriptA()]
"""

    script_b = base_template + f"""
class ScriptB:
    def websocket_message(self, flow: http.HTTPFlow):
        if not flow.websocket: return
        message = flow.websocket.messages[-1]

        if message.from_client:
            # Burp -> Server
            try:
                burp_json = json.loads(message.content.decode("utf-8"))
                outer = pb.{ENVELOPE}()
                outer.msg_no = burp_json.get("msg_no", 0)
                outer.unix_milli = burp_json.get("unix_milli", 0)
                outer.user_id = burp_json.get("user_id", "")
                outer.data = encode_payload(outer.msg_no, burp_json.get("payload", {{}}))
                message.content = outer.SerializeToString()
                ctx.log.info(f"✅ [Burp->Server] 发往服务器 | MsgNo: {{outer.msg_no}}")
            except Exception as e:
                ctx.log.error(f"❌ [Burp->Server] 还原并发送给服务器崩溃: {{e}}")
        else:
            # Server -> Burp
            if isinstance(message.content, bytes):
                try:
                    outer = pb.{ENVELOPE}()
                    outer.ParseFromString(message.content)
                    burp_json = {{
                        "direction": "response",
                        "msg_no": outer.msg_no,
                        "unix_milli": outer.unix_milli,
                        "user_id": outer.user_id,
                        "payload": decode_payload(outer.msg_no, outer.data)
                    }}
                    message.content = json.dumps(burp_json, ensure_ascii=False, indent=2).encode("utf-8")
                    ctx.log.info(f"✅ [Server->Burp] 响应解包成功 | MsgNo: {{outer.msg_no}}")
                except Exception as e:
                    ctx.log.error(f"❌ [Server->Burp] 服务器响应解壳崩溃: {{e}}")

addons = [ScriptB()]
"""
    with open("c_burp.py", "w", encoding="utf-8") as f: f.write(script_a)
    with open("s_server.py", "w", encoding="utf-8") as f: f.write(script_b)
    print("[+] 脚本生成完成。")


def start_proxies():
    print(f"[*] 启动节点 A (监听 {PORT_A}, 上游 -> {BURP_PROXY}) ...")
    proc_a = subprocess.Popen(
        ["mitmdump", "-p", str(PORT_A), "--mode", f"upstream:http://{BURP_PROXY}", "--ssl-insecure", "-s", "c_burp.py"])
    time.sleep(1)
    print(f"[*] 启动节点 B (监听 {PORT_B}, 直接连接外网) ...")
    proc_b = subprocess.Popen(["mitmdump", "-p", str(PORT_B), "--ssl-insecure", "-s", "s_server.py"])
    return proc_a, proc_b


if __name__ == "__main__":
    os.system('cls' if os.name == 'nt' else 'clear')
    print("🚀 Protobuf V2 (单字典外壳版) 主控系统启动")

    pb2_name = compile_proto(PROTO_FILE)
    map_str = extract_mappings(PROTO_FILE)
    generate_scripts(pb2_name, map_str)

    proc_a, proc_b = start_proxies()

    try:
        proc_a.wait()
        proc_b.wait()
    except KeyboardInterrupt:
        print("\n[*] 正在安全终止进程...")
        proc_a.terminate()
        proc_b.terminate()
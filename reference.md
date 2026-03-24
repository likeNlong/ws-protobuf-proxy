# Proto提取参考指南

从前端代码中识别和提取Protobuf消息定义的详细方法。

## 搜索策略

### 第一步：快速定位protobuf文件

在 `code/` 中搜索：

```
优先搜索的文件名模式：
*.proto, *proto*.js, *pb*.js, *protobuf*.js, *message*.js
index.js, bundle.js, app.js, main.js, game.js
```

搜索关键词：
- 高优先级：`protobuf`, `.proto`, `$root`, `Writer`, `Reader`, `jspb.Message`
- 中优先级：`encode`, `decode`, `serialize`, `deserialize`, `ParseFromString`
- 低优先级：`message`, `packet`, `payload`, `envelope`

### 第二步：确定protobuf库类型

根据代码特征判断前端使用的protobuf库。

## 常见库及代码特征

### 1. protobuf.js（最常见）

**特征A：JSON Descriptor 模式**

```javascript
var $root = protobuf.Root.fromJSON({
    nested: {
        packet: {
            nested: {
                MsgNo: {
                    values: {
                        Def: 0,
                        MsgNo_LoginC2S: 100,
                        MsgNo_LoginS2C: 101
                    }
                },
                Packet: {
                    fields: {
                        msg_no: { type: "int32", id: 1 },
                        data:   { type: "bytes", id: 2 }
                    }
                },
                LoginC2S: {
                    fields: {
                        username: { type: "string", id: 1 },
                        token:    { type: "string", id: 2 }
                    }
                }
            }
        }
    }
});
```

提取方法：直接从JSON结构读取 `fields` 和 `values`，重建proto定义。

**特征B：编译后代码模式**

```javascript
$root.packet = (function() {
    const packet = {};

    packet.Packet = (function() {
        function Packet(p) {
            if (p) for (var ks = Object.keys(p), i = 0; i < ks.length; ++i)
                if (p[ks[i]] != null) this[ks[i]] = p[ks[i]];
        }
        Packet.prototype.msg_no = 0;
        Packet.prototype.data = $util.newBuffer([]);
        Packet.prototype.unix_milli = $util.Long ? $util.Long.fromBits(0,0,false) : 0;

        Packet.encode = function encode(m, w) {
            if (!w) w = $Writer.create();
            if (m.msg_no != null && Object.hasOwnProperty.call(m, "msg_no"))
                w.uint32(8).int32(m.msg_no);
            if (m.data != null && Object.hasOwnProperty.call(m, "data"))
                w.uint32(18).bytes(m.data);
            if (m.unix_milli != null && Object.hasOwnProperty.call(m, "unix_milli"))
                w.uint32(24).int64(m.unix_milli);
            return w;
        };
        return Packet;
    })();
    return packet;
})();
```

提取方法：
- 从 `prototype.xxx = defaultValue` 提取字段名和默认值类型
- 从 `encode` 函数中 `w.uint32(N).type(m.field)` 提取字段编号和类型
- `uint32(N)` 中 N 的含义：`N = (field_number << 3) | wire_type`

**Wire Type 编码解析：**

| wire_type | 含义 | 对应proto类型 |
|-----------|------|-------------|
| 0 | Varint | int32, int64, uint32, uint64, sint32, sint64, bool, enum |
| 1 | 64-bit | fixed64, sfixed64, double |
| 2 | Length-delimited | string, bytes, message, repeated (packed) |
| 5 | 32-bit | fixed32, sfixed32, float |

**示例解码：**
- `w.uint32(8).int32(...)` → N=8, field_number=8>>3=1, wire_type=8&7=0 → field 1, int32
- `w.uint32(18).bytes(...)` → N=18, field_number=18>>3=2, wire_type=18&7=2 → field 2, bytes
- `w.uint32(24).int64(...)` → N=24, field_number=24>>3=3, wire_type=24&7=0 → field 3, int64

**区分 int32/int64/bool/enum（同为 wire_type=0）：**
- 看 encode 调用的方法名：`.int32()`, `.int64()`, `.uint32()`, `.bool()`, `.sint32()` 等
- 看 prototype 默认值：`= 0` 通常是 int32, `$util.Long` 是 int64, `= false` 是 bool

**识别 repeated 字段：**
- prototype 默认值为空数组：`Packet.prototype.items = $util.emptyArray`
- encode 中有循环写入：`for (var i = 0; i < m.items.length; ++i)`

**识别嵌套 message：**
- encode 中调用：`$root.package.InnerMsg.encode(m.field, w.uint32(N).fork()).ldelim()`

**识别 enum：**
```javascript
packet.MsgNo = (function() {
    const valuesById = {}, values = Object.create(valuesById);
    values[valuesById[0] = "Def"] = 0;
    values[valuesById[100] = "MsgNo_LoginC2S"] = 100;
    return values;
})();
```

### 2. google-protobuf (goog/jspb)

**特征：**

```javascript
proto.packet.Packet = function(opt_data) {
    jspb.Message.initialize(this, opt_data, 0, -1, null, null);
};
goog.inherits(proto.packet.Packet, jspb.Message);

proto.packet.Packet.deserializeBinary = function(bytes) { ... };
proto.packet.Packet.prototype.serializeBinary = function() { ... };

proto.packet.Packet.prototype.getMsgNo = function() {
    return jspb.Message.getFieldWithDefault(this, 1, 0);
};
proto.packet.Packet.prototype.setMsgNo = function(value) {
    return jspb.Message.setProto3IntField(this, 1, value);
};
```

提取方法：
- 从 `getFieldWithDefault(this, N, default)` 提取字段编号 N
- 从 `setProto3XxxField` 推断类型：`IntField`→int32, `StringField`→string, `BytesField`→bytes
- 从 getter/setter 方法名推断字段名：`getMsgNo` → `msg_no`

### 3. 静态Proto描述文件

有些前端会直接包含 `.json` 描述文件或 `.desc` 文件（FileDescriptorSet 的二进制序列化）。

如找到 `.desc` 文件，可用 protoc 反编译：
```bash
protoc --decode=google.protobuf.FileDescriptorSet google/protobuf/descriptor.proto < file.desc
```

## 信封识别技巧

信封消息是 WebSocket 通信的最外层包装，用来路由内层业务消息。

**识别方法：**
1. 搜索 WebSocket `send()` 调用，追踪序列化的是哪个消息类型
2. 搜索 `onmessage` / `onMessage` 处理函数，追踪反序列化的是哪个消息类型
3. 信封消息通常只有少量字段，其中必有一个 bytes 字段用于承载内层消息
4. 信封消息通常有一个"消息号/命令号"字段，结合 enum 实现路由

**单信封 vs 双信封判断：**
- 如果 `send()` 和 `onmessage` 使用同一个消息类型 → 单信封
- 如果分别使用不同类型（一个用于请求，一个用于响应）→ 双信封

## proto3 语法速查

```protobuf
syntax = "proto3";
package mypackage;

enum MyEnum {
    DEFAULT = 0;
    VALUE_A = 1;
    VALUE_B = 2;
}

message MyMessage {
    int32           field_a = 1;
    string          field_b = 2;
    bytes           field_c = 3;
    bool            field_d = 4;
    int64           field_e = 5;
    float           field_f = 6;
    double          field_g = 7;
    MyEnum          field_h = 8;
    InnerMessage    field_i = 9;
    repeated int32  field_j = 10;
}
```

## 常见问题

**Q: 前端代码高度混淆/压缩怎么办？**
A: 尝试搜索未混淆的字段名（protobuf字段名通常保留原名）。搜索 `prototype.` 赋值语句或 JSON descriptor 中的 `fields` 关键词。如果实在无法解析，停下来告知用户。

**Q: 一个前端有多个proto包怎么办？**
A: 全部提取，合并到一个或多个 `.proto` 文件中。确保 package 和 import 关系正确。

**Q: 提取的proto编译报错怎么办？**
A: 停下来，向用户展示编译错误，讨论修复方案。常见原因：字段编号冲突、类型不匹配、缺少依赖的 message 定义。

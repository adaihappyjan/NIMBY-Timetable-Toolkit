# NIMBY Rails 存档二进制格式调查报告

> 只读逆向，全部在 `_backups/` 的安全副本上进行，**未改动任何原始存档**。
> 样本：`Das Rails Autosave 1.nimbyrails5`（file 4,403,114 B → 解压 18,759,436 B），
> 对照导出：`Das Rails Timetable Export 20271209T090628Z.json`（model_version 230）。

---

## 0. 备份状态（安全前提）
- 已把 **32/32** 个 `.nimbyrails5` 复制到 `F:\Codex\NIMBY_Timetable_Toolkit\_backups\saves_<时间戳>\`。
- 每个文件做了 **SHA256 逐一校验**，0 失败，清单见该目录 `_manifest.json`。
- 备份目录已加入 `.gitignore`（`_backups/`、`_research/`），不会被提交。

---

## 1. 文件外层结构
```
[固定头 1380 B] + [zstd 帧（标准 zstd，magic 28 b5 2f fd）]
```
- 头以 ASCII `NMBY` 开头，随后 `02 00 01 00`（格式主/次版本）、`13 00 0a 00`。
- 头中包含若干 32-bit LE 计数、**两段 32 字节的类哈希/GUID 块**、以及以 `Das Rails\0…` 开头的**存档名（定长字段 + 大片保留 0 区）**。
- 头**尾部 4 字节 `0c 3f 1e 01` = 0x011E3F0C = 18,759,436 = 解压后大小**（size 提示）。
- 解压后熵 ≈ 5.26 bit/byte；`0x80` 占 26%、`0x00` 占 14% —— 典型的 **varint（LEB128）续位字节**海量出现，说明 payload 是**类 protobuf 的变长整数对象流**。

### 权威长度来自 zstd 帧，不是头
工具箱现有写入管线 `write_output()` 只做 `header + zstd(raw_after)`，**头原样不动**。而已验证的“车库接班”补丁会给 payload 追加字节（长度变化），游戏仍能正常读取。
➡ 结论：游戏加载时用的是 **zstd 帧自带的 content size**，头里的 size 字段只是过时提示。**因此变长编辑是安全的**，无需重算头中的哈希/计数（现有 garage-join 写入即活证据）。

---

## 2. 对象 id 编码与类型码（核心发现）
- id 在流中编码为 `uvarint(int(id,16) * 2)`（末位恒为偶，用于区分“这是一个 id”）。
- **id 的最高十六进制位 = 对象类型码**：

| type (id>>48) | 类别 | 导出JSON含? | 该存档数量级 | 说明 |
|---|---|---|---|---|
| `0x1` | **Track 轨道段** | 仅被引用 | 151k refs | 铁路几何主干，被线路/站台大量引用 |
| `0x2` | **Station 车站** | ✅ | 411 defs / 913k refs | 定位实体（2×f64 Mercator） |
| `0x3` | **信号机/道岔节点（推测）** | ❌ | ~7,377 | 携带 Mercator 坐标，导出里没有 |
| `0x4` | **Line 线路** | ✅ | 51 | code/color/stops |
| `0x5` | **Train 列车** | ✅ | 393 | name/code/tags |
| `0x6` | **Schedule 时刻表** | ✅ | 70 | shifts/trains |
| `0x7` | **脚本扩展定义** | ❌ | 少 | 即 `GARAGE_JOIN_VECTOR`（旁为车号 MR-73 / TTC 00xx） |
| `0x8` | **扩展实例绑定** | ❌ | ~16k | 旁有字符串 `stm_timetable_garage_join_1` |

> `0x9–0xf` 在普查中出现但 id 非顺序（如 0x96cf607fffff3），是几何数据里的**假阳性**（巧合的 varint 串），非真实对象类型。

**意义**：信号机、道岔、完整轨道几何**只存在于二进制**，导出 JSON 完全不含。这正是“复刻现实路网 / #10 二进制编辑”的真正瓶颈所在。

---

## 3. 记录布局（已反解）

### 3.1 Station 记录
```
… [uvarint id] … [f64 merc_x] [f64 merc_y] [uvarint namelen] [name utf8]
   [00 00 00] [uvarint 区数/长度] [ 站台Track列表: uvarint track_id … ]
   [f32 from_t][f32 to_t] …
```
实测 “Toronto Union Station” 名前 16 字节 = 两个 float64：
- `x = -8,836,575.82`，`y = 5,410,593.43`
- 名字后紧跟其站台轨道 id `0x1000000000001`(10W)、`0x1000000010001`(10E)——与 Line.stops 里的 track_id 完全一致。
- 站台 `from_t/to_t` 为 **f32**（如 `00 00 80 3f`=1.0，`43 16 b2 3e`≈0.3479）。

### 3.2 坐标投影 = 标准 Web Mercator（EPSG:3857），R=6378137，**误差 0**
```
x = R * radians(lon)
y = R * ln(tan(pi/4 + radians(lat)/2))         # 反解:
lon = degrees(x / R)
lat = degrees(2*atan(exp(y / R)) - pi/2)
```
6 个车站反解与导出经纬度**逐位一致**（R_impl=6378137.000，误差 0.00e-6）。
➡ 任意真实经纬度都能**精确**换算成游戏内部坐标——可用于把真实站点逐字节注入/对齐。

### 3.3 Line / Stop（来自导出，物理布局与站点一致）
`Line{ id,name,code,color(0xAABBGGRR ABGR),tags,stops[] }`；
每个 `Stop{ idx, leg_distance(f32), station_id, arrival, departure, areas[[ {track_id, platform_name, from_t(f32), to_t(f32)} ]] }`。

### 3.4 脚本扩展（type 0x7/0x8）
`GARAGE_JOIN_VECTOR = 01 8280808080808007 dedceebcf08cfdee5b00008fd2e2ee97b1b4907d`
即“把某列车的 garage_join 扩展打开”的尾部向量；工具箱已能安全批量写入/移除（末尾定长向量替换 + 反向解压校验）。

---

## 4. 对象流分区（字节偏移）
```
0x000000 .. ~3.27M   轨道段定义 + 信号/节点（type 1/3，带坐标与几何）
~3.27M               车站区（type 2）
~3.53M               线路区（type 4）
~3.65M               列车区（type 5）
~3.80M               时刻表区（type 6）+ 扩展绑定（type 8）
~3.80M .. ~18.2M     巨型轨道几何点阵（曲线折线，占全文件 ~77%）
~18.2M .. 末尾        车辆/mod 定义与长描述文本（TrainUnit 说明）
```

---

## 5. 可安全编辑的字段（按风险从低到高）

| 编辑目标 | 位置 | 宽度 | 风险 | 方法 |
|---|---|---|---|---|
| **车站坐标对齐真实经纬度** | Station 名前 16 B | 定长 | 最低 | 就地覆盖 2×f64（长度不变，size/哈希都不受影响） |
| **线路颜色** | Line.color | 4 B | 低 | 就地覆盖（注意 ABGR 字节序） |
| **站台 from_t/to_t** | Stop.areas | 4 B f32 | 低 | 就地覆盖 |
| **车库接班扩展开关** | train 记录尾 | 定长向量 | 低（已验证） | 复用现有 `GARAGE_JOIN_VECTOR` 补丁 |
| **车站/线路改名** | 变长字符串 | 变长 | 中 | 需按现有 schedule 改名同款“定位+长度差补丁+反向解压校验” |
| **新增/删除 站/轨/信号** | 全流 | 变长+计数 | 高 | 需完整序列化器（会牵动 header 计数与海量引用），暂不建议 |

**统一安全护栏（沿用工具箱既有做法）**：
1. 只写新文件，绝不覆盖输入；`.partial` 原子落盘 + SHA256。
2. 写前用 id+name 唯一定位记录（多命中即拒写）。
3. 压缩后 `zstd 反向解压 == 期望 payload` 才落盘。
4. 全程基于 `_backups/` 副本验证，通过后再交给用户。

---

## 6. 直接解锁的能力（对用户目标）
1. **现实路网精确注入**：Web Mercator 公式已验证 → 可把 OSM 真实站点坐标就地写入对应 Station（复刻现实路网从“清单对照”升级为“坐标级对齐”）。
2. **信号机/道岔可见化**：type 0x3 带坐标 → 可解析并在线路图/地图上渲染出导出 JSON 缺失的信号布局。
3. **批量线路上色 / 站台微调**：定长就地编辑，零结构风险。

---

## 7. 复现脚本（均只读）
- `_research/recon.py <save>` —— 头/熵/字符串概览
- `_research/schema.py <export.json>` —— 导出逻辑 schema
- `_research/samples.py <export.json>` —— 完整样本 + 车站锚点
- `_research/anchor.py <save> <export.json>` —— 站名锚定反解记录布局
- `_research/investigate.py <save> <export.json>` —— 投影反解 + id 类型普查 + 分区
- `_research/probe_types.py <save>` —— 未知类型 0x3/0x7/0x8 定位

> 下一步建议：为 type 0x3 做一次专项反解（确认信号 vs 道岔的字段），并落地一个**就地坐标编辑器**（最低风险、直接服务“复刻现实路网”）。

---

## 8. 后续进展（本轮追加）

### 8.1 type 0x3 = 带坐标的定位节点（信号机 / 道岔）
- 候选 id varint（末位 nibble=3）**7377** 个，其中 **2460** 个在其后 20 字节内带合法 Mercator 坐标，且**全部集中在 ~3.33MB 区**（轨道/站点交界处）。
- id **严格顺序**：0x3000000000001, 0x3000000010001, 0x3000000020001 …（真实对象，非几何噪声）。
- 记录形态：`[id][字段][小端长度 3a/1a/36][00 00 00 00][flags][f64 X][f64 Y][f64 ~朝向/轨道参数]`。
- 样本坐标紧密聚集在多伦多联合车站咽喉区（-79.381, 43.6448±）——符合**大站信号/道岔群**特征。
- 结论：**导出 JSON 缺失的信号/道岔布局可从二进制还原并在地图/线路图上渲染**。

### 8.2 JSON-free 直读器（已验证原型 `_research/save_reader.py`）
以匹配存档为真值对照：
- **Station**：找到的车站**坐标 100% 逐位精确**（本存档实际含 166 个；导出 JSON 的 411 是更晚扩建后的状态，多出的 Ottawa/Montréal 站在本存档里确实不存在——直读结果才是该存档真相）。
- **Train 393/393、Schedule 70/70、Line 51/51 的 id 全部命中**（Line 的 name/code/color/stops 因“引用 vs 定义”交织，完整解析列为下阶段）。
- 结论：**车站坐标与对象身份已可完全脱离 JSON 直接从存档读取**；时刻表班次/线路站序的完整直读是下一里程碑。

### 8.3 就地坐标编辑器（已落地并测试）`toolkit_coordedit.py`
- 能力：直接从存档枚举车站（id+名+经纬度），并把任意车站**就地改写为真实经纬度**（Web Mercator 精确换算，16 字节定长覆盖，payload 长度不变）。
- 安全：只写新文件、多命中/未命中拒写、反向解压校验、原子落盘。
- 验证：
  - 真实存档往返测试 **PASS**（仅目标站 16 字节变化，其余全字节不变，重读经纬度精确匹配）。
  - `tests/test_toolkit_coordedit.py` **6 项单测通过**（投影往返、范围守卫、直读、只改目标、拒绝未知站、拒绝覆盖输入）。
- 用法（命令行）：
  ```bash
  python toolkit_coordedit.py list  <存档.nimbyrails5>
  python toolkit_coordedit.py set   <输入.nimbyrails5> <输出.nimbyrails5> "站名=lon,lat" [更多…]
  ```
- 意义：**“复刻现实路网”从“清单对照”升级为“逐站坐标级对齐”**。

### 8.4 Line 的 stops 语法完全反解（本轮攻克）
- **关键结论**：线路的 name/code/color/**按序站点** 都存在**带名记录**上（该记录 id 末位为 `0x6`，即游戏内统一的 Line/Schedule 对象），`0x4` 记录不携带名字。
- 记录语法：`[id][namelen name][codelen code][tagcount=00][color uvarint][flags…][stopCount][每站块…]`；
  - `color` 为 uvarint，值即 `0xAABBGGRR`（ABGR）；例 `a9 81 80 f8 0f` → `0xFF0000A9`。
  - 每站块 = `[站台轨道 id ×N(W/E)][Station id][from_t/to_t f32 等标量]`，**Station id 为块尾**；按序收集 `stopCount` 个 Station id 即为完整站序。
- **校验（对拹导出 JSON）**：站序 **35/37 完全一致**、颜色 **33/37 一致**（其余差异来自该存档与导出为不同游戏状态，站点数 166≠411 已佐证）。
- 落地：`toolkit_savereader.py` 一体化直读 **站/线(含站序)/信号**；`tests/test_toolkit_savereader.py` 3 项单测通过。

### 8.5 完整 JSON-free 路网管线（本轮落地）
- `toolkit_savereader.read_network(save)` → `{stations, lines(含 stops), signals, counts}`，真实存档实测 **166 站 / 37 线 / 2459 信号**。
- 已接入后端命令 `network-read`、`align-coords` 与 Web UI（现实路网页“从存档直读路网（含信号）”“信号/道岔图层”“坐标对齐面板”），HTTP 端到端验证通过。
- **是否还需要 JSON？** 线路图 / 路网对照 / 坐标对齐现已可**完全脱离导出 JSON**。仅“时刻表体检/迁移”仍以导出 JSON 作为**真值**做写前后逐班次校验（安全护栏，刻意保留）。

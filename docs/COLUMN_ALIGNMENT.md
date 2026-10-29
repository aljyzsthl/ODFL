# 列识别精度分析 — 价格 / 数量为什么会对错列

> ⚠️ **状态（2026-10-21）**：本文描述的整套列推断机制**已整体退役**。
> `CodeExtract/engine.py`（几何管线：pdfplumber 单元格网格 → 表头分类 → 列边界 →
> 单元格分配）连同 `devtools.py` 已移入 `CodeExtract/_legacy/`，PO 抽取改由
> `CodeExtract/claude_engine.py` 调用 Claude API 完成（见 HANDOVER 第 4 章）。
> 因此本文不再描述任何现行代码路径——它记录的是**为什么**本地几何解析会静默错列，
> 以及那次排查沉淀下来的两条至今有效的规则：
> **数值形状必须校验**，**不确定就标记而不是推算**。这两条在新实现里分别是
> `claude_engine` 的算术复核与 `review` 列表。

> ⚠️ **状态（2026-10-13）**：本文是 2026-10 一次缺陷排查的**历史记录**。文中
> `.workbuddy\column_probe.py` 与 §0 的复现命令**已随 2026-10-11 的发布清理被删除**
> （`.workbuddy/` 下只剩 `port_probe.py`，见 HANDOVER 4.11 与 §7），命令本身不再可运行；
> 符号仍存在，行号已对照当前 `CodeExtract/engine.py` 校正：
> `classify_header` :734、`_CELL_VALIDATORS` :1263、`parse_line_items` :1083、
> `extract_from_table` :4574、`align_value_to_row` :2751、`cell_from_block` :1272、
> `find_header_row` :994、`build_column_bounds` :1037、`enrich_money_from_pages` :3569、
> `qty_before_price` :3097、`_MONEY_CELL` :1254、`_ROLE_LOOKUP` :688、`COLUMN_ROLES` :626。
> §2.2 / §3 中作为**修复手段**引用的 `reconcile_money()`、`is_clipped_amount()`、
> `_lost_leading_char()`、`find_document_total_qty()` 已于 2026-10 **被有意移除**（见
> HANDOVER 2.2），相关描述保留为历史记录。
>
> **结论仍有效，且 §3 的 P0 部分已经落地**（见 §5.1 进度表）：现在改用词边界匹配、
> 每角色唯一列、跨行表头合并、表头区间空隙定界、数值形状校验与 `low_confidence` 标记。
> 当时探针的 12 项断言已固化到 `CodeExtract\devtools.py` 的 `t_column_identity` /
> `t_page_columns`（共 50 项检查，本快照 49 通过 1 项因缺渲染器而跳过，属环境问题）。

> 结论先行（**当时的**价格/数量错位，主因不是 OCR 识别错误，而是"列身份"的推断方式有问题）。
> 列身份曾由「表头文字分类 + 表头中心点的中点」一次性决定，没有任何反馈校验；
> 表头一旦认错或认漏，数值就会整片落到相邻列，而且**是静默发生的**。

---

## 0. 复现命令（探针已删除，保留为当时的输出）

```
C:\Python314\python.exe .workbuddy\column_probe.py
```

```
A. classify_header()      engine.py:701
B. _CELL_VALIDATORS       engine.py:979
C. parse_line_items()     engine.py:832
D. extract_from_table()   engine.py:4402
E. align_value_to_row()   engine.py:2380
→  2 passed, 12 failed
```

⚠️ 该脚本已不在本快照中（见顶部状态说明）。**替代办法**（同样已退役，仅在
`_legacy/` 中保留）：`cd CodeExtract/_legacy && python devtools.py` —— 其中的
`t_column_identity` 与 `t_page_columns` 就是这 12 项缺陷的定型版本，且当时全部通过
（最初是 2/12）。上表中的 `engine.py:NNN` 是**旧版引擎**的行号，与当前文件无关。

---

## 1. 数据去哪了：一条数据要经过四次"列身份"判断

```
PDF
 ├─ (a) 矢量表格 ──► pdfplumber 单元格网格 ──► extract_from_table()   表头子串路由   ← D 段
 ├─ (b) 模板 zone ─► words 坐标 ──► parse_line_items() ──► 表头中心点中点定界        ← A/B/C 段
 │                                    └─► 按 y 就近取值 ──► align_value_to_row()     ← E 段
 └─ (c) 兜底 ─────► 整页文本 ──► enrich_money_from_pages()  "最后两个金额" 约定      ← F 段
```

四条路各有一套独立的列判定规则，彼此不交叉验证。**任何一条判错，都没有第二条路来纠正它。**

---

## 2. 已复现的缺陷清单（按优先级）

> ⚠️ 本节及 §3 中的 `engine.py:NNN` 均为**当时**的旧引擎行号，与当前文件不符（顶部状态
> 说明已给出本节用到的符号在现版本的对应行号）。这些缺陷**大部分已在 2026-10-08 修复**
> （见 §5.1），阅读时请把"当时如何出错"当作历史背景，把 §3 当作后来落地的改法。

### P0-1 表头词表的"3 字符陷阱" — 数量列整个丢失

`classify_header()`（`engine.py:701`）的匹配分两步：先整格相等，再允许子串匹配，
**但子串匹配要求 `len(word) >= 4`**（`engine.py:712`）。而词表里恰好有一批长度 ≤ 3 的关键别名：

| 别名 | 长度 | 所在角色 | 后果 |
|---|---|---|---|
| `qty` | 3 | quantity | 只要表头不是**恰好**写 `Qty`，就永远匹配不到 |
| `u/m` | 3 | unit | 同上 |
| `u/p` | 3 | unit_price | 同上 |

实测：

```
'Ord Qty'     -> ''          ← 数量列消失
'Total Qty'   -> 'amount'    ← 更糟：被当成金额列
```

`'Total Qty'` 为什么变成 amount：`total` 是 amount 的别名且长度 5 ≥ 4，
按"长词优先"在 `qty` 之前命中。**这不是漏识别，是错识别**——数量会被写进金额字段。

### P0-2 `Description` 抢走 `material_code` 角色

`"description"` 同时登记在 `material_code`（`engine.py:664`）和 `description`（`engine.py:688`）
两个角色下。`_ROLE_LOOKUP` 按 `-len` 排序且是**稳定排序**（`engine.py:698`），
同长度时先注册的 `material_code` 胜出：

```
'Description' -> 'material_code'   （期望 'description'）
```

配合 `find_header_row()` 的"先到先得"（`engine.py:778`：`role not in colmap`），
当版面是 `Description | Item #`（描述在左、编号在右，PO 里很常见）时：

```
表头  Description(60)  Item #(400)  Qty(520)  Price(560)
结果  material_code 锚定在 x=88  ← 描述列
      Item # 列因为角色已被占用而被丢弃
      row = {'material_code': 'SAMSUNG WASHER', 'quantity': 'WF45B6300AP 2', ...}
                              ^ 描述当成了物料         ^ 编号溢进数量列
```

一次表头歧义，直接造成**物料、数量两列同时错位**。

### P0-3 同一个表头被拆成两个锚点 —— 价格掉进 `unit` 列

这是最隐蔽也最有代表性的一条。表头 `Unit Price` 在 PDF 里是两个独立的词，
`find_header_row()` 逐词分类后再尝试合并相邻对（`engine.py:783-790`）：

```
词 "Unit"  -> role 'unit'       锚点 A（中心 x=530）
词 "Price" -> role 'unit_price' 锚点 B（中心 x=545）
合并 "Unit Price" -> 'unit_price'  → 但 'unit_price' 已存在，被 "role not in colmap" 跳过
                                  → 子锚点 A 也没有被删除
```

结果**这一列内部被劈成两半**，边界落在列中央而不是列边缘，数字落在左半边：

```
columns: {material_code:70, description:158, quantity:408, unit:530, unit_price:558}
bounds : [(material_code,0,114) (description,114,282) (quantity,282,469)
          (unit,469,544) (unit_price,544,700)]
                                        ^^^^^^^^^^^ 边界在 544，
row:  {'quantity': '2', 'unit': '599.00'}        ← 价格(599.00, 中心533) 落在 unit
      unit_price = ''                            ← 单价列为空
```

而 `unit` 列的校验器只接受 `EA/PCS/SET...`（`engine.py:983`），
`cell_from_block()` 对"有校验器但校验失败"的列**返回空字符串并丢弃候选值**
（`engine.py:1009`）——所以价格不是"保守地留给人工"，而是**静默消失**。

### P0-4 4 位以上、无千分位的金额一律被判定为"不是金额"

```python
_MONEY_CELL = re.compile(r"^\s*\$?\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*$")   # engine.py:975
```

`\d{1,3}` 决定了**没有千分位的 4 位以上数字全部不通过**：

| 打印形式 | 结果 |
|---|---|
| `599.00` / `$599.00` / `1,198.00` | accepted |
| `1198.00` | **REJECTED** |
| `1234.00` | **REJECTED** |
| `1060.00` | **REJECTED** |
| `1060.0000` | **REJECTED** |

`1060.0000` 这个格式在真实单据里出现过——**金额扫描器认识它，单元格校验器却不认识**，两处契约不一致。
（原引用的是已被删除的 `reconcile_money()` 注释；该格式现由 `_MONEY_CELL` / `_AMOUNT`
（`engine.py:1251/1254`）接受，见 §5.1 阶段 1。）

叠加 P0-3 的"校验失败即丢弃"，一张单价 ≥ $1000 且版面没有千分位的 PO，
单价会整列丢失。

### P0-5 `extract_from_table()` 的覆盖式表头路由 —— 单价读成了行总额

`engine.py:4422-4432` 用子串包含判断列角色，且在同一循环里**覆盖赋值**：

```python
if any(kw in h for kw in ["unit price", "price", "unit cost"]):
    price_col = idx
if any(kw in h for kw in ["amount", "total", "ext", "extended"]):
    amount_col = idx
```

表头 `Extended Price` 同时含有 `price` 和 `extended`，于是：

```
表头: ['Item', 'Description', 'Qty', 'Unit Price', 'Extended Price']
数据: ['WF45B6300AP', 'SAMSUNG WASHER', '2', '599.00', '1198.00']
结果: unit_price = '1198.00'   ← 读的是行总额，不是单价
      amount     = '1198.00'
```

这是最典型的"**价格对应到错误的列**"：数值本身 OCR 读对了，是**列归属错了**，
而且错得"看起来合理"（1198.00 确实是个金额），人工只扫一眼很难发现。
同一段里 `mat_col` 也是覆盖式赋值，缺陷同源。

### P0-6 两级表头会污染第一条数据

`find_header_row()` 只扫描 `rows[:8]` 的**单行**，相邻词合并且只在同一行内进行。
表头分两行打印时（`Unit` 在上一行、`Price` 在下一行）：

```
'599.00 Price'   ← 第二级表头的 "Price" 被当成数据，并进了 unit 单元格
```

### P0-7 就近取值的"一值多领"

`align_value_to_row()`（`engine.py:2380`）是"距离最近 + 固定容差 6.0"，
**没有一对一约束，也不记录已被认领**：

```
value row y=103 '599.00'
item A y=100 -> '599.00'
item B y=107 -> '599.00'      ← 同一笔单价被两行同时认领
```

### P1-8 兜底路径用"位置约定"代替"列身份"

`enrich_money_from_pages()`（`engine.py:3358`）在代码行找不到金额时，
向上下各 4 行搜索（`_MONEY_NEIGHBOUR_SPAN`，`engine.py:3316`），
然后用**约定**决定谁是单价：

```python
if not price:
    price, amount = money[-2], money[-1]     # engine.py:3487  最后两个金额
```

只有 `qty × price == amount` 成立时才走算术择优（`engine.py:3476-3485`），
且 `score >= 3` 才提前停止，**score == 2（≥2 个金额）也被接受**。
行内出现三个以上金额（零售价、折扣、税、成本+总额）时，`[-2]` 未必是单价。

`qty_before_price()`（`engine.py:2711`）同理：用"价格左边最近的整数就是数量"，
并取**最后一个**满足条件者（`found = n` 覆盖），行内还有箱数/重量/行号时会取错。

### P1-9 缺少全局一致性回灌

**写作当时**引擎里有这些可用的自检信号：
- `find_document_total_qty()` —— 文档自己打印的总数量
- `reconcile_money()` —— `qty × unit_price = amount`
- `is_clipped_amount()` / `_lost_leading_char()` —— 单据算术的截断/丢字特征

> ⚠️ **2026-10 更新：这四个函数已被有意删除**（HANDOVER 2.2），理由是"一个推导出来的
> 错价比一个明显缺失的价更危险"。因此本节的"用算术信号回灌"思路已不可直接照搬，
> 需要以「不变量**检测**/报警」而非「数值**修正**」的形式重新设计：发现 `qty × price ≠
> amount` 时标记该行降置信度、提示人工，而不是把数值改掉。

文档自己提供的约束，是唯一不需要标注就能验证列是否错位的证据，目前基本被浪费了。

---

## 3. 改进方案

### P0 —— 局部修补，低风险，可立即验证

| # | 改什么 | 怎么改 | 位置 |
|---|---|---|---|
| 1 | 短别名失效 | 子串匹配改为**词边界匹配**（`\bqty\b` 等）并去掉 `len>=4` 门槛；`total` 只在整格等于 `total` 时才算 amount，避免吞掉 `Total Qty` | `engine.py:712` |
| 2 | 角色歧义 | `description` 从 `material_code` 词表中移出，改为**上下文消歧**：同一表头行里若已有更明确的物料列（`item #`/`sku`/`material`），则 `Description` 归 description | `engine.py:659-691` |
| 3 | 表头拆成两个锚点 | 相邻词合并成功后，**删除被合并区间覆盖的子锚点**；同一角色出现多个候选时保留最具体的，其余降级为 `role#2` 而不是丢弃 | `engine.py:783-790` |
| 4 | 金额校验器 | `_MONEY_CELL` 改 `\d+`（接受无千分位的 4+ 位）并容忍 4 位小数；与 `_money_pass` 的规则对齐 | `engine.py:975` |
| 5 | 校验失败即丢弃 | `cell_from_block()` 校验失败时**返回原值**，同时在记录上打 `low_confidence` 标记，交给复核而不是静默丢 | `engine.py:1009` |
| 6 | 覆盖式表头路由 | 改为**每个角色只认一个最佳列 + 角色互斥**（`price_col != amount_col`），并按"别名越长越具体"优先 | `engine.py:4422-4432` |
| 7 | 两级表头 | `find_header_row()` 支持**连续 2 行的表头带**，把两行合并后再分类；被判定为表头的行全部从 body 中剔除 | `engine.py:767-798` |
| 8 | 就近取值 | `align_value_to_row()` 加**已认领集合**：按距离升序贪心配对，一个值行只归一行 | `engine.py:2380` |

### P1 —— 用几何与算术替代"表头中心点"，收益最大

**9. 列边界改由数据自身的对齐方式决定（核心改动）**

现在 `build_column_bounds()`（`engine.py:801`）取相邻**表头中心点**的中点作为边界。
问题在于：**表头和数据几乎从来不对齐**——表头多是左对齐/居中，而数字列一律右对齐，
且表头文字长度与数据宽度无关。实测已经证明：同一份数据、同样的 x 坐标，
**只把表头从 `Qty` 改成 `Total Qty`，数量就从 quantity 列跑到了 amount 列**。

改法：**表头只负责给列命名，不负责定界。**

```
1. 取表格区域内所有"数值 token"的 x 中心（数字/金额/数量形态）
2. 对这些 x 中心做一维聚类（按间隙切分，间隙阈值用 token 高度的中位数）
3. 每个聚类就是一个真实的数值列，边界取聚类之间的空隙中点
4. 用表头文字的 x 区间与聚类做匹配 → 给每个聚类命名
5. 少数几行才出现的列（如"折扣"）自然形成窄聚类，不会去瓜分邻列宽度
```

这一步同时解决问题 3、6（列边界不再依赖表头是否被认出来），
且对"表头完全缺失"的版面也有效。

**10. 把 `qty × price = amount` 从"事后修正"提升为"列指派的打分函数"**

列数通常 ≤ 10，候选组合有限，可以直接搜索：
在候选列集合上，选择一组指派使**尽量多的行满足 `qty × unit_price = amount`**，
把"算术自洽的行数"作为目标函数。这在混有"零售价/折扣/税"的复杂表头下，
比任何关键词规则都可靠——因为它是文档自己保证成立的关系。

**11. 全局自检并暴露给用户**

- `Σ quantity` 与单据自己打印的总数量比对（⚠️ 提供该信号的
  `find_document_total_qty()` 已删除，需重新实现"读取印刷合计"这一动作），不等则整单降置信度并在界面标黄
- `Σ (qty × unit_price)` 与 `Σ amount` 的偏差超过 1 分即**告警**（⚠️ 只告警、不修正 —— 见 §P1-9 的更新）
- 每一列算"非空率"与"量级分布"：某列大量为空而邻列超载 = 边界错了的强信号

这些**不需要标注数据**就能跑，是最便宜的错误探测器。

### P2 —— 结构性方案，针对最复杂的版面

**12. 有表格线的 PDF 直接用表格线定界。** `pdfplumber` 的 `page.lines` / `page.rects`
（以及 `find_tables()`）能给出真实的列边界，比任何文字推断都稳。
现在 `extract_tables()` 只用在 Priority 2 路径上，且拿 `table[0]` 当表头、用子串路由
（正是缺陷 5 所在）。表格线应当作为**首选**几何来源，而不是兜底。

**13. 每客户模板记录"列 x 区间"。** `customer_templates.json` 已有 fingerprint 匹配机制
（现版本：`build_fingerprint()` :2299、`fingerprint_score()` :2331、`find_customer_template()` :2339），
再加一个 `column_bands` 字段即可：某客户第一次确认正确后，
后续即使表头缺失、字体变了、扫描歪了，也能按 x 区间定位列。
这是长期最稳的方案，且与现有模板体系天然契合。

**14. 用历史确认结果做轻量拟合。** 把人工在界面上确认过的行作为标注，
对每个客户拟合各列的 x 区间（分位数即可，不需要模型）。
新单据先按拟合区间取值，再用不变量检查兜底。

---

## 4. 怎么验证"真的改好了"

### 4.1 列级 ground truth（需要明文 PDF）

现在的 baseline 快照对比只比对 **(code, qty, price)** 的最终值，
所以"读对了但列归错了"这种情况在对比里看不出来。
需要把记录下沉到列一级：

```json
{"page": 1, "line": 3, "code": "WF45B6300AP",
 "qty": "2", "unit_price": "599.00", "amount": "1198.00",
 "column_x": {"qty": [405, 425], "unit_price": [520, 560], "amount": [600, 660]},
 "header_text": {"qty": "Total Qty", "unit_price": "Unit Price"}}
```

有了 `column_x`，评分就能区分三种错误，而不是笼统地算"错"：
- 数值读错（OCR 问题）
- 数值读对但落到别的列（**本次分析的重点**）
- 整行丢失

> ⚠️ **本机限制**：这个快照里 `CodeExtract\data_upload` 的 PDF 都是
> NASCA DRM 加密的，无法在**本机**建立或运行列级评分。列级评分必须在有明文 PDF 的
> 机器上做。这一点不能含糊——本机只能验证合成表与几何逻辑。

### 4.2 不变量检查（不需要标注，随时可跑）

| 检查 | 判据 | 能抓住什么 |
|---|---|---|
| 总数量守恒 | `Σ qty ==` 单据印刷的总数量（信号函数已删，需重实现读取动作） | 数量漏读、串到邻列 |
| 行算术 | `qty × unit_price == amount`（±0.01） | 单价/金额互换、单价读成行总额 |
| 单据合计 | `Σ (qty × price) ≈ Σ amount` | 整列错位 |
| 列非空率 | 每列非空率不应出现"一列近满、邻列近空" | 列边界画错 |
| 量级一致性 | 同列内相邻行数值不应有 10× 以上跳变 | 小数位/千分位丢失 |

⚠️ 前三项是**不变量探测**，只能告警与标黄；**不得据此改写数值**（HANDOVER 2.2：
算术修正已于 2026-10 被有意移除）。

这套检查的价值在于：**它用文档自身的规则判断对错，不需要任何人工标注**，
可以直接挂到现有的复核界面上，把可疑行标出来。

### 4.3 交叉读取一致性（不需要标注）

同一份 PDF 走三条独立的路（表格线 / 坐标聚类 / 行文本兜底），逐行比对
`(code, qty, price)`。三条路一致的行自动放行；**不一致的行进人工复核池**。
这是"不需要 ground truth 就能发现列错位"的最实用办法，也正好利用了当前
各路径互不校验这个弱点——把弱点变成信号。

### 4.4 回归测试

- `.workbuddy\column_probe.py` —— 合成表验收测试（本次新增，12 项断言即修复目标）
  ⚠️ **已删除**，其断言现由下面第一项承载
- `CodeExtract\devtools.bat` —— 引擎自带套件（列身份部分即 `t_column_identity` / `t_page_columns`）
- `python src\selftest.py` —— 面板层回归（`po` / `lines` / `ui` / `excel` / `erp` /
  `bridge` / `sku` / `classify` / `p0` / `p3` 共 10 个套件）

**每改一处引擎列逻辑，这三套都要跑。**

---

## 5. 建议的落地顺序

| 阶段 | 内容 | 验收 |
|---|---|---|
| 1 | P0-4 + P0-5 + P0-6（校验器、表头路由互斥、两级表头） | `devtools.py` 的 `t_column_identity` 对应断言转绿；套件无回归 |
| 2 | P0-1 + P0-2 + P0-3（词表、角色歧義、锚点去重） | 同上，四种表头写法结果一致 |
| 3 | P1-9（列边界由数值对齐决定） | 无 |
| 4 | P1-10 + P1-11（算术打分选列 + 全局自检） | ⚠️ 依赖 2026-10 已移除的算术机制，见 HANDOVER 2.2 |
| 5 | P2-12 + P2-13（表格线定界、模板列区间） | 在明文 PDF 机器上跑列级评分 |

阶段 1–2 是"修补明知的错误"，改动小、可立刻验证。
阶段 3 是本次分析真正的核心：**把列边界的依据从"表头文字"换成"数据自身的对齐"**。
阶段 4–5 决定复杂版面（多金额列、无表头、扫描歪斜）的上限。

### 5.1 进度（2026-10-08）

| 阶段 | 状态 | 说明 |
|---|---|---|
| 1 | ✅ 已完成 | `_MONEY_CELL` 接受全部实际打印形态（含 4 位以上无千分位、4 位小数）；`cell_from_block()` 校验失败时**返回原值并在 block 上记 `low_confidence`**，只有纯文本才拒绝；`extract_from_table()` 的表头路由改为**每角色唯一列**，并与 zone 路径共用 `classify_header()` 词表 |
| 2 | ✅ 已完成 | 词表改为**词边界匹配**（保留一段子串兜底，`NETPRICE` 这类无空格表头仍可解析）；`description` 移出 `material_code`；表头短语合并**仅限词表中的已知短语**且要求间隙小于字高，合并后删除被覆盖的子锚点；两行表头按 x 重叠**跨行补全**并把被吸收的词从正文剔除；列边界改取**相邻表头区间的空隙中点**，不再用中心点 |
| 3 | 🟡 部分完成 | **无模板、无表格线的整页文本表**已改走"整页当一张表"的列路由（新增 `extract_page_line_items()`，pattern 路径的 Priority 0）：保留每页 word 坐标、识别 `Line#` 为独立列、**未识别的表头格单独占位**（不再把 x 区间让给邻列）。仍未做 P1-9 的"数值 token x 聚类" |
| 4 | ⬜ 未开始 | P1-10 / P1-11：算术打分选列 + 全局不变量回灌 |
| 5 | ⬜ 未开始 | P2-12 / P2-13：表格线定界、模板 `column_bands` |

**验收结果（当时）**：`.workbuddy\column_probe.py` **14 passed, 0 failed**（原 2 passed, 12 failed）；
`CodeExtract\devtools.py` **52 passed, 1 failed**（唯一失败是环境缺依赖，与本改动无关）；`python src\selftest.py` **ALL SUITES PASSED**。
上述行为已固化为 `devtools.py` 的 `t_column_identity` 与 `t_page_columns` 用例，改动后必须同时跑这三套。

**2026-10-13 复核**：探针已删；`python CodeExtract\devtools.py` 现为 **50 项检查，49 通过、
1 项跳过**（`t_deps` 因本机无 PDF 光栅化器而失败，属环境问题非逻辑问题），
`python src\selftest.py` **10 个套件全部通过**。

### 5.2 真实单据验证：PO 6-95635-1026（Encompass，1 页）

这是 §3 之外唯一能读到的真实单据，也是"列身份"缺陷最完整的一次复现：

| 行 | 打印 Qty | 修复前读到 | 修复后 |
|---|---|---|---|
| 1 HAF-CIN-2P/EXP | 6 | **2**（"2 PACK"里的 2） | 6 |
| 2 HAF-QIN-2P/EXP | 30 | **2** | 30 |
| 3 RA-F18DBBQL/AA | 1 | **4**（"4-DOOR"里的 4） | 1 |
| 9 RA-F36DMMQL/AA | 3 | **4** | 3 |

单价同样整列错（读成 `Unit Core` 的 `0.00`，`amount` 读成真正的单价）——因为该表单**根本没有
extended cost 列**，而旧代码按"最后两个金额 = 单价、总额"的约定硬配。

修复后：9/9 行的数量与单价全部与打印值一致，且**单据自身的算术自洽**——
`Σ(qty × unit_price) = 2785.31` 等于页脚打印的 **PO Total**，数量合计 `52` 等于打印的
**Total Pieces**。这正是 §4.2 说的"不需要标注的验证信号"。

⚠️ `CodeExtract\data_upload` 里的 5 个 PDF 全是 NASCA DRM 包裹的，本机（及任何无 ClearText 的机器）
读不了，所以**本次真实单据对比只用到了这一个文件**。

> 本机（macOS，无 `pywin32`）跑测试的办法（该测试已退役）：
> `pip install --target <某个目录> openpyxl pdfplumber pypdf Pillow`，然后
> `PYTHONPATH=<该目录> python3 CodeExtract/_legacy/devtools.py`。
> ⚠️ 下文提到的 `.workbuddy/pydeps` 目录与 `column_probe.py` 均已删除；本地依赖目录
> 仍**不随发布分发**（`make_release.bat` 与 `prepare_handover.bat` 均已排除）。

---

## 附：本次复现脚本（已被 `devtools.py` 取代）

`.workbuddy\column_probe.py` —— 五个小节，12 项缺陷断言，全部基于真实引擎代码。
修复过程中它逐步转绿，最后并入了 `devtools.py` 的套件。
（2026-10-08：已全绿并并入 `devtools.py` 的 `t_column_identity`；2026-10-11：脚本本身
随发布清理被删除，断言仍由 `devtools.py` 承载。）

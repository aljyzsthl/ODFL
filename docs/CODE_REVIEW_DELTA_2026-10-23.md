# 相对 2026-10-21 审查的增量复核 — 新工作区 `C:\Users\17519\Documents\1021`

**复核时间**：2026-10-23
**基线**：`C:\Users\17519\Documents\1019-2`（CODE_REVIEW_2026-10-21.md 的审查对象）
**结论一句话**：这两天的改动是**功能演进**（R.D.D 列、订单预览、Party 联动、needs_review 闸门全链路），
**不是**按审查报告做的安全加固 —— 上一轮 8 项 P0 里 **5 项原样未修、2 项部分修复、1 项部分修复**，
且新增 1 个端口校验回归风险点。回归测试 11 套件全绿（`ALL SUITES PASSED`），
说明**新增能力自身是稳的**，但测试套件对安全边界依旧无覆盖。

---

## 0. 变更概览

| 文件 | diff 行数 | 性质 |
|---|---|---|
| `src/report.py` | ~1899 | 新增订单预览卡、设置重置、同步进度条、RDD 显示 |
| `src/selftest.py` | ~763 | 新增 `p0`/`p3`/`extract` 三套件（现 11 套件） |
| `src/of_erp.py` | ~455 | **RDD 列 K**、列映射冲突护栏、`_po_header`/`_order_dates`、预览字段 |
| `CodeExtract/claude_engine.py` | ~429 | 模型下拉、Bearer/token 校验、缓存签名、`apply_gate` 语义升级 |
| `src/of_server.py` | ~212 | `/api/order_preview`、`/api/settings_reset`、`/api/sync_state`、`_typed_party` |
| `src/of_master.py` | ~142 | `SHIP_DETAIL_FIELDS`→`TYPED_FIELDS`、mm_upload 走 `merge()` 增量 |
| `src/of_pdf.py` | ~128 | `preview_order`（改名避开 facade 撞名）、`force=False` 缓存复用 |
| `src/of_core.py` / `of_outlook.py` / `code_rules.py` | ~62/37/18 | 同步进度回调、字段名统一 |

**回归测试**：`C:/Python314/python.exe src/selftest.py` → `11` 套件、`ALL SUITES PASSED`（extract 套件 76/76）。

### 新增的、值得肯定的能力

1. **needs_review 闸门全链路打通**（`claude_engine.apply_gate` → `of_erp.prepare_lines` → 预览卡）。
   未登记物料码现在 `include=False`，须人工勾选才进 Order Upload —— 这是对
   「抽取提议、主数据裁决」契约的**实质性加强**，比上一轮审查时的"进 review 列表但照发"更严。
2. **列映射冲突护栏**（`of_erp.py:389-415`）：位置兜底只在该列未被占用时使用，避免把日期写进
   Sold-To Name 这类"ERP 照收、没人看"的错列。这是真正的正确性修复。
3. **两日期优先级被文档化且单点实现**（`_order_dates`：键入 > 印刷 > 默认），并新增 R.D.D（列 K）。
4. **端口分配加固**：`looks_like_orderflow` / `refuse_stale_instance` / `find_free_port`，
   不再静默杀进程、不再把浏览器开到别人的实例上。
5. `preview_order` 改名避开 `orderflow.py` facade 撞名 —— 并在 docstring 里记下了事故经过。

---

## 1. P0 逐项复核（对照 CODE_REVIEW_2026-10-21.md）

### P0-1　GET 侧无 Host/Origin 校验 — ❌ **原样未修**

**问题描述**：`_same_origin()` 只在 `do_POST` 调用（`src/of_server.py:554`）；
`do_GET` / `_do_GET`（`:354`、`:362`）全程不校验 Host。
**影响**：DNS rebinding 仍可读走全部邮件、客户主数据、订单文件
（`/api/codes`、`/api/master_export`、`/download/*` 都在 GET 侧）。
**建议改动**：在 `do_GET` 入口同样调用 `_same_origin()`，或抽一个 `_guard()`
在两个入口共用。GET 侧只需 Host 校验（读操作无 CSRF 面），成本极低：

```python
def do_GET(self):
    if not self._same_origin():          # 只挡 DNS rebinding
        self._json({"error": "cross-origin request refused"}, 403)
        return
    ...
```

---

### P0-2　`Origin: null` 放行 + 不校验 Content-Type — ❌ **原样未修**

**问题描述**：`src/of_server.py:331`
```python
if not raw or raw.lower() == "null":
    continue
```
`null` Origin（sandboxed iframe、`data:` URL、部分跨站表单）被直接放行；
`do_POST` 也不检查 `Content-Type`，所以 `<form enctype="text/plain">` 的简单请求
无需预检即可命中。
**影响**：任意网页可盲打 `/api/master_clear`（清空两张客户表）、`/api/cleanup`（删文件）、
`/api/settings_reset`（**新增的这条还会清掉 Claude token**）。
**建议改动**：`null` 一律拒绝；非简单请求才允许缺失 Origin，但必须
`Content-Type: application/json`：

```python
if not raw or raw.lower() == "null":
    return False          # null 就是"我不告诉你我从哪来"
...
ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
if ct and ct != "application/json":
    return False
```

> 注意：新增的 `/api/settings_reset`（`of_server.py:984-1008`）会**主动删除**
> `claude.api_key`，把这个风险面从"清数据"扩大到"清凭证"。

---

### P0-3　端口挪位后 `_same_origin` 校验错端口 → 自己 POST 全 403 — ❌ **未修，且默认值仍不一致**

**问题描述**：
- `src/of_server.py:322` `port = str(settings.get("server", {}).get("port", 8766))`
- `src/of_server.py:1596` `port = int(settings.get("server", {}).get("port", 8765))`

两处默认值 **8766 vs 8765** 仍不一致。端口被占用挪到 `nxt`（`:1616`）后，
`mine` 集合仍只含 settings 里的旧端口 → 浏览器发来的 `Host: 127.0.0.1:<nxt>`
不在 `mine` 里 → **所有 POST 被自己 403**。
**影响**：挪位后 dashboard 展示正常但点了没反应，极易被误判为前端 bug。
**建议改动**：把**实际绑定端口**写回 `settings["server"]["port"]`（或注入 handler），
两处默认值统一成一个常量：

```python
PORT_DEFAULT = 8765          # 唯一来源
...
settings.setdefault("server", {})["port"] = port   # 挪位后回写
```

---

### P0-4　report.py 两处 XSS — ❌ **原样未修**

**(a) `filterHint` 搜索词直插 HTML**
`src/report.py:3972` / `:3994`：
```js
filterHint: q ? SHIP.total+' matching "'+q+'"' : ...
```
`q` 是搜索框输入，经 `:1127` 的 `'<span class="md">'+(o.filterHint||...)` 进 innerHTML。
搜索词输入 `<img src=x onerror=alert(1)>` 即触发。
**建议**：`filterHint` 用 `esc()` 包裹，或在 `:1127` 统一 `esc(o.filterHint||...)`。

**(b) `JSON.stringify` 写进 onclick 属性**
`src/report.py:2824`、`:2967`、`:4119`、`:4149`、`:4170`、`:4202`：
```js
'onclick="SELDATE=' + JSON.stringify(key).replace(/"/g,'&quot;') + ...
```
只替换了 `"`，**`<`/`>`/`&`/单引号未处理**；且数据源含产品名、物料码、域名等
用户可控串（`prods[p]` 来自主数据上传）。
**建议**：改用事件委托 + `data-*` 属性，或至少
`esc(JSON.stringify(v))` 后再拼；更彻底是把字符串放进 `dataset` 而非 onclick 内联。

---

### P0-5　`normalise_to_master` 异常 fail-open — ❌ **原样未修**

**问题描述**：`src/of_pdf.py:1690-1691`
```python
except Exception as e:
    return [], [], str(e)
```
调用方 `src/of_pdf.py:1850-1852` 把 err 只当提示：
```python
if err:
    msgs.append(f"(material master check skipped: {err})")
```
随后 `results` 里**未经核对的物料码继续往下走**。
**影响**：主数据读取失败（文件被占用、JSON 损坏）时，"主数据裁决"整条被跳过，
破坏硬性契约 #2。虽然 `apply_gate` 在抽取侧有独立闸门，但两者并非同一路径，
gate 失效 + normalise 失败时仍会漏。
**建议改动**：fail-closed —— 返回一个错误码，让 `run_extractor` / `preview_order`
拒绝出文件，而不是"跳过检查继续"：

```python
except Exception as e:
    raise RuntimeError(f"Material Code list unreadable - "
                       f"refusing to publish unchecked codes: {e}")
```
（或返回 `(None, None, err)`，调用方 `if err: return ok, msg, ""`）

---

### P0-6　`prepare_lines` qty=0 被覆盖 + 0.00 当价 — ❌ **原样未修**

**问题描述**：`src/of_erp.py:812-815`
```python
qty = str(rec.get("quantity") or "").strip()
if not qty:
    qty = _qty_from_desc(src)      # 读者给的 0 被当成"没给"，被印刷行覆盖
```
`quantity=0` → `str(0 or "")` = `""` → falsy → 用 `source_line` 的数字覆盖。
**违反契约 #5**（绝不覆盖 reader 已给值）。

0.00 价格：`src/of_erp.py:823` `cost = _num(rec.get("unit_price"))`
→ `_num("0.00")` = `0`（int），`cost in (None, "")` 不拦，`0` 被当真值发布。
**违反契约 #6**（0.00 不是价格）。
**建议改动**：

```python
qty_raw = rec.get("quantity")
qty = None if qty_raw in (None, "") else str(qty_raw).strip()
if qty is None:                    # 只有"读者没给"才恢复
    qty = _qty_from_desc(src) or None
...
cost = rec.get("unit_price")
cost = None if cost in (None, "") else _num(cost)
if cost == 0:                      # 0.00 是"没印价格"，不是价格
    cost = None
if cost is None:
    cost = _cost_from_desc(...)
```

---

### P0-7　Excel 2 万行静默截断 + 全量 REPLACE 丢主数据 — ⚠️ **部分修复**

**已修**：`mm_upload`（`of_master.py:965`）现在走 `merge()` **增量合并**，
不再整表替换；返回 `added/existing/total` 可见。这是好消息。
**未修**：
- 截断仍在：`of_master.py:360` `for r in vals[:20000]`、`:392` `max_row=20000`，
  **无任何警告**，超 2 万行的价目表会静默丢行。
- `upload()`（Ship-To，`:2046`）、`dm_upload()`（Domain，`:2344`）仍是整表 REPLACE。
**建议改动**：截断时返回 `truncated=True` 并在 UI 明示；Ship-To / Domain 上传
改为合并或"上传前先备份旧表到 `*.bak`"。

---

### P0-8　`os.startfile` 无白名单 + `cleanup_inputs` 删父目录 — ⚠️ **部分修复**

**已修**：`/api/quick_open` 一处（`of_server.py:879-889`）现在走
`ALLOWED_EXT` + `realpath` 白名单 —— 注释里还写明了理由。
**未修**：
- 另外 **4 处裸调**：`:1329`（mm_export）、`:1435`（.eml ref）、`:1454`（openerp）、
  `:1477`（open index）。`:1454` 的 `erp_file` 与 `:1477` 的附件索引虽来自 DB，
  但 DB 可被 `/api/update` 类接口影响，仍应走同一白名单。
- `cleanup_inputs`（`of_pdf.py:1040`）**仍然 `shutil.rmtree(os.path.dirname(p))`** ——
  删的是**父目录**。若 `save_input()` 的落盘路径被改到用户目录，会连带删掉兄弟文件。
**建议改动**：抽 `_open_safe(path)` 统一 5 处调用；`cleanup_inputs` 改为
只删 `p` 自身 + 仅当父目录是本轮 `tempfile.mkdtemp` 创建的才 `rmdir`（非 rmtree）。

---

## 2. 本轮新引入的问题

### N-1　`settings_reset` 扩大了 CSRF 的爆炸半径 — 优先级 P0

`src/of_server.py:984-1008`：新接口会 `settings.pop("claude")`，
**连 API token 一起清掉**。叠加上面 P0-2（`Origin: null` 放行），
一个恶意网页一次请求就能把用户的 PO 阅读凭证抹掉，且**无确认、无日志**。
**建议**：该接口必须走 `_same_origin` 强校验 + 二次确认（body 里带
`{"confirm": true}`），并把 `claude.api_key` 保留（注释里"reset 就该 reset"
的论证不成立 —— 凭证是身份，不是偏好）。

### N-2　`_typed_party` 的输入清洗是白名单但截断语义不清 — 优先级 P2

`src/of_server.py:141-143`：
```python
value = "".join(ch for ch in value if ch.isalnum() or ch in "-_")[:20]
```
`isalnum()` 在 Python 里接受全角数字/汉字（`str.isalnum()` 对 `１２３` 为 True），
而 ERP 列 F/G 要的是 10 位账号。建议改 `ch in string.ascii_letters + string.digits + "-_"`。

### N-3　`_po_header` 多文档分歧只提示、不阻断 — 优先级 P2

`src/of_erp.py:890-920`：两个附件给出不同 `po_date` 时，注释说"须人工看"，
但实现是 `continue` + 记 note，**文件照出**。按本项目"可见即可疑"的调性，
这类分歧应让预览卡高亮为阻断项（或至少 `needs_review` 级别），而非一条可忽略的提示。

---

## 3. 上一轮 P1/P2 的现状（速查）

| 项 | 状态 | 证据 |
|---|---|---|
| Confirm 提前置 Done / 吞抽取结果 | 🟡 部分改善 | Confirm 现在回传 `file/name/url`（`of_server.py:684-689`），但 status 仍在 extractor 前写 |
| COM 无超时 / SYNC_LOCK | ❌ 未修 | `of_outlook.py` 无超时包裹 |
| `"ea"` 前缀误配 each | ❌ 未修 | — |
| 数字解析四套不一致 | ❌ 未修 | `_num`/`qc_num`/`_qty_from_desc`/JS 侧仍是四套 |
| mapping 数值单元格损坏 | ❌ 未修 | — |
| selftest 恒真断言 / 崩溃当通过 | 🟡 套件扩容但未审 | 新增 3 套件，`extract` 76 项断言扎实；旧的弱断言是否清理未逐条核 |
| JS/Python 域名规范化分叉 | ❌ 未修 | — |
| CODEQ 全页渲染 | ❌ 未修 | `report.py:4123` 仍 `oninput=CODEQ=this.value;render()` |
| 1MB/2.8MB JSON 无缓存重复解析 | ❌ 未修 | `of_pdf.py` 循环内仍重解析 |
| dashboard 列表无 LIMIT | ❌ 未修 | — |
| ThreadingHTTPServer 共享状态无锁 | ❌ 未修 | 新增 `SYNC` dict 仍无锁 |
| facade `_bind` 约 400 组 | ❌ 未修 | `orderflow.py:328` 仍在手工登记（且新增 `preview_order` 条目） |
| README 说 10 suites / 头部说 7 / 实有 11 | ❌ 口径更偏 | 现 `SUITES` 11 项，`selftest.py:1-12` 只列了 7 个子命令 |

---

## 4. 建议的下一步（按性价比排序）

**第一批 · 半天内可完成、风险最低**
1. `do_GET` 加 `_same_origin()`（P0-1）
2. `null` Origin 拒绝 + 校验 `Content-Type`（P0-2）
3. 端口常量统一 + 挪位后回写 settings（P0-3）
4. `filterHint` 加 `esc()`（P0-4a，一行）

**第二批 · 安全包**
5. 5 处 `os.startfile` 收敛到 `_open_safe()`（P0-8）
6. `settings_reset` 加 confirm + 保留 token（N-1）
7. `cleanup_inputs` 不再 rmtree 父目录（P0-8）

**第三批 · 数据/契约包**
8. `normalise_to_master` fail-closed（P0-5）
9. `prepare_lines` 零值/0.00 语义（P0-6）
10. Excel 截断告警 + Ship-To/Domain 上传备份（P0-7）

**第四批 · XSS 包**
11. onclick 内联串改事件委托（P0-4b，6 处）

每批完成后跑 `python src\selftest.py`，并**手工补一条安全回归**
（selftest 目前对 Host/Origin/Content-Type 完全无覆盖）。

---

## 5. 仍然值得保留的好做法

1. `apply_gate` 的"showing is not publishing"注释与实现一致，且现已贯通到 `include` 闸门。
2. `of_erp.detect_columns` 的位置冲突护栏 + 说明性 note。
3. 端口分配的三段式处理（自己 → 别人的 OrderFlow → 别的程序）与"绝不杀进程"。
4. `preview_order` 改名并在 docstring 记录 facade 撞名事故 —— 这类事故记录比注释更值钱。
5. `write_line` 按字段名写、空值不写、代码列转文本保前导零。
6. selftest `extract` 套件对缓存签名 / Bearer / 模型白名单的 76 项断言质量很高。

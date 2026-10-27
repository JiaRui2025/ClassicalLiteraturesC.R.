# 流水线详解

六个阶段的完整命令、参数与产出。所有脚本都在 `scripts/`，只依赖 PyMuPDF + Pillow + numpy（OCR 另需 PyObjC）。

---

## 0. 环境

```bash
python -m venv .venv && . .venv/bin/activate
pip install pymupdf pillow numpy pyobjc-framework-Vision pyobjc-framework-Quartz

npm i puppeteer-core@23      # 仅验收阶段需要
```

macOS 自带 Chrome 即可，`puppeteer-core` 不下载浏览器。

---

## 1. 判断 PDF 类型

```bash
python - <<'EOF'
import pymupdf
d = pymupdf.open("thesis.pdf")
print("pages", d.page_count)
print("text chars on p1", len(d[0].get_text()))
print("images on p1", len(d[0].get_images()))
EOF
```

- `text chars ≈ 0` 且 `images ≥ 1` → 图片型扫描件，走 OCR。
- 有文字层 → `pymupdf` 直接抽文本 + `get_text("dict")` 取包围盒，跳过第 2 步，其余流程不变。

判断依据要写在交付说明里。这一步弄错，后面全部白做。

---

## 2. OCR

```bash
python scripts/ocr_pages.py thesis.pdf --out ocr_all.json --langs es-ES,en-US
```

| 参数 | 说明 |
|---|---|
| `--langs` | 逗号分隔，**顺序即优先级**。西文书 `es-ES,en-US`；中文书 `zh-Hans,en-US`；多语混排把主语言放前面 |
| `--dpi` | 默认 200。细密小字（脚注、图例）可用 300，耗时约翻倍 |
| `--start/--end` | 分段跑，中断续传 |

耗时参考：476 页 @200dpi ≈ 12 分钟（M 系列 Mac）。**务必后台执行**。

产出结构（包围盒为归一化值，原点**左下**）：

```json
{"44": [{"text":"Fig. III-2. Fachada Principal…","conf":0.97,
         "x":0.18,"y":0.21,"w":0.63,"h":0.019}]}
```

转 top-down 的两个常用换算：

```
上沿 top    = 1 - (y + h)
下沿 bottom = 1 - y
```

> 这个坐标约定是全流程最容易出错的地方。写代码时把变量名直接叫 `top`/`bottom`，不要叫 `y1`/`y2`。

---

## 3. 找图注、出候选

```bash
python scripts/find_figs.py thesis.pdf ocr_all.json --out cands/ --contact-sheet
python scripts/find_figs.py thesis.pdf ocr_all.json --out cands/ --pages 40-120
```

默认正则覆盖西文写法：

```
^(fig(ura)?|tabla|l[áa]m(ina)?|foto|plate|figure)\s*\.?\s*([ivxlcdm]+|\d+)?\s*[.\-–]?\s*(\d+)
```

中文书换 `--pattern`：

```bash
--pattern '^(图|表)\s*([0-9一二三四五六七八九十]+)[.\-－]?\s*([0-9]+)'
```

**算法：图注即分隔符。**

对每条图注，在它上方的 OCR 文本行里找「最近的、且至少相距 14% 页高」的那一条，两条之间就是这张图的区域。

为什么是 14%：图里常有图例、坐标轴数字、手写批注被 OCR 成文本行，它们紧贴图注上方。取「最近一行」会把图切掉大半；取「至少 14% 以外」则跳过这些噪声。宁可多含白边——白边在第 5 步一定会被裁掉，少含图像则不可逆。

产出：`cands/p{页}_{序}.png` + `candidates.json` + `sheet_*.png`（每 20 张一张联系表）。

**这一步只出候选。** 直接拿去用会有 10%~20% 错位，必须人工过一遍。

---

## 4. 人工核对，写定稿

打开联系表，逐张比对「图注文字 ↔ 图像内容」。三种情况：

| 现象 | 判断 | 处理 |
|---|---|---|
| 图片里能看到图注文字 | 切到了**下一张**图 | 换 `src` 或改 `rect` |
| 图只剩一条横带 | 上界被图内文字顶掉了 | 手动给 `rect` |
| 同页两图内容相同 | 自动裁切落到同一区域 | 两图分别量 `rect` |

定稿 `figs.json`：

```json
{"figs": [
  {"id": "III-2",   "page": 44,  "rect": [0.21, 0.15, 0.83, 0.80]},
  {"id": "III-3",   "src": "cands/p044_001.png"},
  {"id": "IV-1",    "page": 96,  "rect": [0.15, 0.175, 0.905, 0.725]},
  {"id": "III-19",  "page": 77,  "rect": [0.24, 0.18, 0.79, 0.70], "rotate": 90}
]}
```

`rect` 是归一化 `[x0, y0, x1, y1]`，原点左上。量法：把页面按 130dpi 渲染成 PNG，肉眼定四边，换算成比例；跑一次第 5 步看结果，偏了就调。两三轮即可收敛。

**编号规范**：`<章罗马数字>-<序号>`，图版类加前缀（`LAM-V-1`、`TAB-V-7`、`FIG-V-10`）。id 同时是文件名，只用 `[A-Z0-9-]`。

---

## 5. 切图、清洗、归档

```bash
python scripts/build_figs.py thesis.pdf figs.json --out assets/fig --max-width 1500
```

清洗顺序（每步对应一类真实脏数据）：

| 步骤 | 处理什么 | 阈值 |
|---|---|---|
| `trim_edges` | 装订线黑条**贴着**裁切边缘 | 边缘列黑占比 > 0.55，最多剥 9% 宽 |
| `kill_side_bar` | 黑条**不贴边**、右侧还有白纸 | 黑占比 > 0.5，带宽 ≤ 18% |
| `trim_dashed_edge` | 虚线状装订标记（断续黑块） | 黑占比 > 0.30，窄带 ≤ 5% |
| `trim_white` | 多含的页边空白 | 墨迹 < 200 视为白，保留 8px |
| 限宽 | 超大图版 | > 1500px 才 LANCZOS 缩小 |

**只缩不放**：小图放大只会糊，宁可原尺寸显示。

产出 `assets/fig/<id>.jpg`（q88）+ `manifest.json` + `_review/final_*.png` 联系表。再回看一遍联系表，确认没有漏网的正文块或黑条。

---

## 6. 写数据、拼站点

`data/meta.js` 立骨架：

```js
window.THESIS = {
  meta:   {title_zh, title_en, title_es, author, year, uni_zh, uni_en, directors, pages, figs},
  problem:{q_zh, q_en, lead_zh, lead_en, tri_zh[][], tri_en[][], thesis_zh, thesis_en},
  objectives: [[zh, en], ...],
  verdict:{title_zh, title_en, lede_zh, lede_en, materials:[...], ranking:[...]}
};
```

章节文件：

```js
window.THESIS.chapters = window.THESIS.chapters || [];   // 这行守卫必须有
window.THESIS.chapters.push({ r:"III", es:"…", zh:"…", en:"…",
  pages:"p. 31–82", tag_zh:"田野诊断", tag_en:"Field diagnosis",
  solved_zh:"…", solved_en:"…",
  body_zh:["…","…"], body_en:["…","…"],
  figs:[{id, cap, t_zh, t_en, d_zh, d_en}, ...] });
```

按 2~4 章一个文件切分（`ch1-3.js`、`ch4-5.js`…），单文件别超过 30KB，否则改一章要重读全文件。

**解读怎么写**（这是全流程唯一无法自动化的部分）：

- 先读该图所在页的正文（OCR 里就有），确认作者用这张图论证什么。
- `d_zh` 写 2~4 句：**这张图证明了什么判断**，不是「图中可以看到 X」。
- 术语首次出现并列三种写法：`泥晶灰岩（caliza micrítica / micritic limestone）`。
- 原文图注一字不改，包括原文里的笔误——那是史料。

---

## 7. 验收

```bash
node scripts/verify.js .
node scripts/shot.js index.html 0,1500,3200,9000,20000,31000
node scripts/shot.js index.html 0,3200 --lang en
node scripts/shot.js index.html 5200 --click ".plate .frame"
```

看三件事：

1. `verify.js` 输出 `✓ 对账通过`（0 缺失 0 冗余）。
2. 截图里图版网格行行对齐、图注不串行、英文模式无残留中文。
3. `shot.js` 打印 `no js errors`。

页面高度是隐性指标：某次改动后从 28k 跳到 32k，通常是有图版 404 后 alt 文本撑开了布局。

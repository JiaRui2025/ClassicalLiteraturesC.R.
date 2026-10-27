---
name: scanned-thesis-web
description: "把一本扫描版学位论文／专著（无文字层的图片型 PDF）做成中英双语、逐图精读的单页网站：OCR 定位图注、按图注切出原书图版、清洗装订线与页边、以 window.THESIS 数据驱动渲染 11 章 + 全部图版 + 灯箱 + 语言切换。当用户要求「读一篇/一本 PDF，给出框架、每章的图都截出来并按原文解释」「做论文精读网页」「扫描书做成网页」「thesis reading site / bilingual figure atlas」时使用。关键词：论文精读、带读网页、扫描版 PDF、图片型 PDF、无文字层、OCR 切图、图版提取、图注定位、双语网页、中英对照、章节框架、figure extraction、scanned PDF、thesis website、bilingual reading page。"
agent_created: true
---

# 扫描版论文 → 双语图版网页

## 何时使用

用户丢来一本**扫描的**学位论文或专著，要求「读懂它、并且把每章的图都截出来讲解」。

典型诉求：

- 「读一下这篇博士论文，给出文章框架，理论解决了什么问题」
- 「每一章的图都要截出来，按原文解释」
- 「中文和英文都要，注意术语」
- 「网页形式新颖一点，不要老套」

交付目标：**一个可双击打开的单页站点**，覆盖全书每一章，每张图都是原书页面的真实裁切（不是重绘、不是示意图），图注保留原文，解读中英双语。

不适用：PDF 有文字层（直接 `pdftotext` 更快，不必 OCR）；用户只要摘要（不必建站）。

## 交付物

```
<project>/
├── index.html                  # 站点（引擎，见下）
├── data/
│   ├── meta.js                 # 书名/作者/问题/核心命题/七项目标/结论
│   ├── ch1-3.js  ch4-5.js ...  # 每 2~4 章一个文件，按章 push
├── assets/fig/<ID>.jpg         # 定稿图版 + manifest.json
├── ocr_all.json                # 全书 OCR（中间产物，保留，便于复查）
└── _review/                    # 截图与联系表（验收用）
```

`assets/template/` 是**已验证可运行的参考实现**（1 章 3 图）。优先复用它的 CSS 与渲染逻辑，不要从零重写——图版网格、灯箱、语言切换、章节进度条之间的耦合点很多，重写几乎必然回退。

## 架构（三句话）

1. **图版是数据**：每张图 = `{id, cap(原文图注), t_zh/t_en(标题), d_zh/d_en(解读)}`，挂在章对象上；`index.html` 遍历 `window.THESIS.chapters` 生成 DOM，`<img src="assets/fig/${id}.jpg">`。
2. **双语靠属性切换**：`<html data-lang="zh|en">`，CSS 里 `[data-lang="zh"] .en{display:none}`；每段文字都写成 `<span class="zh">…</span><span class="en">…</span>` 一对，不在 JS 里做字符串替换。
3. **图版靠「图注即分隔符」切**：OCR 给出每一行的归一化包围盒，图注上方最近的另一条文本行就是这张图的上界——整页图版、多图共页都能一次切对，空白交给后续白边裁切。

## 六个阶段

### ① 判断 PDF 类型

```bash
python -c "import pymupdf;d=pymupdf.open('thesis.pdf');print(d.page_count, len(d[0].get_text()))"
```

第二项为 0 → 图片型，走 OCR；否则可直接抽文本，跳过 ②。

### ② OCR（macOS Vision，无需 tesseract）

```bash
pip install pymupdf pyobjc-framework-Vision pyobjc-framework-Quartz
python scripts/ocr_pages.py thesis.pdf --out ocr_all.json --langs es-ES,en-US
```

476 页 @200dpi 约 12 分钟。**必须后台跑**，不要占住前台；中断后 `--start` 续跑。

语言顺序即优先级：西文书 `es-ES,en-US`，中文书 `zh-Hans,en-US`，英文书 `en-US`。

### ③ 找图注、出候选

```bash
python scripts/find_figs.py thesis.pdf ocr_all.json --out cands/ --contact-sheet
```

产出 150~200 张候选 + 联系表。**这一步只是候选**，直接拿去用会有 10%~20% 错位（同页两图互换、切到正文、切掉半张图）。

### ④ 人工核对，写定稿

打开 `cands/sheet_*.png`，逐张比对「图注文字 ↔ 图像内容」。对的记下 `src`，错的在页面上量出归一化矩形记 `rect`：

```json
{"figs": [
  {"id": "III-2", "page": 44, "rect": [0.21, 0.15, 0.83, 0.80]},
  {"id": "III-3", "src": "cands/p044_001.png"},
  {"id": "LAM-V-1", "page": 115, "rect": [0.18, 0.10, 0.86, 0.88], "rotate": 90}
]}
```

量矩形的笨办法最可靠：把该页按 130dpi 渲染出来，肉眼定四个边，跑一次 `build_figs.py` 看结果，偏了就调。**同页多图一定要分别核对**——两张图的自动裁切常常落到同一个区域。

### ⑤ 切图、清洗、归档

```bash
python scripts/build_figs.py thesis.pdf figs.json --out assets/fig
```

依次做：`trim_edges`（贴边黑条）→ `kill_side_bar`（不贴边的黑条）→ `trim_dashed_edge`（虚线装订标记）→ 白边裁切 → 限宽 1500 → 输出 JPEG q88 + `manifest.json` + 联系表。

### ⑥ 写数据、拼站点

`data/meta.js` 立骨架（书名/作者/问题/核心命题/七项目标/结论区），章节文件按章 push。每章至少要有：

| 字段 | 作用 |
|---|---|
| `r` / `es` / `zh` / `en` | 罗马数字章号 + 原书标题 + 中英译名 |
| `pages` / `tag_zh` / `tag_en` | 页码区间 + 一句话定性（如「田野诊断」） |
| `solved_zh` / `solved_en` | **本章解决了什么**——放在正文最前，读者先拿结论 |
| `body_zh[]` / `body_en[]` | 正文段落，每段 3~5 句，对应原文论证环节 |
| `figs[]` | 图版，见下 |

单张图版：

```js
{id:"III-24", cap:"Contour scaling desarrollado sobre dolomías de la Catedral de Jaén.",
 t_zh:"白云岩上的轮廓状剥落", t_en:"Contour scaling on dolomite",
 d_zh:"……（依据原文该节写 2~4 句，说清这张图证明了什么）",
 d_en:"……"}
```

写解读的三条硬要求：**图注原样保留**（西班牙语/德语等原词不动）、**术语首次出现并列**（「泥晶灰岩（caliza micrítica / micritic limestone）」）、**每段解读要落到判断**（不是「图示了 X」，而是「X 说明 Y，因此 Z」）。

### 验收

```bash
node scripts/verify.js .                      # 图号 ↔ 文件对账，必须 0 缺失 0 冗余
node scripts/shot.js index.html 0,1500,9000   # 真实 Chrome 截图，逐屏看
```

`shot.js` 会打印 `no js errors` 和页面高度；高度突变（如 28k → 32k）通常意味着某个图版加载失败撑开了布局。

## 设计要点（这套版式为什么这么定）

- **纸感而非「网页感」**：米白纸底 `#f3f0e9`、墨色 `#191714`、赤陶 `#a8482a`、铜绿 `#3f5f52`；衬线正文 + 等宽小字做元信息。学术读物不该长得像落地页。
- **图版框固定高 290px**：图片 `object-fit:contain`，三列网格因此行行对齐；不固定就会出现高低参差的「瀑布流」，读起来散。
- **图注三段式**：原文图注（斜体、小号、灰）→ 中英标题 → 中英解读。原文永远在上，译写在下的层级不能反。
- **章节导航做成「岩芯」**：左侧竖条按各章页数比例分配高度，滚动时高亮当前章——比目录更直观地表达「这本书的分量分布」。
- **结论区必须有**：不是复述，而是给出可带走的判断（排序、权衡、代价）。没有结论的精读网页只是加长版目录。

细节见 `references/layout-system.md`。

## 已踩坑清单

### 切图

- **同页两图互换**：`Fig. III-2` 与 `Fig. III-3` 印在同一页，自动裁切按 y 排序，caption 归属容易反。核对方法：把裁出的图打开看，图注在图片里就说明切到了**下一张**。
- **图注被 OCR 成 `I/I-25`**（III 被识别成 I/I）：正则匹配不到，候选会缺。看联系表发现「某图号整章缺失」时，回去查 OCR 原文。
- **图内图例/坐标轴/手写批注被 OCR 成文本行**，紧贴图注上方；若直接取「最近一行」作上界，会把图切掉一大半。所以 `region_above` 要求上界与图注至少相距 14% 页高。
- **虚线装订标记**（断续黑块，整列约 30%~50% 黑）过不了「连续深色」阈值，需要单独一趟 `trim_dashed_edge`；若虚线紧贴图像且中间无白纸，只能手动收紧 `rect`。
- **横排印刷的图版**（原书把横图旋转 90° 印在竖页上）切出来是躺倒的，用 `rotate` 转正。

### 站点

- `Chrome --headless --screenshot` 只能截首屏，配合 `#hash` 滚动经常截到空白帧（smooth-scroll + IntersectionObserver 未触发）。用 `puppeteer-core` 直接 `window.scrollTo` 并等待，才是可靠做法。
- 数据文件是**浏览器脚本**不是模块：`window.THESIS.chapters = window.THESIS.chapters || [];` 这行守卫必须有，否则第一个章节文件就报 `Cannot read properties of undefined`。
- `meta-grid` 用 `auto-fit,minmax(150px,1fr)` 会排出 4+2 的空格；固定 `repeat(3,1fr)` 才整齐。
- 无图章节的元信息不要显示 `FIG. 00`，改成「无图版 / NO PLATES」。

## 参考

- `references/pipeline.md` — 六阶段完整命令、参数、耗时与产出
- `references/pitfalls.md` — 逐条踩坑与判定方法（切图错位怎么看出来）
- `references/layout-system.md` — 配色、字体、组件、栅格与交互
- `assets/template/` — 可运行参考实现（1 章 3 图）

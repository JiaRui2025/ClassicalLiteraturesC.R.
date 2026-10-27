# scanned-thesis-web

把一本**扫描版**学位论文或专著（无文字层的图片型 PDF）做成中英双语、逐图精读的单页网站。

产出长这样：全书每一章都有「本章解决什么」+ 正文脉络 + 该章全部图版的**原书裁切**（不是重绘）+ 原文图注 + 中英双语解读；左侧「岩芯」导航按页数比例显示各章分量；点击图版进灯箱，可跨章翻页；中英一键切换。

---

## 为什么需要它

扫描版论文的三个死结：

1. **没有文字层** —— `pdftotext` 出来是空的，全文检索、图注定位全部失效。
2. **图版不能重画** —— 用户要的是「原书那张图」，示意图、重绘图都没有证据价值。
3. **图注是切图唯一的锚** —— 而图注恰恰埋在图像里，只能靠 OCR 捞出来。

这套流程把三件事串起来：OCR 拿包围盒 → 图注当分隔符定图块 → 按定稿清单切图清洗 → 数据驱动渲染。

---

## 目录

```
07_thesisWeb/
├── SKILL.md                     # 技能主文件（何时用、六阶段、踩坑清单）
├── README.md
├── scripts/
│   ├── ocr_pages.py             # macOS Vision OCR，逐页、可续跑
│   ├── find_figs.py             # 图注正则 + 图块定位 → 候选裁切 + 联系表
│   ├── build_figs.py            # 定稿清单 → 清洗 → 归档 + manifest
│   ├── shot.js                  # puppeteer 截图验收（滚动/切语言/点灯箱）
│   └── verify.js                # 图号 ↔ 文件对账，退出码可用于 CI
├── references/
│   ├── pipeline.md              # 六阶段完整命令与参数
│   ├── pitfalls.md              # 16 条踩坑 + 判定方法
│   └── layout-system.md         # 配色/字体/栅格/组件
└── assets/template/             # 可运行参考实现（1 章 3 图）
    ├── index.html
    ├── data/{meta.js, ch-demo.js}
    └── assets/fig/{III-2, III-6, III-24}.jpg
```

---

## 快速开始

```bash
pip install pymupdf pillow numpy pyobjc-framework-Vision pyobjc-framework-Quartz

# 1. OCR 全书（476 页约 12 分钟，放后台）
python scripts/ocr_pages.py thesis.pdf --out ocr_all.json --langs es-ES,en-US

# 2. 出候选 + 联系表
python scripts/find_figs.py thesis.pdf ocr_all.json --out cands/ --contact-sheet

# 3. 人眼过一遍联系表，写 figs.json（同页多图必须分别核对）

# 4. 切图清洗
python scripts/build_figs.py thesis.pdf figs.json --out assets/fig

# 5. 对账 + 截图
node scripts/verify.js .
node scripts/shot.js index.html 0,1500,9000
```

先看 `assets/template/`：直接用浏览器打开 `index.html` 就能跑，改动它比从零写快得多。

---

## 实战记录

本技能由一篇 476 页、纯图像扫描的西班牙语地质学博士论文（Rodríguez-Navarro, 1994, Univ. Granada）提炼。最终交付：11 章全覆盖、80 张图版、约 3.2 万像素高的单页站点。

几个数字：

- OCR 476 页 @200dpi ≈ 12 分钟
- 自动候选 155 张 → 人工定稿 80 张（约一半被替换或重裁）
- 图版清洗平均每张 2 轮 `rect` 微调

**结论**：自动切图能把工作量压到原来的 1/3，但「最后 20%」必须人眼看。这不是脚本不够好，是扫描件的脏法没有穷尽。

---

## 依赖

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | 脚本 |
| PyMuPDF | ≥1.24 | 渲染与裁切 |
| Pillow / numpy | 任意近期版 | 图像清洗 |
| PyObjC Vision/Quartz | 任意近期版 | macOS 原生 OCR（仅 macOS） |
| Node | 18+ | 验收脚本 |
| puppeteer-core | 23 | 复用本机 Chrome，不下载浏览器 |

Linux 上跑 OCR 需换 `pytesseract` 或 PaddleOCR，`find_figs.py` 的输入接口（`{page: [{text,x,y,w,h}]}`）不变，只需把包围盒换算成左下原点。

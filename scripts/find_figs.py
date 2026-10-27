#!/usr/bin/env python3
"""
find_figs.py — 从 OCR 结果里定位图注，并把图注上方的区域切出来做「候选」。

它只负责**给候选**，不负责定稿：一本书里的图往往是多图共页、跨栏、整页
图版，自动切分必然有 10%~20% 出错。正确做法是——自动跑一遍拿到 150~200
张候选，再人工比对图注文字与图像内容，把定稿写成 figs.json 交给 build_figs.py。

核心思路（比「找墨迹块」稳）
---------------------------
  图注本身是最好的分隔符。对每一条图注，取**它上方最近的另一条 OCR 文本行**
  作为上界，取图注行作为下界，中间那一块就是这张图的区域。
  这样整页图版、多图共页、图上有空白的情况都能一次切对；
  空白边由 build_figs.py 的白边裁切收尾。

用法
----
  python find_figs.py thesis.pdf ocr_all.json --out cands/
  python find_figs.py thesis.pdf ocr_all.json --out cands/ --contact-sheet
  python find_figs.py thesis.pdf ocr_all.json --out cands/ --pages 40-120,300

输出
----
  cands/p{页码}_{序号}.png     候选裁切
  cands/candidates.json         [{id, page, caption, rect:[x0,y0,x1,y1], src}]
  cands/sheet_*.png             联系表（每 20 张一张，带文件名标注）

图注正则
--------
  默认覆盖西文常见写法：Fig. / Fig / Figura / Tabla / Lám. / Lam. / Foto. /
  Plate / Figure + 章节号（罗马数字或阿拉伯数字）+ 序号。
  中文书改 --pattern，例如 r'^(图|表)\\s*([0-9一二三四五六七八九十]+)[.\\-－]?\\s*([0-9]+)'
"""

import argparse
import json
import os
import re

import numpy as np
import pymupdf
from PIL import Image, ImageDraw

DEFAULT_PATTERN = (
    r"^(fig(?:ura)?|tabla|l[áa]m(?:ina)?|foto|plate|figure)\s*\.?\s*"
    r"([ivxlcdm]+|\d+)?\s*[.\-–]?\s*(\d+)"
)

ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def roman_to_int(s):
    s = s.lower()
    if not s or not all(c in ROMAN for c in s):
        return None
    total, prev = 0, 0
    for c in reversed(s):
        v = ROMAN[c]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def norm_id(kind, chapter, num):
    """Fig. III-2 / Fig. III.2 / Fig. 2 → FIG-III-2 这类稳定 id。"""
    k = kind.lower().rstrip(".")
    prefix = {"fig": "FIG", "figu": "FIG", "figura": "FIG", "figure": "FIG",
              "plate": "FIG", "tabl": "TAB", "tabla": "TAB",
              "lam": "LAM", "lám": "LAM", "lamin": "LAM", "foto": "FOTO"}.get(k, "FIG")
    parts = [prefix]
    if chapter:
        r = roman_to_int(chapter)
        parts.append(str(r) if r else chapter.upper())
    parts.append(str(int(num)))
    return "-".join(parts)


def region_above(cap_top, anchors, min_h=0.14, max_h=0.78, gap=0.005):
    """
    图注上界 = 上方最近的、且与图注至少相距 min_h 的那条文本行的下沿。

    为什么要 min_h：图内常有图例、坐标轴标注、手写批注被 OCR 成文本行，
    它们紧贴图注上方，若直接取「最近一行」会把图切掉一大半。
    宁可多含白边（build_figs 会裁掉），也不要少含图像。
    """
    cands = [a for a in anchors if a < cap_top - min_h]
    top = max(cands) if cands else max(0.0, cap_top - max_h)
    if cap_top - top > max_h:
        top = cap_top - max_h
    return max(0.0, top + gap), max(0.0, cap_top - gap)


def col_bounds(gray, y0, y1, ink_thr=0.04, pad=0.012):
    """在给定行区间内收紧左右边界（只做粗裁，细裁交给 build_figs）。"""
    h, w = gray.shape
    sub = gray[int(y0 * h):int(y1 * h), :]
    if sub.size == 0:
        return 0.05, 0.95
    prof = (sub < 150).mean(axis=0)
    cols = np.where(prof > ink_thr)[0]
    if not len(cols):
        return 0.05, 0.95
    return max(0.0, cols.min() / w - pad), min(1.0, cols.max() / w + pad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("ocr")
    ap.add_argument("--out", default="cands")
    ap.add_argument("--pattern", default=DEFAULT_PATTERN)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--pages", default="", help="只处理这些页，如 40-120,300")
    ap.add_argument("--contact-sheet", action="store_true")
    args = ap.parse_args()

    keep = None
    if args.pages:
        keep = set()
        for part in args.pages.split(","):
            if "-" in part:
                a, b = part.split("-")
                keep.update(range(int(a), int(b) + 1))
            else:
                keep.add(int(part))

    os.makedirs(args.out, exist_ok=True)
    doc = pymupdf.open(args.pdf)
    ocr = json.load(open(args.ocr, encoding="utf-8"))
    rx = re.compile(args.pattern, re.I)

    cands = []
    for page_s in sorted(ocr, key=int):
        pno = int(page_s)
        if keep is not None and pno not in keep:
            continue
        lines = ocr[page_s]
        if not lines:
            continue

        # Vision 包围盒原点在左下；统一转成 top-down 的下沿坐标。
        # 低置信 / 极短的行多半是图内文字，不参与锚点，否则会把图切碎。
        anchors = sorted(
            1 - ln["y"] for ln in lines
            if ln.get("conf", 1.0) >= 0.35 and len(ln["text"].strip()) >= 4
        )

        pix = doc[pno - 1].get_pixmap(dpi=args.dpi)
        gray = np.array(
            Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        )
        h, w = gray.shape

        k = 0
        for ln in lines:
            txt = ln["text"].strip()
            m = rx.match(txt)
            if not m:
                continue
            cap_top = 1 - (ln["y"] + ln["h"])
            y0, y1 = region_above(cap_top, anchors)
            if y1 - y0 < 0.05:
                continue
            x0, x1 = col_bounds(gray, y0, y1)

            crop = Image.fromarray(
                gray[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
            )
            if crop.width < 80 or crop.height < 50:
                continue

            fid = norm_id(m.group(1), m.group(2), m.group(3))
            name = f"p{pno:03d}_{k:03d}.png"
            crop.save(os.path.join(args.out, name))
            cands.append({
                "id": fid,
                "page": pno,
                "caption": txt,
                "rect": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)],
                "src": name,
            })
            k += 1

    with open(os.path.join(args.out, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=1)
    print(f"{len(cands)} candidates -> {args.out}/candidates.json")

    if args.contact_sheet:
        cols, rows, tw, th = 5, 4, 320, 400
        for b in range(0, len(cands), 20):
            sheet = Image.new("RGB", (cols * tw, rows * th), "white")
            d = ImageDraw.Draw(sheet)
            for i, c in enumerate(cands[b:b + 20]):
                im = Image.open(os.path.join(args.out, c["src"])).convert("RGB")
                im.thumbnail((tw - 10, th - 28))
                x, y = (i % cols) * tw + 5, (i // cols) * th + 20
                sheet.paste(im, (x, y))
                d.text((x, y - 14), f'{c["id"]}  {c["src"]}', fill="black")
            sheet.save(os.path.join(args.out, f"sheet_{b // 20}.png"))
        print("contact sheets written")


if __name__ == "__main__":
    main()

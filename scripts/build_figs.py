#!/usr/bin/env python3
"""
build_figs.py — 按「定稿清单」把图版切出来、洗干净、编号归档。

输入是一份 figs.json（人工核对过的定稿），不是自动识别的结果。
自动识别只用来产生候选，定稿必须人工看一眼——这一步省不掉。

figs.json 两种写法，可混用
-------------------------
  {
    "figs": [
      {"id": "III-2",  "page": 44, "rect": [0.21, 0.15, 0.83, 0.80]},
      {"id": "III-3",  "src": "cands/p044_001.png"},
      {"id": "LAM-V-1","page": 115, "rect": [0.18, 0.10, 0.86, 0.88], "rotate": 90}
    ]
  }

  · rect 为归一化 (x0, y0, x1, y1)，top-down，原点左上。
  · src 直接复用已有的候选 PNG（省一次渲染，且候选已验证过）。
  · rotate 可选 90/180/270，用于横排图版（原书把横图旋转印刷的情况）。

用法
----
  python build_figs.py thesis.pdf figs.json --out assets/fig --max-width 1500

输出
----
  assets/fig/<id>.jpg      定稿图版
  assets/fig/manifest.json [[id, file, w, h], ...]
  _review/final_*.png      联系表，每 20 张一张

清洗顺序（每一步都对应一类真实脏数据）
------------------------------------
  1. trim_edges      —— 装订线黑条贴着裁切边缘时，一列列剥掉
  2. kill_side_bar   —— 黑条不贴边、右侧还有白纸时，整条切掉
  3. 白边裁切        —— 去掉多含的页边空白（宁可多切，白边一定在）
  4. 宽度上限        —— 超过 max_width 才缩放，避免小图被放大糊掉
"""

import argparse
import json
import os

import numpy as np
import pymupdf
from PIL import Image, ImageDraw


def trim_edges(a, thresh=0.55, max_frac=0.09):
    """剥掉紧贴左右边缘的连续深色列（装订线）。"""
    h, w0 = a.shape
    for _ in range(400):
        colp = (a < 120).mean(axis=0)
        if a.shape[1] > 200 and colp[-1] > thresh and (w0 - a.shape[1]) < w0 * max_frac:
            a = a[:, :-1]
        else:
            break
    for _ in range(400):
        colp = (a < 120).mean(axis=0)
        if a.shape[1] > 200 and colp[0] > thresh:
            a = a[:, 1:]
        else:
            break
    return a


def kill_side_bar(a, thresh=0.5, right_frac=0.60, max_bar=0.18):
    """切掉位于图内、右侧还有白纸的孤立深色竖条（装订黑条未被上一步处理时）。"""
    hh, ww = a.shape
    colp = (a < 120).mean(axis=0)
    dark = colp > thresh
    runs, i = [], 0
    while i < ww:
        if dark[i]:
            j = i
            while j < ww and dark[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    for s, e in runs:
        bw = e - s
        if s > ww * right_frac and 4 <= bw <= ww * max_bar:
            tail = a[:, e:]
            if tail.size and (tail > 200).mean() > 0.6:
                return a[:, :s]
    return a


def _runs(mask):
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def trim_dashed_edge(a, dark=0.30, zone=0.12, max_band=0.05, white=0.80):
    """
    虚线状装订标记：整列约 30%~50% 是黑的（断续），过不了 trim_edges 的
    0.55 阈值。做法是找「贴边的窄黑带」并切掉——窄带宽度上限 max_band，
    所以贴着裁切边缘的深色图像（宽黑带）不会被误切。
    """
    h, w = a.shape
    if w < 200:
        return a
    n = int(w * zone)

    # 右边缘
    for s, e in reversed(_runs((a < 120).mean(axis=0) > dark)):
        if s < w - n:
            break
        if (e - s) <= w * max_band:
            out = a[:, e:]
            if out.shape[1] == 0 or (out > 200).mean() > white:
                a = a[:, :s]
                break

    # 左边缘
    w2 = a.shape[1]
    for s, e in _runs((a < 120).mean(axis=0) > dark):
        if e > n:
            break
        if (e - s) <= w2 * max_band:
            out = a[:, :s]
            if out.shape[1] == 0 or (out > 200).mean() > white:
                a = a[:, e:]
                break
    return a


def trim_white(a, pad=8, ink=200, min_px=2):
    """裁掉四周白边，保留 pad 像素余量。"""
    m = a < ink
    ys = np.where(m.sum(axis=1) > min_px)[0]
    xs = np.where(m.sum(axis=0) > min_px)[0]
    if len(ys) and len(xs):
        return a[max(0, ys[0] - pad):ys[-1] + pad, max(0, xs[0] - pad):xs[-1] + pad]
    return a


def render(doc, pno, rect, dpi=220):
    pg = doc[pno - 1]
    w, h = pg.rect.width, pg.rect.height
    x0, y0, x1, y1 = rect
    clip = pymupdf.Rect(x0 * w, y0 * h, x1 * w, y1 * h)
    pix = pg.get_pixmap(dpi=dpi, clip=clip)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("spec", help="figs.json")
    ap.add_argument("--out", default="assets/fig")
    ap.add_argument("--max-width", type=int, default=1500)
    ap.add_argument("--dpi", type=int, default=220)
    ap.add_argument("--quality", type=int, default=88)
    ap.add_argument("--review", default="_review")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.review, exist_ok=True)

    spec = json.load(open(args.spec, encoding="utf-8"))
    figs = spec["figs"] if isinstance(spec, dict) else spec
    doc = pymupdf.open(args.pdf)

    rows = []
    for f in figs:
        fid = f["id"]
        if "src" in f:
            im = Image.open(f["src"]).convert("L")
        else:
            im = render(doc, f["page"], f["rect"], args.dpi)
        if f.get("rotate"):
            im = im.rotate(f["rotate"], expand=True)

        a = np.array(im)
        a = trim_edges(a)
        a = kill_side_bar(a)
        a = trim_dashed_edge(a)
        a = trim_white(a)

        im = Image.fromarray(a)
        if im.width > args.max_width:
            im = im.resize((args.max_width, int(im.height * args.max_width / im.width)),
                           Image.LANCZOS)
        name = f"{fid}.jpg"
        im.save(os.path.join(args.out, name), quality=args.quality, optimize=True)
        rows.append((fid, name, im.width, im.height))
        print(f"{fid}\t{im.width}x{im.height}")

    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False)
    print(f"\n{len(rows)} figures -> {args.out}")

    # 联系表，便于整体回看
    cols, rws, tw, th = 5, 4, 320, 400
    for b in range(0, len(rows), 20):
        sheet = Image.new("RGB", (cols * tw, rws * th), "white")
        d = ImageDraw.Draw(sheet)
        for i, (fid, name, w, h) in enumerate(rows[b:b + 20]):
            im = Image.open(os.path.join(args.out, name)).convert("RGB")
            im.thumbnail((tw - 10, th - 28))
            x, y = (i % cols) * tw + 5, (i // cols) * th + 20
            sheet.paste(im, (x, y))
            d.text((x, y - 14), fid, fill="black")
        sheet.save(os.path.join(args.review, f"final_{b // 20}.png"))
    print("contact sheets ->", args.review)


if __name__ == "__main__":
    main()

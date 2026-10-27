#!/usr/bin/env python3
"""
ocr_pages.py — 扫描版 PDF 逐页 OCR（macOS Vision 框架，无需 tesseract）。

为什么用 Vision：扫描版学位论文/专著通常没有文字层（get_text() 长度为 0），
而 macOS 自带的 VNRecognizeTextRequest 对西文/中文印刷体质量优于多数开源方案，
且零安装、离线、按行返回归一化包围盒（bottom-left 原点），正好可用于版面分析。

用法
----
  python ocr_pages.py thesis.pdf --out ocr_all.json
  python ocr_pages.py thesis.pdf --out ocr_all.json --langs es-ES,en-US
  python ocr_pages.py thesis.pdf --out ocr_all.json --start 1 --end 120   # 分段续跑

输出
----
  { "<page_no 1-based>": [ {"text":..., "conf":..., "x":..., "y":..., "w":..., "h":...} ] }

  包围盒为归一化值，原点在**左下角**（Vision 约定）。转成 top-down 的写法：
      top    = 1 - (y + h)
      bottom = 1 - y

依赖
----
  pip install pymupdf pyobjc-framework-Vision pyobjc-framework-Quartz

注意
----
  · 200 dpi 足够；300 dpi 对细字更稳但慢约 2 倍（476 页 ≈ 12 分钟 @200dpi）。
  · 每页只处理**一次**，别在循环里重复开 PDF。
  · 结果按页增量写入，中断后可用 --start 续跑，不要从头再来。
"""

import argparse
import json
import os
import sys
import tempfile

import pymupdf  # PyMuPDF

try:
    import Quartz
    import Vision
    from Foundation import NSURL
except ImportError:  # pragma: no cover
    sys.exit(
        "缺少 PyObjC。请安装：\n"
        "  pip install pyobjc-framework-Vision pyobjc-framework-Quartz"
    )


def ocr_image(path, langs=("es-ES", "en-US")):
    """对单张图片做 OCR，返回行级结果列表。"""
    url = NSURL.fileURLWithPath_(path)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        return []
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(0)              # 0 = accurate（1 = fast，别用）
    req.setRecognitionLanguages_(list(langs))
    req.setUsesLanguageCorrection_(True)
    handler.performRequests_error_([req], None)

    out = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        c = cand[0]
        bb = obs.boundingBox()
        out.append({
            "text": str(c.string()),
            "conf": float(c.confidence()),
            "x": float(bb.origin.x),
            "y": float(bb.origin.y),
            "w": float(bb.size.width),
            "h": float(bb.size.height),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default="ocr_all.json")
    ap.add_argument("--langs", default="es-ES,en-US",
                    help="逗号分隔的识别语言，顺序即优先级")
    ap.add_argument("--start", type=int, default=1, help="起始页（1-based，含）")
    ap.add_argument("--end", type=int, default=0, help="结束页（含），0 = 到末页")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()

    langs = tuple(x.strip() for x in args.langs.split(",") if x.strip())
    doc = pymupdf.open(args.pdf)
    end = args.end or doc.page_count

    # 已有结果则续写
    res = {}
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            res = json.load(f)

    tmp = os.path.join(tempfile.gettempdir(), "_ocr_page.png")
    for i in range(args.start - 1, min(end, doc.page_count)):
        pno = i + 1
        if str(pno) in res and res[str(pno)]:
            continue
        pix = doc[i].get_pixmap(dpi=args.dpi)
        pix.save(tmp)
        blocks = ocr_image(tmp, langs)
        res[str(pno)] = blocks
        print(f"{pno}\t{len(blocks)}", flush=True)
        if pno % 20 == 0:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    print(f"done: {len(res)} pages -> {args.out}")


if __name__ == "__main__":
    main()

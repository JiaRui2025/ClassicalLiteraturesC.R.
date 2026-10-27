#!/usr/bin/env node
/**
 * shot.js — 用真实 Chrome 截图做视觉验收（不是「能不能跑」，是「长什么样」）。
 *
 * 为什么不用 `chrome --headless --screenshot --window-size`：
 *   · 它只截首屏，滚动位置只能靠 #hash 或 JS 注入，遇到 smooth-scroll /
 *     IntersectionObserver 进场动画，经常截到空白帧；
 *   · 截不到控制台报错。
 * puppeteer-core 复用本机已装的 Chrome，滚动、点击、按键都能精确控制。
 *
 * 安装
 * ----
 *   npm i puppeteer-core@23
 *   若在受管环境里，装到统一目录再设 NODE_PATH：
 *   cd <node-workspace> && npm i puppeteer-core@23
 *   NODE_PATH=<node-workspace>/node_modules node shot.js ...
 *
 * 用法
 * ----
 *   node shot.js index.html 0,1500,3200
 *   node shot.js index.html 0,12000 --lang en --out _review/en
 *   node shot.js index.html 5200 --click ".plate .frame"     # 顺便验灯箱
 *   node shot.js http://localhost:8080 0,900                 # 也可截 dev server
 */

const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

const CHROME =
  process.env.CHROME_PATH ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i > -1 ? process.argv[i + 1] : def;
}

(async () => {
  const target = process.argv[2] || 'index.html';
  const ys = (process.argv[3] || '0').split(',').map(Number);
  const lang = arg('lang', '');
  const outDir = arg('out', '_review');
  const clickSel = arg('click', '');
  const width = parseInt(arg('width', '1440'), 10);
  const height = parseInt(arg('height', '900'), 10);

  fs.mkdirSync(outDir, { recursive: true });
  const url = /^https?:/.test(target) ? target : 'file://' + path.resolve(target);

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-gpu',
      '--in-process-gpu',
      '--hide-scrollbars',
      // 关掉滚动动画与进场动画，否则截图会拍到半透明/未定位的元素
      '--force-prefers-reduced-motion',
    ],
  });

  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 1 });

  const errs = [];
  page.on('pageerror', (e) => errs.push('PAGEERROR ' + e.message));
  page.on('console', (m) => {
    if (m.type() === 'error') errs.push('CONSOLE ' + m.text());
  });

  await page.goto(url, { waitUntil: 'networkidle2' });
  await new Promise((r) => setTimeout(r, 600));

  if (lang) {
    await page.evaluate((l) => {
      const b = [...document.querySelectorAll('button,span,a')]
        .find((x) => x.textContent.trim().toLowerCase() === l.toLowerCase());
      if (b) b.click();
    }, lang);
    await new Promise((r) => setTimeout(r, 400));
  }

  const H = await page.evaluate(() => document.body.scrollHeight);
  console.log('page height', H);

  for (const y of ys) {
    await page.evaluate((v) => window.scrollTo(0, v), y);
    await new Promise((r) => setTimeout(r, 650));
    const p = path.join(outDir, `p_${y}${lang ? '_' + lang : ''}.png`);
    await page.screenshot({ path: p });
    console.log('shot', y, '->', p);
  }

  if (clickSel) {
    const ok = await page.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return false;
      el.click();
      return true;
    }, clickSel);
    await new Promise((r) => setTimeout(r, 500));
    const p = path.join(outDir, 'click.png');
    await page.screenshot({ path: p });
    console.log('click', clickSel, ok, '->', p);
  }

  console.log(errs.length ? errs.join('\n') : 'no js errors');
  await browser.close();
})();

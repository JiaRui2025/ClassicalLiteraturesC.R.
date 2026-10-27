#!/usr/bin/env node
/**
 * verify.js — 交付前的对账脚本：数据里引用的图号 ↔ 磁盘上的图版文件。
 *
 * 三件事必须同时成立，否则页面会出现「碎图」或「孤儿图」：
 *   1. 每个 fig.id 都有 assets/fig/<id>.jpg
 *   2. 每个 <id>.jpg 都被某个章节引用（没有多余文件）
 *   3. id 不重复
 *
 * 用法
 * ----
 *   node verify.js [项目目录]        # 默认当前目录
 *
 * 退出码：0 通过，1 有问题（可直接用于 CI / pre-commit）。
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(process.argv[2] || '.');
const dataDir = path.join(root, 'data');
const figDir = path.join(root, 'assets', 'fig');

if (!fs.existsSync(dataDir)) {
  console.error('找不到 data/ 目录：', dataDir);
  process.exit(1);
}

// 数据文件是给浏览器用的脚本，不是 CommonJS 模块；用 vm 造一个 window 来加载
const sandbox = { window: {} };
vm.createContext(sandbox);
const files = fs
  .readdirSync(dataDir)
  .filter((f) => f.endsWith('.js'))
  .sort((a, b) => (a === 'meta.js' ? -1 : b === 'meta.js' ? 1 : a.localeCompare(b)));

for (const f of files) {
  const code = fs.readFileSync(path.join(dataDir, f), 'utf8');
  try {
    vm.runInContext(code, sandbox, { filename: f });
  } catch (e) {
    console.error(`数据文件执行失败：${f}\n  ${e.message}`);
    process.exit(1);
  }
}

const T = sandbox.window.THESIS;
if (!T) {
  console.error('window.THESIS 未定义');
  process.exit(1);
}

const ids = [];
console.log('章节                图版');
for (const ch of T.chapters || []) {
  const n = (ch.figs || []).length;
  console.log(`  ${String(ch.r).padEnd(4)} ${String(ch.pages || '').padEnd(12)} ${String(n).padStart(3)}`);
  (ch.figs || []).forEach((f) => ids.push(f.id));
}

const dup = ids.filter((x, i) => ids.indexOf(x) !== i);
const onDisk = fs.existsSync(figDir)
  ? fs.readdirSync(figDir).filter((f) => f.endsWith('.jpg')).map((f) => f.replace(/\.jpg$/, ''))
  : [];

const missing = ids.filter((i) => !onDisk.includes(i));
const unused = onDisk.filter((f) => !ids.includes(f));

console.log(`\n章节 ${(T.chapters || []).length} 个 · 图版引用 ${ids.length} 条 · 磁盘文件 ${onDisk.length} 个`);
if (dup.length) console.log('重复 id：', dup.join(', '));
if (missing.length) console.log('缺文件：', missing.join(', '));
if (unused.length) console.log('未被引用：', unused.join(', '));

const bad = dup.length || missing.length || unused.length;
console.log(bad ? '\n✗ 对账未通过' : '\n✓ 对账通过');
process.exit(bad ? 1 : 0);

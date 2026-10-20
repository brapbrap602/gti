// LNReader plugin harness: bundles plugins from a checkout of lnreader-plugins and runs them.
//
// Adapted from lnreader-plugins' scripts/live-check-plugin.js (MIT, (c) 2021 Rajarshee
// Chatterjee): each plugin's TypeScript source is bundled with esbuild (the repo's @libs and
// @ aliases resolved, npm packages from this harness's node_modules) and required as CommonJS.
//
// Usage: node harness.mjs <lnreader-plugins checkout>
// One JSON request per stdin line, one JSON reply per stdout line, in order:
//   {"op": "plugins"}                        -> [{file, id, name, site, lang} | {file, error}]
//   {"op": "novel", "file": f, "path": p}    -> {name, author, genres, summary, status, chapters: [{name, path, chapterNumber}]}
//   {"op": "chapter", "file": f, "path": p}  -> {html}
// Replies are {"ok": true, "result": ...} or {"ok": false, "error": "..."}.
// Plugins log every request with console.log, so all console output goes to stderr.

import * as esbuild from 'esbuild';
import { createRequire } from 'module';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs';
import os from 'os';
import readline from 'readline';

const require = createRequire(import.meta.url);
const HARNESS_DIR = path.dirname(fileURLToPath(import.meta.url));
const PLUGINS_ROOT = path.resolve(process.argv[2] ?? '.');
const STEP_TIMEOUT_MS = 60_000;

const writeReply = line => process.stdout.write(line + '\n');
for (const name of ['log', 'info', 'debug', 'warn']) {
  console[name] = (...args) => process.stderr.write(args.map(String).join(' ') + '\n');
}

const loaded = new Map(); // plugin file (relative to the checkout) -> plugin instance

async function loadPlugin(file) {
  if (loaded.has(file)) return loaded.get(file);
  const entry = path.resolve(PLUGINS_ROOT, file);
  if (!entry.startsWith(path.join(PLUGINS_ROOT, 'plugins') + path.sep)) {
    throw new Error(`${file} is not a plugin in the checkout`);
  }
  const result = await esbuild.build({
    entryPoints: [entry],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    target: 'node22',
    write: false,
    logLevel: 'silent',
    alias: {
      '@libs': path.join(PLUGINS_ROOT, 'src/libs'),
      '@': path.join(PLUGINS_ROOT, 'src'),
    },
    nodePaths: [path.join(HARNESS_DIR, 'node_modules')],
  });
  const unique = `${process.pid}-${loaded.size}-${Math.random().toString(36).slice(2)}`;
  const bundled = path.join(os.tmpdir(), `lnreader-${path.basename(file, '.ts')}-${unique}.cjs`);
  fs.writeFileSync(bundled, result.outputFiles[0].text, 'utf8');
  let plugin;
  try {
    const mod = require(bundled);
    plugin = mod.default ?? mod;
  } finally {
    delete require.cache[require.resolve(bundled)];
    fs.rmSync(bundled, { force: true });
  }
  loaded.set(file, plugin);
  return plugin;
}

async function withTimeout(promise, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out`)), STEP_TIMEOUT_MS);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

async function listPlugins() {
  const base = path.join(PLUGINS_ROOT, 'plugins');
  const found = [];
  for (const lang of fs.readdirSync(base, { withFileTypes: true })) {
    if (!lang.isDirectory() || lang.name === 'multisrc') continue;
    for (const name of fs.readdirSync(path.join(base, lang.name))) {
      if (!name.endsWith('.ts') || name.endsWith('.broken.ts') || name.endsWith('.d.ts')) continue;
      const file = `plugins/${lang.name}/${name}`;
      try {
        const plugin = await loadPlugin(file);
        found.push({ file, id: plugin.id, name: plugin.name, site: plugin.site, lang: lang.name });
      } catch (error) {
        found.push({ file, error: String(error?.message ?? error) });
      }
    }
  }
  return found;
}

function chapterItems(chapters) {
  return (chapters ?? []).map(c => ({
    name: c.name ?? '',
    path: c.path,
    chapterNumber: typeof c.chapterNumber === 'number' ? c.chapterNumber : null,
  }));
}

async function readNovel(file, novelPath) {
  const plugin = await loadPlugin(file);
  const novel = await withTimeout(plugin.parseNovel(novelPath), 'parseNovel');
  let chapters = novel.chapters ?? [];
  // A paged plugin lists its chapters page by page (the app reads pages 1..totalPages).
  const pages = novel.totalPages ?? 0;
  if (typeof plugin.parsePage === 'function' && pages >= 1 && (chapters.length === 0 || pages > 1)) {
    chapters = [];
    for (let page = 1; page <= pages; page++) {
      const part = await withTimeout(plugin.parsePage(novelPath, String(page)), `parsePage ${page}`);
      chapters.push(...(part?.chapters ?? []));
    }
  }
  return {
    name: novel.name ?? '',
    author: novel.author ?? '',
    genres: novel.genres ?? '',
    summary: novel.summary ?? '',
    status: novel.status ?? '',
    chapters: chapterItems(chapters),
  };
}

async function readChapter(file, chapterPath) {
  const plugin = await loadPlugin(file);
  return { html: await withTimeout(plugin.parseChapter(chapterPath), 'parseChapter') };
}

async function handle(request) {
  switch (request.op) {
    case 'plugins':
      return listPlugins();
    case 'novel':
      return readNovel(request.file, request.path);
    case 'chapter':
      return readChapter(request.file, request.path);
    default:
      throw new Error(`unknown op ${JSON.stringify(request.op)}`);
  }
}

const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  if (!line.trim()) continue;
  try {
    writeReply(JSON.stringify({ ok: true, result: await handle(JSON.parse(line)) }));
  } catch (error) {
    const status = error?.response?.status ?? error?.status;
    const reason = String(error?.message ?? error) + (status ? ` (HTTP ${status})` : '');
    writeReply(JSON.stringify({ ok: false, error: reason }));
  }
}

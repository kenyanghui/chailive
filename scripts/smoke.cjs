// 冒烟 v2：适配 hash 路由架构（home/all/chap/mod 四视图 + AI 面板 + RIA 钩子）
const fs = require('fs');

// --- chapters.js 注入 ---
global.window = {};
const src = fs.readFileSync('/root/chailive/data/chapters.js', 'utf8');
new Function('window', src)(global.window);
const { CHAI_CHAPTERS: CHAPS, CHAI_CARDS: CARDS, CHAI_MODS: MODS } = global.window;
if (!Array.isArray(CHAPS) || !Array.isArray(CARDS) || !Array.isArray(MODS)) { console.error('LOAD FAIL globals', CHAPS.length, CARDS.length, MODS && MODS.length); process.exit(1); }
console.log(`load: ${CHAPS.length} chaps, ${CARDS.length} cards, ${MODS.length} mods`);

// --- DOM stub ---
function el(tag) {
  return {
    tag, children: [], _html: '', dataset: {}, style: {}, value: '', textContent: '',
    set innerHTML(v) { this._html = String(v); }, get innerHTML() { return this._html; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener() {}, onclick: null, onsubmit: null, focus() {},
    classList: { _s: new Set(), add(x) { this._s.add(x); }, remove(x) { this._s.delete(x); }, toggle(x, on) { on === undefined ? (this._s.has(x) ? this._s.delete(x) : this._s.add(x)) : (on ? this._s.add(x) : this._s.delete(x)); }, contains(x) { return this._s.has(x); } },
    querySelector() { return el('div'); }, querySelectorAll() { return []; },
    scrollIntoView() {}
  };
}
const registry = {};
['bar toc stream top theme home q aiFab aiPanel aiMsgs aiForm aiQ aiGo aiClose'].forEach(id => registry[id] = el('div'));

// hash 路由 stub：记录 hashchange 监听器，set hash 时手动派发
let hashListeners = [];
const doc = {
  documentElement: { dataset: {} },
  getElementById: id => registry[id] || (registry[id] = el('div')),
  querySelector: sel => el('button'),
  querySelectorAll: () => [],
  createElement: t => el(t),
  head: el('head')
};
global.document = doc;
global.localStorage = { getItem: () => null, setItem() {} };
global.matchMedia = () => ({ matches: false });
global.scrollTo = () => {};
global.addEventListener = (ev, fn) => { if (ev === 'hashchange') hashListeners.push(fn); };
global.location = {
  _h: '',
  get hash() { return this._h; },
  set hash(v) { const same = this._h === v; this._h = v; if (!same) hashListeners.forEach(f => { try { f(); } catch (e) { console.error('HASHCHANGE FAIL:', e.message); process.exit(1); } }); },
  href: ''
};
global.fetch = () => Promise.reject(new Error('offline-smoke'));
Object.assign(global.window, { addEventListener: (ev, fn) => { if (ev === 'hashchange') hashListeners.push(fn); }, matchMedia: global.matchMedia, localStorage: global.localStorage, location: global.location, scrollTo: global.scrollTo, document: doc, CHAI_PD: {} });

// --- 抽取内联主 JS 并执行（含初始 route()）---
const html = fs.readFileSync('/root/chailive/scripts/template-living.html', 'utf8');
const parts = html.split('<script>');
const inline = parts[parts.length - 1].split('</script>')[0];
try {
  new Function(inline).call(global.window);
} catch (e) { console.error('RUNTIME FAIL:', e.stack.split('\n').slice(0, 3).join(' | ')); process.exit(1); }

const stream = () => registry.stream.innerHTML;
const count = (re) => (stream().match(re) || []).length;

// --- 断言 1：home 视图（初始 route）---
const modsHome = count(/class="modc"/g);
console.log(`home-view: ${modsHome} module cards`);
if (modsHome !== 6) { console.error('SMOKE FAIL home mods != 6'); process.exit(1); }

// --- 断言 2：all 视图 31 章 19262 卡 ---
global.location.hash = '#all';
const chaps = count(/class="chap"/g), cards = count(/class="card"/g);
console.log(`all-view: ${chaps} chapter sections, ${cards} cards`);
if (chaps !== 31 || cards !== 19262) { console.error(`SMOKE FAIL all-view ${chaps}/31 ${cards}/19262`); process.exit(1); }

// --- 断言 3：chap 视图（最大章 ch01=5950）---
global.location.hash = '#c-ch01';
const c1 = count(/class="card"/g);
console.log(`chap-view ch01: ${c1} cards`);
if (c1 !== 5950) { console.error(`SMOKE FAIL ch01 ${c1}/5950`); process.exit(1); }

// --- 断言 4：mod 视图（m1=6671）---
global.location.hash = '#m-m1';
const m1 = count(/class="card"/g);
console.log(`mod-view m1: ${m1} cards`);
if (m1 !== 6671) { console.error(`SMOKE FAIL m1 ${m1}/6671`); process.exit(1); }

// --- 断言 5：AI 面板绑定 + 检索召回（中文整句问题）---
if (typeof global.window.tokenize !== 'function') {
  // tokenize 未导出——通过 DOM 交互验证：aiFab 点击 + aiForm 提交
  try { registry.aiFab.onclick(); } catch (e) { console.error('SMOKE FAIL aiFab click:', e.message); process.exit(1); }
  console.log('ai-panel: fab toggle ok');
} else {
  const hit = global.window.tokenize('怎么跟青春期孩子说话');
  if (hit.length < 3) { console.error('SMOKE FAIL tokenize recall', hit); process.exit(1); }
  console.log(`ai-retrieve: tokenize → ${hit.length} tokens`);
}

// --- 断言 6：__clFill RIA 钩子 + 数据分片存在 ---
if (typeof global.window.__clFill !== 'function') { console.error('SMOKE FAIL no __clFill'); process.exit(1); }
const withRia = CARDS.find(c => c.x === 1);
const dpath = `/root/chailive/data/${withRia.b}.js`;
if (!fs.existsSync(dpath)) { console.error('SMOKE FAIL data shard missing', dpath); process.exit(1); }
console.log(`ria-hook: __clFill ok, shard ${withRia.b}.js exists`);

// --- 断言 7：每日一拆视图 ---
global.location.hash = '#daily';
const dh = count(/class="dh"/g), cards1 = count(/class="card"/g);
if (dh !== 1 || cards1 !== 1) { console.error(`SMOKE FAIL daily ${dh}/1 hero, ${cards1}/1 card`); process.exit(1); }
console.log('daily-view: hero + 1 card ok');

// --- 断言 8：知识地图视图（6 模块卡 + 31 章节点）---
global.location.hash = '#map';
const mc = count(/class="modcard"/g), dots = count(/class="chdot/g);
if (mc !== 6 || dots !== 31) { console.error(`SMOKE FAIL map ${mc}/6 modcards, ${dots}/31 chdots`); process.exit(1); }
console.log('map-view: 6 modcards + 31 chdots ok');

// --- 断言 9：练武场挂载（__clFill 注入 np-box，写入便签触发评审流）---
global.location.hash = '#daily';
const dailyCard = registry.stream.children.find ? null : null;
// 直接找 stream 里第一张卡（stub 里 stream.innerHTML 是字符串，改由 __clFill 语义验证）
if (!stream().includes('np-box')) { console.error('SMOKE FAIL card missing np-box mount'); process.exit(1); }
console.log('practice-mount: np-box present in cardHTML ok');

// --- 断言 10：海报函数存在 ---
const fn = ['openPoster','closePoster','dlPoster','cpPoster','drawPoster'];
const missing = fn.filter(f => typeof global[f] !== 'function' && typeof global.window[f] !== 'function');
if (missing.length) { console.error('SMOKE FAIL poster fns missing:', missing); process.exit(1); }
console.log('poster-fns: all present ok');

console.log('SMOKE PASS: home/all/chap/mod/daily/map 六视图 + 练武场 + AI 面板 + RIA + 海报全过');

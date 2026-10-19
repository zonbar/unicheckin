/* ======================================================================
   前端运行时自测（用 jsdom 真跑一遍）

   为什么需要它：前端契约测试（test_panel_static.py）只做**文本检查** ——
   断言某个字符串在不在文件里。它抓不到「脚本一加载就抛异常」这类问题，
   而那恰恰是最致命的：app.js 初始化阶段一throw，整个界面停在
   「正在连接面板」，所有功能全废，但服务端一切正常、日志里也看不到线索。

   这里用 jsdom 加载真实页面并执行两个脚本，抓两类问题：
     1. 初始化阶段有没有抛异常（含跨文件作用域错误）
     2. 自绘下拉真的能用吗 —— 填选项、读写value、点选、展开收起

   跑法：node tools/test_frontend_runtime.js
   依赖 jsdom，装在临时目录里，不进项目依赖。
   ====================================================================== */

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "panel", "static");

let JSDOM;
try {
  ({ JSDOM } = require(process.env.JSDOM_PATH || "jsdom"));
} catch (_) {
  console.log("跳过：找不到 jsdom。");
  console.log("  npm install jsdom 后重跑，或设 JSDOM_PATH 指向它。");
  process.exit(0);
}

let pass = 0;
let fail = 0;
const failed = [];

function check(name, cond, extra = "") {
  if (cond) {
    pass++;
    console.log(`  [OK]   ${name}`);
  } else {
    fail++;
    failed.push(name);
    console.log(`  [FAIL] ${name} ${extra}`);
  }
}

function section(t) {
  console.log("");
  console.log(t);
}

/* ---------- 加载页面 ---------- */
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const dom = new JSDOM(html, {
  url: "http://127.0.0.1/",
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const { window } = dom;
const doc = window.document;

// 页面运行所需的最小桩：这几个脚本只用到这三样
window.fetch = () => Promise.resolve({ ok: true, json: async () => ({}) });
window.localStorage.clear();

section("1) 脚本加载：初始化阶段不能抛异常");
/* dropdown.js 必须先于 app.js —— 它往 window.DD_PROXY 注册代理，
   app.js 的 $() 初始化时要能查到。顺序反了 app.js 照样能跑，
   但下拉会静默退化成原生控件，问题更难查。 */
const scripts = [...doc.querySelectorAll("script[src]")].map((s) => s.getAttribute("src"));
const ddi = scripts.findIndex((s) => /dropdown\.js$/.test(s));
const api = scripts.findIndex((s) => /app\.js$/.test(s));
check("dropdown.js 先于 app.js 加载", ddi !== -1 && api !== -1 && ddi < api, scripts.join(" → "));

for (const f of ["dropdown.js", "app.js"]) {
  const src = fs.readFileSync(path.join(ROOT, f), "utf8");
  let err = null;
  try {
    window.eval(src);
  } catch (e) {
    err = e;
  }
  check(`${f} 执行无异常`, !err, err ? `${err.message} @ ${(err.stack || "").split("\n")[1] || ""}` : "");
  if (err) {
    // 一旦抛异常，后续断言都不可信了
    console.log("");
    console.log("  初始化中断，剩余用例跳过。");
    break;
  }
}
if (fail) {
  console.log("");
  console.log("通过 " + pass + "  失败 " + fail);
  process.exit(1);
}

/* ---------- 下拉的可用性 ---------- */
const $ = (id) => window.DD_PROXY[id] || doc.getElementById(id);

section("2) 自绘下拉：结构");
const ddWraps = doc.querySelectorAll(".dd");
check("原生 select 全部升级", ddWraps.length >= 7, `实际 ${ddWraps.length} 个 .dd`);
check("原生 select 保留在 DOM 里当数据源",
  doc.querySelectorAll("select.dd-native").length >= 7);
check("按钮有初始文字",
  (doc.querySelector(".dd-btn .dd-label") || {}).textContent?.length > 0);

section("3) 自绘下拉：innerHTML 填选项");
const gf = $("groupFilter");
check("$ 返回代理对象", !!gf && !!gf.__wrap);
if (gf) {
  // app.js::render 就是这么填的
  gf.innerHTML =
    '<option value="all">全部分类</option>' +
    '<option value="social">社交</option>' +
    '<option value="tool">工具</option>';
  const items = doc.querySelectorAll('.dd[data-dd="groupFilter"] .dd-item');
  check("填充出 3 个列表项", items.length === 3, `实际 ${items.length}`);
  check("列表项带正确的 data-value", items[1] && items[1].dataset.value === "social");
  check("原生 select 也同步了选项",
    [...doc.querySelectorAll("select.dd-native")].some((s) =>
      [...s.options].some((o) => o.value === "social")));
}

section("4) 自绘下拉：value 读写");
if (gf) {
  gf.value = "tool";
  check("写 value 后 getter 读到", gf.value === "tool", `实际 ${JSON.stringify(gf.value)}`);
  check("选中项高亮到正确一条",
    (doc.querySelector(".dd[data-dd=groupFilter] .dd-item.sel") || {}).dataset?.value === "tool");
  check("按钮文字跟着变",
    doc.querySelector('.dd[data-dd="groupFilter"] .dd-label').textContent === "工具");
}

section("5) 自绘下拉：点选与展开收起");
if (gf) {
  let fired = false;
  gf.onchange = () => { fired = true; };
  doc.querySelector('.dd[data-dd="groupFilter"] .dd-item[data-value="social"]')
    .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  check("点列表项触发 onchange", fired);
  check("点选后 value 更新", gf.value === "social", `实际 ${JSON.stringify(gf.value)}`);

  const wrap = doc.querySelector('.dd[data-dd="groupFilter"]');
  // 打开时菜单会被移到 body 下，所以要用全局查询，不能从 wrap 里找
  check("默认收起（不在 body 下且无 .on）",
    doc.querySelector(".dd-menu.on") === null
    && !doc.body.classList.contains("x"));
  wrap.querySelector(".dd-btn").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const menuOpen = doc.querySelector(".dd-menu.on");
  check("点按钮展开（菜单带上 .on）", !!menuOpen);
  check("展开时菜单挂在 body 下（脱离祖先 overflow 裁切）",
    !!menuOpen && menuOpen.parentNode === doc.body,
    menuOpen ? menuOpen.parentNode.nodeName : "");
  wrap.querySelector(".dd-btn").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const mClosed = doc.querySelector(".dd-menu");
  check("再点收起（.on 摘掉、菜单回到 .dd 里）",
    doc.querySelector(".dd-menu.on") === null
    && !!mClosed.parentNode.classList.contains("dd")
    && !wrap.classList.contains("open"));
}

section("6) 跨文件作用域（这几处曾经真的炸过）");
const ddSrc = fs.readFileSync(path.join(ROOT, "dropdown.js"), "utf8");
// $ 与 esc 都是 app.js 的局部 const，dropdown.js 里引用会直接抛
// "$ is not defined"，页面卡在「正在连接面板」。
const codeOnly = ddSrc
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/\/\/.*$/gm, "");
check("dropdown.js 不引用 app.js 的 $", !/(?<![a-zA-Z0-9_$])\$\s*\(/.test(codeOnly));
check("dropdown.js 不引用 app.js 的 esc", !/(?<![a-zA-Z0-9_])esc\s*\(/.test(codeOnly));

section("7) 推送渠道开关");
const appSrc = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
// 渠道方框是 openSettings 时渲染的，这里验证绑定方式 —— 必须用委托，
// 因为 #noticeGroups 的 innerHTML 每次打开设置页都会重画，直接绑会丢。
check("开关用事件委托绑定在 #noticeGroups 上",
  appSrc.includes('$("noticeGroups").addEventListener("change"'));
check("保存时按组跳过关闭的渠道",
  appSrc.includes('box.querySelectorAll("[data-notice]")')
  && appSrc.includes("if (on && !on.checked) return;"));
check("切换开关会收起/展开该组字段",
  appSrc.includes("function applyChannelToggle") && /if \(f\) f\.hidden = off;/.test(appSrc));
check("初始收起在渲染之后调用（此前写在 bind 里，元素还不存在）",
  appSrc.includes('$("noticeGroups").innerHTML = noticeHTML(st);') &&
  /innerHTML = noticeHTML\(st\);\s*\n\s*initChannelToggles\(\)/.test(appSrc));

console.log("");
console.log("=".repeat(66));
console.log(`通过 ${pass}  失败 ${fail}`);
if (fail) {
  console.log("失败项：" + failed.join("、"));
  process.exit(1);
}
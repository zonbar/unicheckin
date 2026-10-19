/* ======================================================================
   自绘下拉：替代原生 <select>

   为什么不用原生：原生 select 点开弹出的是**系统控件面板**，
   那是一层独立窗口，CSS 完全管不到 —— 想让它贴着按钮展开、
   用品牌紫做选中态、不想要原生那圈系统边框，都做不到。
   桌面浏览器上尤其明显：点开就是一个灰底的系统菜单，
   和面板本身的风格完全不搭。

   这里做的是**接口等价的代理**：对上层完全像 <select>，
   一样有 .value（读写）、.innerHTML（塞 <option>）、.onchange（赋值）。
   所以 app.js 里 `el.value = x` / `el.innerHTML = html` / `el.onchange = fn`
   这些原有代码一行都不用改，只是底层从原生控件换成了 div + 列表。

   用法：
     <div class="dd" data-dd="filter">
       <button class="dd-btn" type="button"><span class="dd-label"></span>
         <svg class="dd-caret">…</svg></button>
       <div class="dd-menu" hidden></div>
     </div>

   .innerHTML 收到的 <option value="x">文字</option> 会被解析成列表项。
   ====================================================================== */

/* 把代理的选中态刷到 UI 上：列表高亮 + 按钮文字。
   放在模块级而不是 makeProxy 内部 —— makeDD 在建代理时就要用它，
   闭包里的函数那时还没创建出来。 */
function syncFromNative(api, sel) {
  const wrap = api && api.__wrap;
  if (!wrap) return;
  const menu = wrap.querySelector(".dd-menu");
  const label = wrap.querySelector(".dd-label");
  if (!menu || !label) return;
  const v = sel ? sel.value : api.__value || "";
  let found = null;
  for (const it of menu.querySelectorAll(".dd-item")) {
    const on = it.dataset.value === v;
    it.classList.toggle("sel", on);
    it.setAttribute("aria-selected", on ? "true" : "false");
    if (on) found = it;
  }
  const text =
    (found && found.dataset.label) ||
    (sel && sel.selectedOptions[0] && sel.selectedOptions[0].textContent) ||
    "";
  label.textContent = text || "—";
}

/** 把 <option ...>文本</option> 串转成真正的 <option> 元素列表 */
function parseOptions(html) {
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  return Array.from(tmp.querySelectorAll("option")).map((o) => {
    const n = document.createElement("option");
    n.value = o.value;
    n.textContent = o.textContent;
    return n;
  });
}

/** 把 <option ...>文本</option> 串转成 dd-item 列表 */
function htmlToItems(html) {
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  const opts = tmp.querySelectorAll("option");
  if (!opts.length) return html; // 不是 option 串，原样保留
  return Array.from(opts).map(optionToHTML).join("");
}

/* 升级一个下拉控件，就地替换。
   传 id 或 DOM 元素都行；已升级过则直接返回（幂等，可重复调用）。

   返回值是**代理对象**（带 value / innerHTML / onchange / options），
   不是原select。app.js 里所有 $(id).value / .innerHTML / .onchange
   都得走代理，所以升级后要把 $(id) 的返回也换成代理 —— 见下方 registerDD。

   ⚠ 这里**不能用 $()**：$ 是 app.js 里的局部 const，跨文件取不到，
   在这个文件里引用会在初始化时报 "$ is not defined"，
   整个 app.js 当场中断，页面卡在「正在连接面板」。用原生查询。 */
function makeDD(target) {
  const sel = typeof target === "string"
    ? document.getElementById(target)
    : target;
  if (!sel) return null;
  if (sel.__dd) return sel.__dd;

  const wrap = document.createElement("div");
  wrap.className = "dd";
  if (sel.className) wrap.className += " " + sel.className;
  // 原来写在 select 上的行内样式（max-width:240px / width:auto）
  // 要搬到 wrapper 上 —— select 自己已经被藏起来了，样式对它没有意义。
  const cs = sel.getAttribute("style") || "";
  if (cs) {
    for (const rule of cs.split(";")) {
      const prop = rule.split(":")[0].trim();
      if (prop === "width") continue;            // 交给 .dd 的默认宽度规则
      wrap.style.setProperty(prop, rule.split(":").slice(1).join(":").trim());
    }
    if (/max-width:\s*240px/.test(cs)) wrap.classList.add("dd-wide");
  }
  const ddId = sel.id || "";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "dd-btn";
  if (sel.title) btn.title = sel.title;

  const label = document.createElement("span");
  label.className = "dd-label";
  const caret = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  caret.setAttribute("viewBox", "0 0 16 16");
  caret.setAttribute("class", "dd-caret");
  caret.setAttribute("aria-hidden", "true");
  caret.innerHTML =
    '<path d="M4 6.2 8 10.2l4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>';
  btn.append(label, caret);

  const menu = document.createElement("div");
  menu.className = "dd-menu";
  menu.setAttribute("role", "listbox");

  wrap.append(btn, menu);
  sel.parentNode.insertBefore(wrap, sel);
  // 原生 select 只做数据源：藏着但保留在 DOM 里
  // —— value / innerHTML / options 全靠它，省掉一整套状态同步。
  sel.classList.add("dd-native");

  const api = makeProxy(wrap, sel);
  wrap.__dd = api;
  sel.__dd = api;
  if (ddId) { registerDD(ddId, api); sel.removeAttribute("id"); wrap.dataset.dd = ddId; }
  // 先把选项搬进列表，再刷选中态（顺序反了刷不到任何一项）
  if (sel.options.length) menu.innerHTML = Array.from(sel.options).map(optionToHTML).join("");
  syncFromNative(api, sel);
  return api;
}

/* HTML 转义。app.js 里有个同名的 esc，但那是它自己的局部变量，
   跨文件取不到 —— 这里必须自带一份，否则一调optionToHTML 就报
   "esc is not defined"。 */
const ddEsc = (v) =>
  String(v == null ? "" : v).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

function optionToHTML(o) {
  const v = ddEsc(o.value);
  const t = ddEsc(o.textContent);
  return `<div class="dd-item" role="option" data-value="${v}" data-label="${t}">${t}</div>`;
}

/* 代理对象：把 .value / .innerHTML / .onchange 转发到底层 */
function makeProxy(wrap, sel) {
  const btn = wrap.querySelector(".dd-btn");
  const label = wrap.querySelector(".dd-label");
  const menu = wrap.querySelector(".dd-menu");

  const api = {
    __wrap: wrap,
    onchange: null,
    /* 外部读 .value 得到当前选中项；写 .value 要同时更新列表高亮、
       按钮文字和底层 select —— app.js 里有 `el.value = "xxx"` 这种写法。
       getter 以**代理自己的记录**为准：原生 select 只有在选项已同步过去时
       才认得这个值，否则 select.value 会静默返回 ""。 */
    get value() { return api.__value || ""; },
    set value(v) {
      api.__value = v;
      if (sel) {
        // 原生 select 里没有这一项时，先补上再赋值，否则赋值无效
        if (![...sel.options].some((o) => o.value === v)) {
          const o = document.createElement("option");
          o.value = v;
          o.textContent = v;
          sel.appendChild(o);
        }
        sel.value = v;
      }
      syncFromNative(api, sel);
    },
    get options() {
      // 调用方偶尔会读 options.length
      return sel ? sel.options : [];
    },
    get innerHTML() { return menu.innerHTML; },
    set innerHTML(html) {
      /* 设 innerHTML 是各处填 options 的地方（app.js 里五处）。
         两处都要更新：
           1. 列表 DOM —— 用户看到的那层
           2. 原生 select —— 唯一数据源，读 .value / .options 都靠它
         只更 1 的话，随后 `el.value = "xxx"` 会因为 select 里没有该项
         而静默失效（原生 select 的行为：赋值不存在的值会保持原样）。 */
      menu.innerHTML = htmlToItems(html);
      if (sel) {
        const opts = parseOptions(html);
        sel.innerHTML = "";
        for (const o of opts) sel.appendChild(o);
      }
      // innerHTML 换掉选项后，原选中项可能已不存在 —— 回落到第一项
      if (![...sel.options].some((o) => o.value === api.__value)) {
        api.__value = sel.options.length ? sel.options[0].value : "";
      }
      syncFromNative(api, sel);
    },
    close,
    toggle,
  };

  function close() {
    wrap.classList.remove("open");
    menu.classList.remove("on");
    btn.setAttribute("aria-expanded", "false");
    detachMenu();
  }

  /* 把弹出层挂到 <body> 下，用 fixed 定位。
     为什么不能就放在 .dd 里：设置页的 .settings-panes、运行日志的 .drawer-body
     都设了 overflow-y:auto，弹出层作为它们的子元素会被**裁切**——
     在这些区域向上展开时列表顶部会被切掉一截（看起来像"贴在容器顶上"）。
     挂到 body + fixed 就脱离了所有祖先的裁切，任何位置都能完整显示。 */
  function attachMenu() {
    if (menu.parentNode !== document.body) document.body.appendChild(menu);
    placeMenu();
  }
  function detachMenu() {
    if (menu.parentNode === wrap) wrap.appendChild(menu);
  }

  /* 按按钮的实际位置定位，并挑空间大的一侧展开 */
  function placeMenu() {
    const r = btn.getBoundingClientRect();
    const mh = menu.offsetHeight || 200;
    const below = window.innerHeight - r.bottom;
    const up = below < mh + 12 && r.top > mh + 12;   // 下方不够且上方够→ 向上
    menu.style.left = `${r.left}px`;
    menu.style.width = `${r.width}px`;
    if (up) menu.style.top = `${Math.max(8, r.top - mh - 4)}px`;
    else menu.style.top = `${Math.min(r.bottom + 4, window.innerHeight - mh - 8)}px`;
    wrap.classList.toggle("up", up);
  }

  function toggle() {
    if (wrap.classList.contains("open")) return close();
    // 同时只开一个
    for (const o of document.querySelectorAll(".dd.open")) {
      o.__dd && o.__dd.close();
    }
    attachMenu();
    wrap.classList.add("open");
    menu.classList.add("on");
    btn.setAttribute("aria-expanded", "true");
    placeMenu();
    const cur = menu.querySelector(".dd-item.sel");
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest" });
  }

  // --- 交互 ---
  btn.addEventListener("click", toggle);

  menu.addEventListener("click", (ev) => {
    const it = ev.target.closest(".dd-item");
    if (!it) return;
    for (const x of menu.querySelectorAll(".dd-item.sel")) x.classList.remove("sel");
    it.classList.add("sel");
    it.setAttribute("aria-selected", "true");
    api.value = it.dataset.value;
    label.textContent = it.dataset.label || "—";
    close();
    if (sel) sel.value = api.value;
    const fn = api.onchange;
    if (typeof fn === "function") fn({ target: sel || api });
  });

  // 键盘：上下移动 + Enter 选中 + Esc 关闭
  wrap.addEventListener("keydown", (ev) => {
    const items = Array.from(menu.querySelectorAll(".dd-item"));
    const at = items.indexOf(document.activeElement);
    if (ev.key === "Escape") { close(); btn.focus(); return; }
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      if (!wrap.classList.contains("open")) return toggle();
      const next = ev.key === "ArrowDown"
        ? Math.min(at + 1, items.length - 1)
        : Math.max(at - 1, 0);
      if (items[at]) items[at].classList.remove("sel");
      items[next].classList.add("sel");
      items[next].focus();
    } else if (ev.key === "Enter" || ev.key === " ") {
      if (at >= 0 && items[at]) { ev.preventDefault(); items[at].click(); }
    }
  });

  // 点外面关闭。菜单挂在 body 下，判断要同时看 wrap 和 menu。
  document.addEventListener("mousedown", (ev) => {
    if (!wrap.classList.contains("open")) return;
    if (wrap.contains(ev.target) || menu.contains(ev.target)) return;
    close();
  });
  // 挂在 body 下之后，滚动/缩放要重新对齐按钮位置，
  // 否则窗口一动菜单就留在原地、跟按钮错位。
  if (typeof window.addEventListener === "function") {
    window.addEventListener("resize", () => { if (wrap.classList.contains("open")) placeMenu(); });
    window.addEventListener("scroll", () => { if (wrap.classList.contains("open")) placeMenu(); }, true);
  }

  // 原生 select 若被别处直接改value，代理这边跟着走
  if (sel) {
    sel.addEventListener("change", () => syncFromNative(api, sel));
    new MutationObserver(() => syncFromNative(api, sel)).observe(sel, {
      childList: true, subtree: true, attributes: true,
    });
  }

  return api;
}

/* 升级一批下拉（幂等，可重复调用）。
   升级后把 id 挂到 wrapper 上，让 patchDollar 能把 $() 导向代理。 */
function upgradeSelects(ids) {
  for (const id of ids) makeDD(id);
}

/* 让 $(id) 对已升级的下拉返回代理而不是原生 select。
   跨文件共享，所以表挂在 window 上：app.js 里的
   `const $ = (id) => window.DD_PROXY[id] || document.getElementById(id)`
   于是所有 $(id).value / .innerHTML / .onchange 自动打到代理上，
   app.js 原有几十处调用一行都不用改。 */
window.DD_PROXY = window.DD_PROXY || {};
function registerDD(id, api) {
  window.DD_PROXY[id] = api;
  api.__id = id;
}

/* 设置 value（代理对象的属性赋值走这里） */
Object.defineProperty(Object.prototype, "__noop", { value: 0, enumerable: false });
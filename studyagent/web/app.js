"use strict";
/* ============ core ============ */
let TOKEN = localStorage.getItem("sa_token") || "";
const IN_APP = /StudyAgentApp/.test(navigator.userAgent);
const APP_HOME = /iPhone|iPad|iPod/.test(navigator.userAgent) ? "capacitor://localhost/?switch=1" : "https://localhost/?switch=1";
if (IN_APP) document.documentElement.classList.add("in-app");
let B = null;               // bootstrap data
let CATS = [];              // categories of current subject
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function toast(t) { const el = $("#toast"); el.textContent = t; el.classList.add("on"); clearTimeout(toast._t); toast._t = setTimeout(() => el.classList.remove("on"), 2600); }
function md(s) {
  s = esc(s);
  s = s.replace(/```(\w*)\n([\s\S]*?)```/g, (m, l, c) => `<pre class="refcode"><code>${c}</code></pre>`);
  s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  s = s.replace(/(https?:\/\/[^\s<)）]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  return s;
}
function twoStep(btn, label, fn) { if (!btn) return; btn.onclick = () => { if (btn.dataset.c) { fn(); } else { btn.dataset.c = 1; btn.dataset.o = btn.textContent; btn.textContent = label; setTimeout(() => { if (btn.isConnected) { delete btn.dataset.c; btn.textContent = btn.dataset.o; } }, 4000); } }; }
const todayStr = (d = new Date()) => { const z = n => String(n).padStart(2, "0"); return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate()); };
const diffDays = (a, b) => Math.round((new Date(b + "T00:00:00") - new Date(a + "T00:00:00")) / 86400000);
const WD = ["日", "一", "二", "三", "四", "五", "六"];
const dow = s => new Date(s + "T00:00:00").getDay();
const fmtMin = ms => { const m = Math.round((ms || 0) / 60000); return m < 60 ? m + " 分钟" : (m / 60).toFixed(1) + " 小时"; };
const LANG_NAME = { python: "Python", javascript: "JavaScript", java: "Java", cpp: "C++" };
const STATUS_NAME = { todo: "未开始", doing: "进行中", done: "已完成", review: "需复习" };

async function api(path, opt = {}) {
  const o = { method: opt.method || (opt.body ? "POST" : "GET"), headers: { Authorization: "Bearer " + TOKEN } };
  if (opt.body instanceof FormData) o.body = opt.body;
  else if (opt.body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opt.body); }
  let r;
  try { r = await fetch(path, o); } catch (e) { throw new Error("连不上平台服务，确认它还在运行"); }
  if (r.status === 401) { showLogin(); throw new Error("请先登录"); }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || ("请求失败（" + r.status + "）"));
  return data;
}
/* SSE over fetch: onEvent receives {type,...}; returns final event */
async function stream(path, body, onEvent, signal) {
  const r = await fetch(path, { method: "POST", headers: { Authorization: "Bearer " + TOKEN, "Content-Type": "application/json" }, body: JSON.stringify(body || {}), signal });
  if (!r.ok) { let m = "请求失败（" + r.status + "）"; try { m = (await r.json()).error || m; } catch (e) { } throw new Error(m); }
  const rd = r.body.getReader(); const dec = new TextDecoder(); let buf = ""; let last = null;
  while (true) {
    const { value, done } = await rd.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      for (const line of chunk.split("\n")) if (line.startsWith("data: ")) { try { const ev = JSON.parse(line.slice(6)); if (ev.type) { last = ev; onEvent(ev); } } catch (e) { } }
    }
  }
  return last;
}
const tierChip = t => `<span class="chip t${t}" title="${esc(B.tiers[t]?.desc || "")}">L${t} ${esc(B.tiers[t]?.name || "")}</span>`;
const typeBadge = t => `<span class="typebadge">${esc(B.types[t] || t)}</span>`;
const catName = id => (CATS.find(c => c.id === id) || {}).name || "未分类";
const subject = () => B.subjects.find(s => s.id === B.goal.subject_id) || B.subjects[0];
const profile = () => { try { return JSON.parse(subject().exam_profile || "{}"); } catch (e) { return {}; } };

/* ============ login ============ */
async function boot() {
  if (!TOKEN) {
    try { const r = await fetch("/api/session/local"); if (r.ok) { TOKEN = (await r.json()).token; localStorage.setItem("sa_token", TOKEN); } } catch (e) { }
  }
  if (!TOKEN) return showLogin();
  try { await reloadBoot(); } catch (e) { return; }
  $("#login").hidden = true; $("#shell").hidden = false;
  render();
}
async function reloadBoot() { B = await api("/api/bootstrap"); CATS = await api("/api/categories"); $("#subjectName").textContent = subject()?.name || ""; }
function showLogin() {
  $("#shell").hidden = true; const L = $("#login"); L.hidden = false;
  L.innerHTML = `<div class="login"><h1>StudyAgent</h1><p class="lead">在这台设备上第一次使用，请输入访问码。访问码在运行平台的电脑上「设置 → 设备与互通」里查看。</p>
  <label class="f">访问码<input type="password" id="code" autocomplete="off"></label><div class="row" style="margin-top:12px"><button class="btn pri" id="go">进入</button><span id="lmsg" class="small" style="color:var(--red)"></span></div></div>`;
  if (IN_APP) L.querySelector(".login").insertAdjacentHTML("beforeend", `<p class="small" style="margin-top:14px"><a href="${APP_HOME}">连接其它电脑</a></p>`);
  $("#go").onclick = async () => { try { const r = await fetch("/api/session/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: $("#code").value.trim() }) }); const j = await r.json(); if (!r.ok) throw new Error(j.error); TOKEN = j.token; localStorage.setItem("sa_token", TOKEN); boot(); } catch (e) { $("#lmsg").textContent = e.message; } };
  $("#code").onkeydown = e => { if (e.key === "Enter") $("#go").click(); };
}

/* ============ router ============ */
const V = {};
let ROUTE = { view: "home", arg: null };
function parseHash() { const h = (location.hash || "#home").slice(1); const [v, ...rest] = h.split("-"); return { view: V[v] ? v : "home", arg: rest.join("-") || null }; }
let renderSeq = 0;
async function render() {
  if (!B) return;
  ROUTE = parseHash(); const seq = ++renderSeq;
  if (CHAT.detach && (ROUTE.view !== "chat" || String(CHAT.conv) !== String(ROUTE.arg))) { CHAT.detach.abort(); CHAT.detach = null; }
  const navOf = { q: "bank", lesson: "plan", import: "bank", classify: "bank", exam: "exams", newq: "bank" };
  $$("#nav a").forEach(a => a.classList.toggle("on", a.dataset.v === (navOf[ROUTE.view] || ROUTE.view)));
  const main = $("#main");
  try {
    const html = await V[ROUTE.view](ROUTE.arg);
    if (seq !== renderSeq) return;
    main.innerHTML = html;
    V[ROUTE.view].after && V[ROUTE.view].after(ROUTE.arg);
    bindCommon();
  } catch (e) { if (seq === renderSeq) main.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  refreshCounts();
}
function bindCommon() {
  $$("#main [data-q]").forEach(el => el.onclick = e => { if (e.target.closest("button,a,input,select")) return; location.hash = "#q-" + el.dataset.q; });
  $$("#main [data-lesson]").forEach(el => el.onclick = () => { location.hash = "#lesson-" + el.dataset.lesson; });
}
async function refreshCounts() {
  try {
    const [rv, pr, runs] = await Promise.all([api("/api/reviews"), api("/api/proposals"), api("/api/runs")]);
    const due = rv.items.filter(r => r.due && r.due <= todayStr()).length;
    $("#cntReview").textContent = due ? due + " 到期" : (rv.items.length || "");
    $("#cntProp").textContent = runs.length ? "生成中…" : (pr.length ? pr.length + " 待确认" : "");
    clearTimeout(refreshCounts._t); if (runs.length) refreshCounts._t = setTimeout(refreshCounts, 3000);
    $("#sideFoot").textContent = (B.user.name || "") + (B.lan_enabled ? " · 局域网已开启" : " · 仅本机");
  } catch (e) { }
}
addEventListener("hashchange", () => { render(); scrollTo(0, 0); });

/* activity time: only while interacting on study pages */
let lastAct = Date.now(), actAcc = 0;
["keydown", "mousedown", "touchstart", "scroll"].forEach(ev => addEventListener(ev, () => { lastAct = Date.now(); }, { passive: true }));
setInterval(() => {
  if (!B || document.hidden || Date.now() - lastAct > 120000) return;
  if (!["q", "exam", "lesson", "chat"].includes(ROUTE.view)) return;
  actAcc += 5000;
  if (actAcc >= 30000) { const ms = actAcc; actAcc = 0; api("/api/activity", { body: { ms, qid: ROUTE.view === "q" ? ROUTE.arg : null } }).catch(() => { }); }
}, 5000);

/* ============ shared renderers ============ */
function qRow(q, extra = "") {
  const rv = q.review_due ? ` · 复习 ${q.review_due <= todayStr() ? "今天到期" : q.review_due.slice(5)}` : "";
  return `<div class="qi" data-q="${esc(q.id)}" tabindex="0"><span class="st ${q.status || "todo"}"></span><div><div class="t">${esc(q.title)} ${typeBadge(q.type)}</div>
  <div class="m">${esc(q.source || "")}${q.level ? " · " + esc(q.level) : ""}${(q.points || []).length ? " · " + esc(q.points.join("、")) : ""}${rv}${q.cls_by === "default" ? " · 分层暂定" : ""}${q.skipped ? " · 已跳过" : ""}${extra}</div></div>${tierChip(q.tier)}</div>`;
}
function renderTask(t, big) {
  if (t.type === "learn") return `<div class="task lrn" data-lesson="${t.category_id}"><span>◆</span><span class="tt">学习：${esc(t.name)}（约 ${t.cost} 分钟）</span></div>`;
  if (t.type === "review") return `<div class="task" onclick="location.hash='#review'"><span>↺</span><span class="tt">错题复习 + 重做难题</span></div>`;
  return `<div class="task" data-q="${esc(t.id)}"><span class="st"></span><span class="tt">${esc(t.title)}${big ? " " + tierChip(t.tier) : ""}</span></div>`;
}
function scoreRuler(score, prof) {
  const max = prof.sections ? prof.sections.reduce((a, s) => a + s.count * s.points, 0) : 100;
  const pct = v => Math.min(100, v / max * 100);
  const pass = prof.pass, exc = prof.excellent;
  return `<div class="ruler"><div class="track"></div><div class="fill" style="width:${pct(score ?? 0)}%"></div>
    ${pass ? `<div class="tick" style="left:${pct(pass)}%"></div><div class="tl" style="left:${pct(pass)}%">${pass} 通过</div>` : ""}
    ${exc ? `<div class="tick exl" style="left:${pct(exc)}%"></div><div class="tl" style="left:${pct(exc)}%">${exc} 优秀</div>` : ""}
    <div class="tl" style="left:0;transform:none">0</div><div class="tl" style="left:100%;transform:translateX(-100%)">${max}</div>
    <div class="tv" style="${pct(score ?? 0) < 20 ? "left:0;transform:none" : "left:" + Math.min(90, pct(score)) + "%"}">${score == null ? "还没有测试成绩" : "最近测试 " + score + " 分"}</div></div>`;
}

/* ============ home ============ */
V.home = async () => {
  const P = await api("/api/plan");
  const g = P.goal; const left = Math.max(0, diffDays(todayStr(), g.exam_date));
  const qs = await api("/api/questions");
  const done = qs.filter(q => q.status === "done").length;
  const last = P.last_exam ? JSON.parse(P.last_exam.result || "null") : null;
  const week = Object.entries(P.study).filter(([d]) => diffDays(d, todayStr()) < 7).reduce((a, [, v]) => a + v, 0);
  const props = await api("/api/proposals");
  return `<div class="hero">
    <div><div class="days">${left}<small>天</small></div><div class="hero-cap">距离「${esc(g.name)}」· ${g.exam_date}</div></div>
    <div><div class="hero-stats">
      <div><b>${done}/${qs.length}</b><span>已完成题目</span></div>
      <div><b>${fmtMin(P.study[todayStr()])}</b><span>今日学习</span></div>
      <div><b>${fmtMin(week)}</b><span>近 7 天</span></div>
      <div><b>${P.independent_rate == null ? "—" : Math.round(P.independent_rate * 100) + "%"}</b><span>独立通过率</span></div>
      <div><b>${P.due_reviews.length}</b><span>今天到期复习</span></div></div>
      ${scoreRuler(last ? last.total : null, profile())}</div></div>
  ${props.length ? `<div class="notice" style="margin-bottom:14px"><b>智能体有 ${props.length} 条建议等你确认。</b> <a href="#chat">去查看</a></div>` : ""}
  ${P.overdue.length ? `<div class="notice" style="margin-bottom:14px"><b>有 ${P.overdue.length} 项逾期任务。</b>任务不会自动删除。<span class="row" style="margin-top:8px"><button class="btn sm" id="odShift">从今天起重新排期</button><a class="btn sm" href="#plan">去计划里逐项处理</a></span></div>` : ""}
  ${!B.models.length ? `<div class="notice" style="margin-bottom:14px"><b>还没有接入模型。</b> 讲解、出题、导入、分类、主观题评分都需要模型。<a class="btn sm pri" href="#models" style="margin-left:8px">去添加模型</a></div>` : ""}
  <div class="grid2">
    <div class="panel"><h2 style="margin-top:0">今日任务</h2>
      ${P.today ? P.today.tasks.map(t => renderTask(t, true)).join("") : '<div class="muted small">今天不在计划日期内。去「学习计划」调整日期。</div>'}
      ${P.today && P.today.ev ? `<div class="ev ${P.today.ev === "monthly" ? "mo" : ""}" onclick="location.hash='#exams'">${P.today.ev === "monthly" ? "月测" : "周测"}（点击开始）</div>` : ""}
      ${P.due_reviews.length ? `<h3>今天到期复习（${P.due_reviews.length}）</h3>${P.due_reviews.map(r => `<div class="task" data-q="${esc(r.question_id)}"><span>↺</span><span class="tt">${esc(r.title)} ${tierChip(r.tier)}</span></div>`).join("")}` : ""}
      ${P.tests.length ? `<h3>待做测试</h3>${P.tests.map(t => `<div class="ev ${t.type === "monthly" ? "mo" : ""}" style="display:inline-block;margin-right:6px" onclick="location.hash='#exams'">${t.date.slice(5)} ${t.type === "monthly" ? "月测" : "周测"}</div>`).join("")}` : ""}
    </div>
    <div class="panel"><h2 style="margin-top:0">各模块掌握度</h2>
      ${CATS.filter(c => !c.lesson_only).map(c => { const cq = qs.filter(q => q.category_id === c.id); if (!cq.length) return ""; const d = cq.filter(q => q.status === "done").length;
        return `<div class="topicrow"><a href="#lesson-${c.id}">${esc(c.name)}${c.lesson_done ? "" : " ·未学"}</a><div class="bar"><i style="width:${d / cq.length * 100}%"></i></div><span class="muted">${d}/${cq.length}</span></div>`; }).join("")}
      <p class="small muted" style="margin-bottom:0">完成 = 提交得满分或手动标记完成；独立通过率 = 没用提示、解析、看答案就满分的题 ÷ 全部满分的题；学习时长只计你在做题、上课、测试和智能体页面有操作的时间。</p></div>
  </div>`;
};
V.home.after = () => { twoStep($("#odShift"), "确认：已完成的保留，其余从今天重排", async () => { await api("/api/goal", { method: "PUT", body: { start_date: todayStr() } }); toast("已从今天起重新排期"); render(); }); };

/* ============ plan ============ */
V.plan = async () => {
  const P = await api("/api/plan"); const g = P.goal;
  const weeks = []; P.days.forEach(d => { const w = Math.floor(d.idx / 7); (weeks[w] = weeks[w] || []).push(d); });
  const h = m => (m / 60).toFixed(1); const t = todayStr();
  const iv = JSON.parse(g.intervals || "[1,3,7,14]");
  return `<h1>学习计划</h1>
  <p class="lead">每个模块先上课（概念 → 方法 → 例题 → 小测），再按 L1 入门 → L4 挑战的层级做题。最后 ${P.sprint} 天冲刺复习，考前最后一天全真模拟。</p>
  <div class="panel row" style="gap:14px;align-items:flex-end">
    <label class="f">目标名称<input type="text" id="gName" value="${esc(g.name)}"></label>
    <label class="f">学科<select id="gSubject">${B.subjects.map(s => `<option value="${s.id}" ${s.id === g.subject_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
    <label class="f">开始日期<input type="date" id="gStart" value="${g.start_date}"></label>
    <label class="f">考试日期<input type="date" id="gExam" value="${g.exam_date}"></label>
    <label class="f">每天学习（小时）<input type="number" id="gHours" min="0.5" max="10" step="0.5" value="${g.hours}" style="width:90px"></label>
    <label class="f">编程语言<select id="gLang">${Object.entries(LANG_NAME).map(([k, v]) => `<option value="${k}" ${k === g.lang ? "selected" : ""}>${v}${k in B.languages ? (B.languages[k] ? "" : "（本机未安装）") : "（AI 检查）"}</option>`).join("")}</select></label>
    <label class="f">周测在<select id="gWeek">${WD.map((w, i) => `<option value="${i}" ${i === g.weekly_day ? "selected" : ""}>周${w}</option>`).join("")}</select></label>
    <label class="f">月测在每月<select id="gMonth">${[...Array(31)].map((_, i) => `<option value="${i + 1}" ${i + 1 === g.monthly_day ? "selected" : ""}>${i + 1} 日</option>`).join("")}</select></label>
    <label class="f">复习间隔（天）<input type="text" id="gIv" value="${iv.join(",")}" style="width:110px"></label>
    <label class="row small" style="gap:6px"><input type="checkbox" id="gHard" ${g.include_hard ? "checked" : ""}>包含 L4 挑战题</label>
    <button class="btn pri" id="gSave">更新计划</button>
    <a class="btn" href="#chat-planner">请规划师评估</a>
  </div>
  <div class="small muted" style="margin:8px 2px 0">共 ${P.total} 天，每天 ${P.budget} 分钟，计划内 ${P.chosen} 道题。月测日期当月没有时（如 31 日）在当月最后一天进行。</div>
  ${P.over > 0 ? `<div class="notice" style="margin:14px 0"><b>时间不够：</b>共需约 ${h(P.need)} 小时，可用约 ${h(P.cap)} 小时，差 ${h(P.over)} 小时。${g.overflow ? `当前选择：<b>${g.overflow === "trim" ? "缩小范围" : "全部保留"}</b>。` : "<b>请选择处理方式</b>（下面暂按「缩小范围」预览）："}
    <div class="row" style="margin-top:8px"><button class="btn sm" data-ov="hours">每天增加到 ${P.suggest_hours} 小时</button>
    <button class="btn sm ${g.overflow === "trim" ? "dark" : ""}" data-ov="trim">缩小范围（去掉 ${P.trimmed.length || "部分"} 道优先级最低的题，核心题保留）</button>
    <button class="btn sm ${g.overflow === "extend" ? "dark" : ""}" data-ov="extend">全部保留（超出部分放进冲刺期）</button></div></div>` : ""}
  ${P.overdue.length ? `<div class="panel" style="margin:14px 0"><h3 style="margin-top:0">逾期任务（${P.overdue.length}）</h3>${P.overdue.slice(0, 20).map(o => `<div class="row" style="justify-content:space-between;border-bottom:1px solid var(--rule2);padding:5px 0"><a href="#q-${esc(o.id)}">${esc(o.title)}</a><span class="small muted">原定 ${o.date.slice(5)}</span><button class="btn sm" data-skip="${esc(o.id)}">跳过</button></div>`).join("")}<div class="row" style="margin-top:8px"><button class="btn sm" id="odShift2">全部从今天起重新排期</button></div></div>` : ""}
  ${weeks.map((w, wi) => `<div class="week" style="margin-top:18px"><div class="week-h"><b>第 ${wi + 1} 周</b><span class="small muted">${w[0].date} 至 ${w[w.length - 1].date}</span></div>
    <div class="days7">${w.map(d => `<div class="day ${d.date === t ? "today" : ""} ${d.date < t ? "past" : ""}"><div class="dh"><span>${d.date.slice(5)} 周${WD[dow(d.date)]}</span>${d.overload ? `<span style="color:var(--red)">超出 ${d.overload} 分钟</span>` : d.sprint ? "<span>冲刺</span>" : ""}</div>${d.tasks.map(x => renderTask(x)).join("")}${d.ev ? `<div class="ev ${d.ev === "monthly" ? "mo" : ""}">${d.ev === "monthly" ? "月测" : "周测"}</div>` : ""}</div>`).join("")}</div></div>`).join("")}`;
};
V.plan.after = () => {
  $("#gSave").onclick = async () => {
    const iv = $("#gIv").value.split(/[,，\s]+/).map(Number).filter(n => n > 0 && n < 366);
    try { await api("/api/goal", { method: "PUT", body: { name: $("#gName").value, subject_id: +$("#gSubject").value, start_date: $("#gStart").value, exam_date: $("#gExam").value, hours: +$("#gHours").value, lang: $("#gLang").value, weekly_day: +$("#gWeek").value, monthly_day: +$("#gMonth").value, include_hard: $("#gHard").checked ? 1 : 0, intervals: iv.length ? iv : [1, 3, 7, 14] } });
      await reloadBoot(); toast("计划已更新"); render(); } catch (e) { toast(e.message); }
  };
  $$("[data-ov]").forEach(b => b.onclick = async () => { const v = b.dataset.ov; const P = await api("/api/plan"); await api("/api/goal", { method: "PUT", body: v === "hours" ? { hours: P.suggest_hours, overflow: null } : { overflow: v } }); render(); });
  $$("[data-skip]").forEach(b => b.onclick = async () => { await api("/api/skip/" + b.dataset.skip, { body: {} }); toast("已跳过，可在题库里恢复"); render(); });
  twoStep($("#odShift2"), "确认重新排期", async () => { await api("/api/goal", { method: "PUT", body: { start_date: todayStr() } }); render(); });
};

/* ============ lesson ============ */
const LSTEPS = [["concepts", "核心概念"], ["signals", "怎么认出这类题"], ["templates", "方法与模板"], ["example", "例题精讲"], ["pitfalls", "常见错误"], ["quiz", "小测"], ["practice", "开始练习"]];
let LESSON = null, LDRAFT = null;
V.lesson = async (cid) => {
  LESSON = await api("/api/lessons/" + cid); const c = LESSON.category; const l = LESSON.lesson;
  if (!l) {
    return `<a href="#plan" class="small">返回计划</a><h1>${esc(c.name)}</h1><p class="lead">这个模块还没有课程。可以让模型根据模块名称和已有题目写一节课，生成后先预览，确认再保存。</p>
    <div class="panel"><button class="btn pri" id="lGen">让 AI 生成课程</button> <span class="small muted" id="lGenMsg"></span><div id="lDraft"></div></div>`;
  }
  const st = LESSON.state || {}; const steps = LSTEPS.filter(([k]) => !(k === "templates" && !(l.templates || []).length) && !(k === "example" && !l.example) && !(k === "practice" && c.lesson_only));
  st.step = Math.min(st.step || 0, steps.length - 1); const [sk, sname] = steps[st.step];
  const code = c => `<div class="codewrap"><pre class="refcode"><code>${esc(c)}</code></pre></div>`;
  let body = "";
  if (sk === "concepts") body = l.concepts.map(x => `<h3>${esc(x.t)}</h3><div class="lesson-text">${md(x.b)}</div>${x.code ? code(x.code) : ""}`).join("");
  if (sk === "signals") body = `<ul>${l.signals.map(x => `<li>${md(x)}</li>`).join("")}</ul>`;
  if (sk === "templates") body = l.templates.map(x => `<h3>${esc(x.t)}</h3>${code(x.code)}`).join("") + (B.goal.lang !== "python" && subject()?.name.includes("编程") ? `<button class="btn sm" id="lRewrite">让 AI 改写成 ${LANG_NAME[B.goal.lang]}</button><div id="lRewriteOut"></div>` : "");
  if (sk === "example") { const ex = l.example; const q = ex.q; body = `<h3>${esc(q ? q.title : ex.title || "例题")} ${q ? tierChip(q.tier) : ""}</h3><div class="lesson-text muted small">${esc((q ? q.stem : ex.stem || "").slice(0, 300))}</div><h3>思路</h3><ol class="steps">${ex.steps.map(x => `<li>${md(x)}</li>`).join("")}</ol>${q ? `<p><a class="btn pri" href="#q-${esc(q.id)}">自己动手做这道题</a></p>` : ""}`; }
  if (sk === "pitfalls") body = `<ul>${l.pitfalls.map(x => `<li>${md(x)}</li>`).join("")}</ul>`;
  if (sk === "quiz") {
    const sub = st.quizDone; const ans = st.answers || {};
    body = l.quiz.map((q, i) => `<div class="quiz"><b>${i + 1}. ${esc(q.q)}</b>${q.o.map((o, j) => { const sel = ans[i] === j; const cls = sub ? (j === q.a ? "right" : (sel ? "wrong" : "")) : ""; return `<label class="opt ${cls}"><input type="radio" name="q${i}" value="${j}" ${sel ? "checked" : ""} ${sub ? "disabled" : ""}> ${esc(o)}</label>`; }).join("")}${sub ? `<div class="small ${ans[i] === q.a ? "ok-t" : "bad-t"}">${ans[i] === q.a ? "答对了。" : "答错了。"}${esc(q.e)}</div>` : ""}</div>`).join("")
      + (sub ? `<p><b>得分 ${st.quizScore}/${l.quiz.length}</b> <button class="btn sm" id="lRetry">重做小测</button></p>` : `<button class="btn pri" id="lQuiz">提交小测</button> <span class="small muted" id="lQuizMsg"></span>`);
  }
  if (sk === "practice") { const qs = await api("/api/questions?category=" + c.id); body = `<p>按层级从简单到复杂做。</p>` + [1, 2, 3, 4].filter(t => qs.some(q => q.tier === t)).map(t => `<h3>${tierChip(t)} <span class="small muted">${esc(B.tiers[t].desc)}</span></h3><div class="qlist">${qs.filter(q => q.tier === t).map(q => qRow(q)).join("")}</div>`).join("") || '<div class="muted">这个模块还没有题。可以去「题库 → 导入题目」。</div>'; }
  LESSON.steps = steps; LESSON.st = st;
  return `<div class="row" style="justify-content:space-between"><a href="#plan" class="small">返回计划</a><span class="small muted">约 ${l.minutes || 30} 分钟${LESSON.done_at ? " · 已学完" : ""}${LESSON.by && LESSON.by !== "builtin" ? " · AI 生成的课程" : ""}</span></div>
  <h1>${esc(c.name)}</h1><p class="lead">${esc(l.intro || "")}</p>
  <div class="stepper">${steps.map(([k, n], i) => `<button class="stp ${i === st.step ? "on" : ""} ${i < st.step || LESSON.done_at ? "past" : ""}" data-step="${i}"><span>${i + 1}</span>${n}</button>`).join("")}</div>
  <div class="lesson-grid"><div class="panel lesson"><h2 style="margin-top:0">${st.step + 1}. ${sname}</h2>${body}
    <div class="row" style="justify-content:space-between;margin-top:22px;border-top:1px solid var(--rule2);padding-top:14px">
      <button class="btn" id="lPrev" ${st.step === 0 ? "disabled" : ""}>上一步</button>
      ${st.step < steps.length - 1 ? `<button class="btn pri" id="lNext">下一步：${steps[st.step + 1][1]}</button>` : (LESSON.done_at ? '<span class="small muted">本课已完成</span>' : `<button class="btn pri" id="lDone">完成本课</button>`)}</div></div>
    <div class="panel"><h3 style="margin-top:0">学习资源</h3><div class="linkcol small">${["B 站", "YouTube"].map(p => `<a target="_blank" rel="noopener" href="${p === "B 站" ? "https://search.bilibili.com/all?keyword=" : "https://www.youtube.com/results?search_query="}${encodeURIComponent(c.name + " " + (subject()?.name || ""))}">在 ${p} 搜索</a>`).join("")}</div>
      ${LESSON.resources.length ? `<div class="small" style="margin-top:6px">${LESSON.resources.map(r => `<div><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a></div>`).join("")}</div>` : ""}
      <h3>问 AI</h3><textarea id="lAsk" rows="3" style="width:100%" placeholder="这一节哪里没看懂？"></textarea><button class="btn sm" id="lAskBtn" style="margin-top:6px">提问</button><div id="lAskOut"></div>
      ${LESSON.by !== "builtin" ? `<h3>课程内容</h3><button class="btn sm" id="lRegen">让 AI 重新生成</button><div id="lDraft"></div>` : ""}</div></div>`;
};
async function saveLessonState(cid, patch) { const r = await api(`/api/lessons/${cid}/state`, { method: "PUT", body: patch }); return r; }
function draftPreview(d) {
  return `<div class="aibox" style="margin-top:10px"><div class="small muted">AI 生成的课程草稿，请先看一遍，确认无误再保存。</div><b>${esc(d.name)}</b>（约 ${d.minutes} 分钟）<div>${esc(d.intro)}</div>
  <div class="small">概念 ${d.concepts.length} 个 · 方法 ${d.templates.length} 个 · 小测 ${d.quiz.length} 题${d.example ? " · 含例题精讲" : ""}</div>
  <details><summary>展开全部内容</summary>${d.concepts.map(c => `<h3>${esc(c.t)}</h3><div class="lesson-text">${md(c.b)}</div>`).join("")}<h3>小测</h3>${d.quiz.map(q => `<div>${esc(q.q)}（答案：${esc(q.o[q.a])}）</div>`).join("")}</details>
  <div class="row" style="margin-top:8px"><button class="btn pri" id="lSaveDraft">保存为本模块课程</button><button class="btn" id="lDropDraft">放弃</button></div></div>`;
}
V.lesson.after = (cid) => {
  const gen = async () => { const m = $("#lGenMsg") || $("#lDraft"); if (m) m.textContent = "生成中，大约需要 20–60 秒…"; try { const r = await api(`/api/lessons/${cid}/generate`, { body: {} }); LDRAFT = r.draft; $("#lDraft").innerHTML = draftPreview(LDRAFT); if ($("#lGenMsg")) $("#lGenMsg").textContent = "";
      $("#lSaveDraft").onclick = async () => { await api(`/api/lessons/${cid}`, { method: "PUT", body: { content: LDRAFT, by: "ai" } }); toast("课程已保存"); render(); }; $("#lDropDraft").onclick = () => { $("#lDraft").innerHTML = ""; }; } catch (e) { if (m) m.textContent = e.message; } };
  if ($("#lGen")) $("#lGen").onclick = gen;
  if ($("#lRegen")) $("#lRegen").onclick = gen;
  if (!LESSON.lesson) return;
  const st = LESSON.st, steps = LESSON.steps, l = LESSON.lesson;
  const go = async (n) => { await saveLessonState(cid, { step: n }); render(); scrollTo(0, 0); };
  $$("[data-step]").forEach(b => b.onclick = () => go(+b.dataset.step));
  if ($("#lPrev")) $("#lPrev").onclick = () => go(Math.max(0, st.step - 1));
  if ($("#lNext")) $("#lNext").onclick = () => { if (steps[st.step][0] === "quiz" && !st.quizDone) { toast("先提交小测再继续"); return; } go(st.step + 1); };
  if ($("#lDone")) $("#lDone").onclick = async () => { if (l.quiz.length && !st.quizDone) { toast("先完成小测"); return go(steps.findIndex(s => s[0] === "quiz")); } await saveLessonState(cid, { done: true }); CATS = await api("/api/categories"); toast("本课已完成"); render(); };
  const answers = { ...(st.answers || {}) };
  $$(".quiz input[type=radio]").forEach(r => r.onchange = () => { answers[+r.name.slice(1)] = +r.value; saveLessonState(cid, { answers }); });
  if ($("#lQuiz")) $("#lQuiz").onclick = async () => { if (l.quiz.some((_, i) => answers[i] === undefined)) { $("#lQuizMsg").textContent = "还有题没选"; return; } await saveLessonState(cid, { answers, quizDone: true, quizScore: l.quiz.filter((q, i) => answers[i] === q.a).length }); render(); };
  if ($("#lRetry")) $("#lRetry").onclick = async () => { await saveLessonState(cid, { answers: {}, quizDone: false }); render(); };
  const askBox = async (prompt, out) => { out.innerHTML = '<div class="aibox">思考中…</div>'; let text = "";
    try { const cv = await api("/api/conversations", { body: { agent: "tutor", title: "课程提问：" + LESSON.category.name } });
      await stream(`/api/conversations/${cv.id}/send`, { text: prompt, context: "课程「" + LESSON.category.name + "」" }, ev => { if (ev.type === "delta") { text += ev.text; out.innerHTML = `<div class="aibox">${md(text)}</div>`; } if (ev.type === "error") out.innerHTML = `<div class="aibox">${esc(ev.message)}</div>`; });
    } catch (e) { out.innerHTML = `<div class="aibox">${esc(e.message)}</div>`; } };
  $("#lAskBtn").onclick = () => { const v = $("#lAsk").value.trim(); if (v) askBox(`我在学「${LESSON.category.name}」的「${steps[st.step][1]}」部分。问题：${v}`, $("#lAskOut")); };
  if ($("#lRewrite")) $("#lRewrite").onclick = () => askBox(`把下面的模板逐个改写成 ${LANG_NAME[B.goal.lang]}，保持功能和注释：\n\n${l.templates.map(t => "## " + t.t + "\n```\n" + t.code + "\n```").join("\n\n")}`, $("#lRewriteOut"));
};

/* ============ bank ============ */
let BF = { category: "", tier: "", type: "", status: "", q: "" };
V.bank = async () => {
  const qs = await api("/api/questions?" + new URLSearchParams(Object.fromEntries(Object.entries(BF).filter(([, v]) => v))));
  const confirmed = qs.filter(q => q.cls_by !== "default").length;
  const groups = CATS.filter(c => qs.some(q => q.category_id === c.id));
  const orphan = qs.filter(q => !CATS.some(c => c.id === q.category_id));
  return `<div class="row" style="justify-content:space-between;align-items:flex-end"><h1>题库 · ${esc(subject()?.name || "")}</h1><div class="row"><a class="btn" href="#newq">手动录题</a><a class="btn" href="#import">导入题目</a><a class="btn" href="#classify">AI 分类分层</a></div></div>
  <p class="lead">按模块分组，每个模块内从 L1 入门到 L4 挑战。${qs.length} 道题中 ${confirmed} 道的分层由 AI 或人工确认过。</p>
  <div class="row" style="margin-bottom:14px">
    <select id="fCat" aria-label="模块"><option value="">全部模块</option>${CATS.filter(c => !c.lesson_only).map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>
    <select id="fTier" aria-label="层级"><option value="">全部层级</option>${[1, 2, 3, 4].map(t => `<option value="${t}">L${t} ${B.tiers[t].name}</option>`).join("")}</select>
    <select id="fType" aria-label="题型"><option value="">全部题型</option>${Object.entries(B.types).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
    <select id="fSt" aria-label="状态"><option value="">全部状态</option>${Object.entries(STATUS_NAME).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}<option value="favorite">已收藏</option><option value="skipped">已跳过</option></select>
    <input type="text" id="fQ" placeholder="搜索题名或知识点" value="${esc(BF.q)}" style="min-width:200px"><span class="muted small">${qs.length} 题</span></div>
  ${groups.map(c => { const cq = qs.filter(q => q.category_id === c.id);
    return `<div class="topic-block"><div class="row" style="justify-content:space-between"><h2 style="margin:0">${esc(c.name)}</h2>${c.lesson ? `<a class="btn sm ${c.lesson_done ? "" : "pri"}" href="#lesson-${c.id}">${c.lesson_done ? "复习课程" : "先学课程（约 " + c.lesson.minutes + " 分钟）"}</a>` : `<a class="btn sm" href="#lesson-${c.id}">生成课程</a>`}</div>
    ${[1, 2, 3, 4].filter(n => cq.some(q => q.tier === n)).map(n => `<div class="tier-h">${tierChip(n)}<span class="small muted">${esc(B.tiers[n].desc)}</span></div><div class="panel qlist" style="padding:4px 14px">${cq.filter(q => q.tier === n).map(q => qRow(q)).join("")}</div>`).join("")}</div>`; }).join("")}
  ${orphan.length ? `<div class="topic-block"><h2>未分类</h2><div class="panel qlist">${orphan.map(q => qRow(q)).join("")}</div></div>` : ""}
  ${!qs.length ? '<div class="empty">没有符合条件的题。换个筛选，或者导入题目。</div>' : ""}`;
};
V.bank.after = () => {
  $("#fCat").value = BF.category; $("#fTier").value = BF.tier; $("#fType").value = BF.type; $("#fSt").value = BF.status;
  [["fCat", "category"], ["fTier", "tier"], ["fType", "type"], ["fSt", "status"]].forEach(([id, k]) => $("#" + id).onchange = e => { BF[k] = e.target.value; render(); });
  $("#fQ").oninput = e => { BF.q = e.target.value; clearTimeout(V.bank._t); V.bank._t = setTimeout(async () => { await render(); const el = $("#fQ"); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }, 350); };
};

/* ============ question ============ */
let QD = null;
V.q = async (id) => {
  QD = await api("/api/questions/" + id); const q = QD.question, p = QD.progress;
  const cat = CATS.find(c => c.id === q.category_id);
  const runnable = q.type === "code" && (q.extra.examples || []).some(e => e.runnable);
  let answerArea = "";
  if (["single", "multi"].includes(q.type)) answerArea = q.options.map((o, i) => `<label class="opt-row" data-opt="${i}"><input type="${q.type === "single" ? "radio" : "checkbox"}" name="opt" value="${i}"><span class="lt">${"ABCDEFGH"[i]}</span><span>${esc(o)}</span></label>`).join("") + (q.type === "multi" ? '<div class="small muted">多选题全对才得分，漏选或错选不得分。</div>' : "");
  if (q.type === "judge") answerArea = [["true", "正确"], ["false", "错误"]].map(([v, t]) => `<label class="opt-row" data-opt="${v}"><input type="radio" name="opt" value="${v}"><span>${t}</span></label>`).join("");
  if (q.type === "fill") { const n = q.extra.blanks || Math.max(1, (q.stem.match(/_{2,}|（\s*）|\(\s*\)/g) || []).length); answerArea = [...Array(n)].map((_, i) => `<div style="margin:6px 0">第 ${i + 1} 空：<input class="blank" data-blank="${i}" type="text"></div>`).join("") + `<div class="small muted">${q.extra.fill_rules?.case_sensitive ? "区分大小写" : "不区分大小写"}，忽略空格。</div>`; }
  if (q.type === "short") answerArea = `<textarea id="shortAns" rows="7" style="width:100%" placeholder="写下你的答案，提交后由 AI 按评分要点打分（结果标注为 AI 辅助评分）"></textarea>`;
  if (q.type === "external") answerArea = `<p><a class="btn pri" href="${esc(q.extra.url)}" target="_blank" rel="noopener">在原网站作答</a> <a class="btn" href="${esc(q.extra.url)}solutions/" target="_blank" rel="noopener">看题解</a></p><p class="small muted">做完回来点「已完成」；没把握就点「需复习」。</p>`;
  const langs = Object.keys(LANG_NAME);
  const codeArea = q.type === "code" ? `<div class="panel"><div class="row" style="justify-content:space-between;margin-bottom:8px">
      <select id="qLang">${langs.map(k => `<option value="${k}" ${k === B.goal.lang ? "selected" : ""}>${LANG_NAME[k]}${B.languages[k] === false ? "（本机未安装）" : B.languages[k] ? "" : "（AI 检查）"}</option>`).join("")}</select>
      <div class="row">${runnable ? `<button class="btn" id="run">运行样例</button><button class="btn pri" id="submit">提交（样例 + ${q.extra.hidden_count} 个隐藏用例）</button>` : ""}<button class="btn" id="resetCode">重置代码</button></div></div>
      <textarea class="editor" id="code" spellcheck="false"></textarea><div class="res" id="res"></div></div>` : "";
  const desc = q.type === "code" ? `<div class="desc">${esc(q.stem)}</div>${(q.extra.examples || []).map((e, i) => `<div class="ex"><b>示例 ${i + 1}</b>${e.doubt ? ' <span class="chip hard">原文存疑，不计分</span>' : ""}<br>输入：<code>${esc(e.input)}</code><br>输出：<code>${esc(e.output)}</code>${e.note ? `<br><span class="muted">说明：${esc(e.note)}</span>` : ""}${e.doubt ? `<br><span class="muted">${esc(e.doubt)}</span>` : ""}</div>`).join("")}` : `<div class="desc">${md(q.stem)}</div>`;
  const att = QD.attempts;
  return `<div class="row" style="justify-content:space-between;margin-bottom:6px"><a href="#bank" class="small">返回题库</a><span class="small muted">${esc(q.source)}${q.source_ref ? "（" + esc(q.source_ref) + "）" : ""}　模块：${esc(cat?.name || "未分类")}　题型：${esc(B.types[q.type])}　本题用时：${fmtMin(p.time_ms)}</span></div>
  <h1>${esc(q.title)} ${tierChip(q.tier)}</h1>
  <div class="row small" style="margin:6px 0 16px">${(q.points || []).map(t => `<span class="chip">${esc(t)}</span>`).join("")}
    ${QD.review && !QD.review.done ? `<span class="chip s2">复习第 ${QD.review.stage + 1} 轮 · ${QD.review.due <= todayStr() ? "今天到期" : "下次 " + QD.review.due.slice(5)}</span>` : ""}
    <span style="margin-left:auto" class="row"><span class="muted">状态：</span>${Object.entries(STATUS_NAME).filter(([k]) => k !== "todo").map(([k, v]) => `<button class="btn sm ${p.status === k ? "dark" : ""}" data-set="${k}">${v}</button>`).join("")}
    <button class="btn sm" id="fav">${p.favorite ? "取消收藏" : "收藏"}</button>${QD.skipped ? '<button class="btn sm" id="unskip">恢复到计划</button>' : ""}</span></div>
  ${!QD.lesson_done && cat && cat.lesson ? `<div class="notice" style="margin-bottom:14px">这道题属于「${esc(cat.name)}」，你还没学这一课。建议先学习（约 ${cat.lesson.minutes} 分钟）。<a class="btn sm" href="#lesson-${cat.id}" style="margin-left:8px">去学习</a></div>` : ""}
  <div class="pwrap">
    <div class="panel">${desc}
      ${q.type !== "code" ? `<div style="margin-top:12px" id="answerArea">${answerArea}</div>${!["external"].includes(q.type) ? `<div class="row" style="margin-top:12px"><button class="btn pri" id="submit">提交</button></div><div id="res" class="res"></div>` : ""}` : ""}
      ${q.type === "code" && q.extra.has_ref ? `<h3>参考解</h3><div id="refBox">${q.extra.ref ? `<pre class="refcode"><code>${esc(q.extra.ref)}</code></pre>` : `<button class="btn sm" id="showRef">查看参考解</button> <span class="small muted">看过后本题记为“辅助完成”</span>`}</div>` : ""}
      ${q.type !== "code" && q.type !== "external" ? `<div id="ansBox">${q.answer !== undefined ? answerHtml(q) : `<button class="btn sm" id="showAns">直接看答案</button> <span class="small muted">看过答案后，本题之后的作答不计入独立正确率</span>`}</div>` : ""}
      <h3>分类与层级</h3><div class="row small"><select id="qCat">${CATS.filter(c => !c.lesson_only).map(c => `<option value="${c.id}" ${c.id === q.category_id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
        <select id="qTier">${[1, 2, 3, 4].map(n => `<option value="${n}" ${n === q.tier ? "selected" : ""}>L${n} ${B.tiers[n].name}</option>`).join("")}</select></div>
      <div class="small muted" style="margin-top:4px">${q.cls_by === "default" ? "暂按原难度分层，还没确认。" : q.cls_by === "user" ? "人工设置的分类。" : "AI 分类" + (q.cls_reason ? "：" + esc(q.cls_reason) : "")}</div>
      <h3>错因标签</h3><div class="row small">${["概念不清", "思路不会", "审题错误", "边界遗漏", "计算/粗心", "超时", "记忆不牢"].map(t => `<label class="row" style="gap:4px"><input type="checkbox" data-tag="${t}" ${p.tags.includes(t) ? "checked" : ""}>${t}</label>`).join("")}</div>
      <h3>我的笔记</h3><textarea id="note" rows="3" style="width:100%" placeholder="思路、易错点……">${esc(p.note)}</textarea>
      ${att.length ? `<h3>作答记录</h3><table class="t small"><tr><th>时间</th><th>方式</th><th>得分</th><th>独立完成</th></tr>${att.map(a => `<tr><td>${a.day}</td><td>${a.mode === "exam" ? "测试" : "练习"}</td><td>${Math.round(a.score / (a.max_score || 1) * 100)}%${a.detail.passed !== undefined ? `（${a.detail.passed}/${a.detail.total}）` : ""}${a.detail.ai ? " · AI 评分" : ""}</td><td>${a.independent ? "是" : "否"}</td></tr>`).join("")}</table>` : ""}
      <h3>题目有问题？</h3><div class="row small"><select id="fbKind"><option>答案错误</option><option>解析不清</option><option>题意不完整</option><option>其它</option></select><input type="text" id="fbText" placeholder="说明（可选）" style="flex:1"><button class="btn sm" id="fbSend">反馈</button></div>
    </div>
    <div>${codeArea}
      <div class="panel" style="margin-top:${q.type === "code" ? 14 : 0}px"><b>AI 辅导</b>
        <div class="row" style="margin-top:8px">${[["hint", "给我提示"], ["explain", "完整解析"], ["review", "检查我的作答"], ["knowledge", "讲讲知识点"], ["similar", "出一道相似题"]].concat(q.type === "code" ? [["edge", "补充边界用例"]] : []).map(([k, v]) => `<button class="btn sm" data-ai="${k}">${v}</button>`).join("")}
        <button class="btn sm" id="stopAi" hidden>停止</button></div>
        <div class="small muted" style="margin-top:4px">用过提示、解析、检查后，本题之后的满分记为“辅助完成”。</div><div id="aiOut"></div></div>
    </div></div>`;
};
function answerHtml(q) {
  let a = "";
  if (q.type === "single") a = "ABCDEFGH"[q.answer] + ". " + (q.options[q.answer] || "");
  else if (q.type === "multi") a = (q.answer || []).map(i => "ABCDEFGH"[i]).join("、");
  else if (q.type === "judge") a = q.answer ? "正确" : "错误";
  else if (q.type === "fill") a = (q.answer || []).map((b, i) => `第 ${i + 1} 空：${(Array.isArray(b) ? b : [b]).join(" 或 ")}`).join("；");
  else a = q.answer || "";
  return `<div class="aibox"><b>答案：</b>${esc(a)}${q.analysis ? `<div style="margin-top:6px"><b>解析：</b>${md(q.analysis)}</div>` : ""}</div>`;
}
let qAbort = null;
V.q.after = (id) => {
  const q = QD.question, p = QD.progress;
  const prog = async (patch) => { try { await api(`/api/questions/${id}/progress`, { body: patch }); } catch (e) { toast(e.message); } };
  $$("[data-set]").forEach(b => b.onclick = async () => { await prog({ status: b.dataset.set }); toast(b.dataset.set === "review" ? "已加入错题复习" : "已标记"); render(); });
  $("#fav").onclick = async () => { await prog({ favorite: p.favorite ? 0 : 1 }); render(); };
  if ($("#unskip")) $("#unskip").onclick = async () => { await api("/api/skip/" + id, { method: "DELETE" }); render(); };
  $$("[data-tag]").forEach(c => c.onchange = () => prog({ tags: $$("[data-tag]").filter(x => x.checked).map(x => x.dataset.tag) }));
  let nt; $("#note").oninput = e => { clearTimeout(nt); nt = setTimeout(() => prog({ note: e.target.value }), 600); };
  const setCls = async patch => { try { await api(`/api/questions/${id}/cls`, { method: "PUT", body: { category_id: +$("#qCat").value, tier: +$("#qTier").value, by: "user", ...patch } }); toast("已更新分类"); render(); } catch (e) { toast(e.message); } };
  $("#qCat").onchange = () => setCls({}); $("#qTier").onchange = () => setCls({});
  $("#fbSend").onclick = async () => { await api(`/api/questions/${id}/feedback`, { body: { kind: $("#fbKind").value, text: $("#fbText").value } }); toast("已记录反馈"); $("#fbText").value = ""; };
  if ($("#showAns")) twoStep($("#showAns"), "确认查看（之后不计独立）", async () => { const r = await api(`/api/questions/${id}/reveal`, { body: {} }); $("#ansBox").innerHTML = answerHtml(r); });
  if ($("#showRef")) twoStep($("#showRef"), "确认查看（记为辅助完成）", async () => { const r = await api(`/api/questions/${id}/reveal`, { body: {} }); $("#refBox").innerHTML = `<pre class="refcode"><code>${esc(r.extra.ref)}</code></pre>`; });
  /* code */
  if (q.type === "code") {
    const ed = $("#code"); const lang = () => $("#qLang").value;
    const starter = () => { const ex = (q.extra.examples || [])[0]; const ps = q.extra.params || ["a", "b"]; return lang() === "javascript" ? `// 实现 solve 并 return 结果\n// 示例调用：solve(${ex ? ex.input : ""})\nfunction solve(${ps.join(", ")}) {\n  \n}\n` : lang() === "python" ? `# 实现 solve 并 return 结果\n# 示例调用：solve(${ex ? ex.input : ""})\ndef solve(${ps.join(", ")}):\n    pass\n` : `// 在这里写 ${LANG_NAME[lang()]} 代码，点「检查我的作答」让 AI 检查\n`; };
    ed.value = p.code[lang()] ?? starter();
    let ct; ed.oninput = () => { clearTimeout(ct); ct = setTimeout(() => { p.code[lang()] = ed.value; prog({ code: p.code }); }, 800); };
    ed.onkeydown = e => { if (e.key === "Tab") { e.preventDefault(); ed.setRangeText("    ", ed.selectionStart, ed.selectionEnd, "end"); ed.oninput(); } };
    $("#qLang").onchange = () => { ed.value = p.code[lang()] ?? starter(); };
    twoStep($("#resetCode"), "确认清空代码", () => { ed.value = starter(); ed.oninput(); });
    const res = $("#res");
    const canRun = () => B.languages[lang()];
    if ($("#run")) $("#run").onclick = async () => { if (!canRun()) { res.innerHTML = `<div class="case bad">${LANG_NAME[lang()]} 不能在本机运行，可用「检查我的作答」。</div>`; return; } res.innerHTML = '<div class="muted">运行中…</div>';
      try { const r = await api(`/api/questions/${id}/run`, { body: { lang: lang(), code: ed.value } }); if (r.error) { res.innerHTML = `<div class="case bad">${esc(r.error)}</div>`; return; }
        res.innerHTML = r.results.map((c, i) => `<div class="case ${c.pass ? "ok" : "bad"}">样例 ${i + 1} ${{ AC: "通过", WA: "答案错误", RE: "运行错误", TLE: "超时", SKIP: "未运行" }[c.kind]}${c.ms !== undefined ? ` · ${(+c.ms).toFixed(1)} ms` : ""}\n输入：${esc(c.input)}\n期望：${esc(c.output)}\n实际：${esc(c.err || c.got || "—")}</div>`).join(""); } catch (e) { res.innerHTML = `<div class="case bad">${esc(e.message)}</div>`; } };
    if ($("#submit")) $("#submit").onclick = async () => { const sb = $("#submit"); if (sb.disabled) return; if (!canRun()) { res.innerHTML = `<div class="case bad">${LANG_NAME[lang()]} 不能在本机运行判题。</div>`; return; } sb.disabled = true; res.innerHTML = '<div class="muted">判题中…</div>';
      try { const r = await api(`/api/questions/${id}/submit`, { body: { lang: lang(), code: ed.value, idem: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) } });
        if (r.error_run) { res.innerHTML = `<div class="case bad">${esc(r.error_run)}</div>`; return; }
        const d = r.detail; res.innerHTML = `<div class="case ${r.full ? "ok" : "bad"}"><b>${d.passed}/${d.total}</b> 个用例通过（含 ${d.hidden} 个隐藏用例），按通过率约得 <b>${Math.round(r.ratio * 100)}%</b>。${r.full ? (r.independent ? "独立通过！" : "通过（辅助）。") : "未通过：" + esc(d.kinds) + "。已加入错题复习。"}${r.review && !r.review.done && r.review.due ? " 下次复习：" + r.review.due : ""}</div>` +
          (d.first_fail ? `<div class="case bad">第一个没通过的用例（练习时显示，正式考试看不到）：\n输入：${esc(d.first_fail.input)}\n期望：${esc(d.first_fail.expect)}\n实际：${esc(d.first_fail.got)}</div>` : "");
      } catch (e) { res.innerHTML = `<div class="case bad">${esc(e.message)}</div>`; } finally { sb.disabled = false; } };
  } else if ($("#submit")) {
    $$(".opt-row").forEach(r => r.onclick = () => { });
    $("#submit").onclick = async () => {
      const sb = $("#submit"); if (sb.disabled) return; let answer;
      if (q.type === "single") { const c = $("input[name=opt]:checked"); if (!c) return toast("先选一个选项"); answer = +c.value; }
      if (q.type === "multi") { answer = $$("input[name=opt]:checked").map(c => +c.value); if (!answer.length) return toast("至少选一个选项"); }
      if (q.type === "judge") { const c = $("input[name=opt]:checked"); if (!c) return toast("先选择正确或错误"); answer = c.value === "true"; }
      if (q.type === "fill") answer = $$("[data-blank]").map(x => x.value);
      if (q.type === "short") { answer = $("#shortAns").value.trim(); if (!answer) return toast("先写答案"); }
      sb.disabled = true; $("#res").innerHTML = '<div class="muted">评分中…</div>';
      try { const r = await api(`/api/questions/${id}/submit`, { body: { answer, idem: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) } });
        if (r.pending) { $("#res").innerHTML = `<div class="case bad">${esc(r.message)}</div>`; return; }
        if (["single", "multi", "judge"].includes(q.type)) { const corr = q.type === "multi" ? r.answer : [q.type === "judge" ? String(r.answer) : r.answer]; $$(".opt-row").forEach(row => { const v = row.dataset.opt; const isC = corr.map(String).includes(v); const sel = row.querySelector("input").checked; row.classList.toggle("right", isC); row.classList.toggle("wrong", sel && !isC); }); }
        $("#res").innerHTML = `<div class="case ${r.full ? "ok" : "bad"}">${r.full ? "回答正确" + (r.independent ? "（独立完成）" : "（辅助完成）") : "得分 " + Math.round(r.ratio * 100) + "%。已加入错题复习。"}${r.detail.ai ? "\nAI 辅助评分：" + esc(r.detail.reason) + (r.detail.misses?.length ? "\n缺少：" + esc(r.detail.misses.join("、")) : "") : ""}${r.review && !r.review.done && r.review.due ? "\n下次复习：" + r.review.due : ""}</div>`;
        if (r.answer !== undefined) $("#ansBox").innerHTML = answerHtml({ ...q, answer: r.answer, analysis: r.analysis });
      } catch (e) { $("#res").innerHTML = `<div class="case bad">${esc(e.message)}</div>`; } finally { sb.disabled = false; }
    };
  }
  /* AI helper */
  $$("[data-ai]").forEach(b => b.onclick = async () => {
    const out = $("#aiOut"); out.innerHTML = '<div class="aibox">思考中…</div>'; let text = "";
    const ansNow = q.type === "code" ? $("#code").value : q.type === "short" ? ($("#shortAns")?.value || "") : q.type === "fill" ? $$("[data-blank]").map(x => x.value).join(" | ") : $$("input[name=opt]:checked").map(c => c.value).join(",");
    qAbort = new AbortController(); $("#stopAi").hidden = false;
    try { await stream(`/api/questions/${id}/ai`, { kind: b.dataset.ai, answer: ansNow }, ev => { if (ev.type === "delta") { text += ev.text; out.innerHTML = `<div class="aibox"><div class="small muted">AI 生成，可能有错</div>${md(text)}</div>`; } if (ev.type === "error") out.innerHTML = `<div class="aibox">${esc(ev.message)}</div>`; if (ev.type === "done" && ev.model) out.insertAdjacentHTML("beforeend", `<div class="small muted">模型：${esc(ev.model)}</div>`); }, qAbort.signal); }
    catch (e) { if (e.name !== "AbortError") out.innerHTML = `<div class="aibox">${esc(e.message)}</div>`; else out.insertAdjacentHTML("beforeend", '<div class="small muted">已停止</div>'); }
    finally { $("#stopAi").hidden = true; }
  });
  $("#stopAi").onclick = () => qAbort && qAbort.abort();
};

/* ============ manual question ============ */
V.newq = async () => `<a href="#bank" class="small">返回题库</a><h1>手动录题</h1>
  <div class="panel"><div class="row" style="gap:14px;align-items:flex-end">
    <label class="f">题型<select id="nType">${Object.entries(B.types).filter(([k]) => k !== "external").map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
    <label class="f">模块<select id="nCat">${CATS.filter(c => !c.lesson_only).map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></label>
    <label class="f">层级<select id="nTier">${[1, 2, 3, 4].map(n => `<option value="${n}" ${n === 2 ? "selected" : ""}>L${n} ${B.tiers[n].name}</option>`).join("")}</select></label></div>
    <label class="f" style="margin-top:10px">题名<input type="text" id="nTitle"></label>
    <label class="f" style="margin-top:10px">题干（填空题用 ____ 表示空）<textarea id="nStem" rows="5"></textarea></label>
    <label class="f" style="margin-top:10px">选项（单选/多选，每行一个）<textarea id="nOpts" rows="4"></textarea></label>
    <label class="f" style="margin-top:10px">答案（单选写 A；多选写 A,C；判断写 对/错；填空每空一行，可接受答案用 | 分隔；简答写评分要点；编程题见下）<textarea id="nAns" rows="3"></textarea></label>
    <label class="f" style="margin-top:10px">编程题示例（每行：输入字面量 =&gt; 期望输出，例如 [1,2],3 =&gt; 4）<textarea id="nEx" rows="3"></textarea></label>
    <label class="f" style="margin-top:10px">解析<textarea id="nAna" rows="3"></textarea></label>
    <div class="row" style="margin-top:12px"><button class="btn pri" id="nSave">保存到我的题库</button><span id="nMsg" class="small"></span></div></div>`;
V.newq.after = () => {
  $("#nSave").onclick = async () => {
    const t = $("#nType").value; const opts = $("#nOpts").value.split("\n").map(s => s.trim()).filter(Boolean); const a = $("#nAns").value.trim();
    const item = { type: t, title: $("#nTitle").value.trim(), stem: $("#nStem").value.trim(), options: opts, analysis: $("#nAna").value, category_id: +$("#nCat").value, tier: +$("#nTier").value };
    if (t === "single") item.answer = a; if (t === "multi") item.answer = a.split(/[,，\s]+/).filter(Boolean); if (t === "judge") item.answer = a;
    if (t === "fill") item.answer = a.split("\n").filter(Boolean).map(l => l.split("|").map(s => s.trim()));
    if (t === "short") item.rubric = a;
    if (t === "code") item.examples = $("#nEx").value.split("\n").filter(l => l.includes("=>")).map(l => { const [i, o] = l.split("=>"); return { input: i.trim(), output: o.trim() }; });
    try { const r = await api("/api/questions", { body: item }); toast("已保存"); location.hash = "#q-" + r.id; } catch (e) { $("#nMsg").textContent = e.message; }
  };
};

/* ============ review ============ */
V.review = async () => {
  const R = await api("/api/reviews"); const t = todayStr();
  return `<h1>错题复习</h1><p class="lead">答错、没拿满分或标了「需复习」的题，按 ${R.intervals.join("、")} 天的间隔安排复习（在学习计划里可改）。到期当天重做并满分进入下一轮，没满分从第一轮重来。</p>
  ${R.items.length ? `<div class="panel tscroll"><table class="t"><tr><th>题目</th><th>轮次</th><th>下次复习</th><th>错因</th><th>历次复习（✓ 通过 ✗ 未通过）</th><th></th></tr>
  ${R.items.map(r => `<tr><td><a href="#q-${esc(r.question_id)}">${esc(r.title)}</a> ${tierChip(r.tier)}</td><td>${r.stage + 1}/${R.intervals.length}</td><td style="color:${r.due <= t ? "var(--red)" : "inherit"}">${r.due <= t ? "今天到期" : r.due}</td><td class="small">${esc(r.tags.join("、")) || '<span class="muted">未标注</span>'}</td><td class="small">${r.history.map(h => h.ok ? "✓" : "✗").join(" ") || "—"}</td><td><button class="btn sm" data-rm="${esc(r.question_id)}">移出错题本</button></td></tr>`).join("")}</table></div>`
    : '<div class="panel empty">错题本是空的。</div>'}${R.done_count ? `<p class="small muted">已完成全部轮次：${R.done_count} 道。</p>` : ""}`;
};
V.review.after = () => { $$("[data-rm]").forEach(b => twoStep(b, "确认移出", async () => { await api("/api/reviews/" + b.dataset.rm, { method: "DELETE" }); render(); })); };

/* ============ exams ============ */
let EO = { type: "weekly", scope: "learned", minutes: "", allow_recent: false, sched: null, src: "bank" };
V.exams = async () => {
  const E = await api("/api/exams"); const prof = E.profile;
  const live = E.exams.find(e => e.status === "running" || e.status === "ready");
  const hist = E.exams.filter(e => e.status === "done");
  return `<h1>测试</h1><p class="lead">按「${esc(prof.name || "测试")}」的结构出卷：${(prof.sections || []).map(s => `${esc(s.name)} ${s.count} 题 × ${s.points} 分`).join("，")}，限时 ${prof.duration} 分钟。计时从点「开始」算起，离开页面不暂停；测试中智能体关闭；交卷后统一显示答案。</p>
  ${live ? `<div class="notice" style="margin-bottom:14px">有一场测试${live.status === "running" ? "正在进行" : "已组好卷待开始"}。<a class="btn sm pri" href="#exam-${live.id}" style="margin-left:8px">${live.status === "running" ? "继续作答" : "去开始"}</a></div>` : ""}
  ${E.pending.length ? `<div class="panel" style="margin-bottom:16px"><h3 style="margin-top:0">计划里到期的测试（错过的会保留）</h3>${E.pending.map(e => `<div class="row" style="justify-content:space-between;border-bottom:1px solid var(--rule2);padding:6px 0"><span>${e.date} 周${WD[dow(e.date)]} · ${e.type === "monthly" ? "月测（全部模块）" : "周测（已学模块）"}</span><span class="row"><button class="btn sm pri" data-ps="${e.date}" data-pt="${e.type}">准备这场</button><button class="btn sm" data-pk="${e.date}">跳过</button></span></div>`).join("")}</div>` : ""}
  <div class="grid2"><div class="panel"><h3 style="margin-top:0">${EO.sched ? `组卷：${EO.sched} 的${EO.type === "monthly" ? "月测" : "周测"}` : "新建测试"}</h3>
    <div class="row" style="margin:10px 0">
      <label class="f">类型<select id="eType"><option value="weekly">周测</option><option value="monthly">月测</option><option value="custom">自定义</option></select></label>
      <label class="f">范围<select id="eScope"><option value="learned">已学模块</option><option value="all">全部模块</option><option value="weak">薄弱题</option></select></label>
      <label class="f">题目来源<select id="eSrc"><option value="bank">题库抽题</option><option value="ai">AI 出新题</option></select></label>
      <label class="f">时长（分钟）<input type="number" id="eMin" value="${EO.minutes || prof.duration || 60}" min="10" max="300" style="width:80px"></label></div>
    <label class="row small"><input type="checkbox" id="eRecent" ${EO.allow_recent ? "checked" : ""}>允许抽到近期测过的题</label>
    <div class="row" style="margin-top:12px"><button class="btn pri" id="eCreate">组卷</button></div><div id="eGap"></div>
    <p class="small muted">「AI 出新题」更接近不考原题的真实考试，但答案未经核验、编程题只有样例，成绩仅供参考。</p></div>
    <div class="panel"><h3 style="margin-top:0">成绩走势</h3>${chart(hist.slice(0, 12).reverse(), prof)}</div></div>
  <h2>历史记录</h2>${hist.length ? `<div class="panel tscroll"><table class="t"><tr><th>日期</th><th>类型</th><th>各题得分</th><th>总分</th><th>用时</th></tr>${hist.map(e => `<tr><td><a href="#exam-${e.id}">${new Date(e.created_at * 1000).toLocaleDateString()}</a></td><td>${e.type === "monthly" ? "月测" : e.type === "weekly" ? "周测" : "自定义"}${e.source === "ai" ? "（AI 题）" : ""}</td><td class="small">${e.items.map(i => `${esc(i.title)}：${i.score ?? "—"}/${i.points}${i.kind ? ` <span class="muted">${esc(i.kind)}</span>` : ""}`).join("<br>")}</td><td class="scorecell" style="color:${e.excellent && e.total >= e.excellent ? "var(--teal)" : e.pass && e.total >= e.pass ? "var(--ink)" : "var(--red)"}">${e.total}/${e.max}</td><td>${e.used_min} 分钟</td></tr>`).join("")}</table></div>` : '<div class="panel muted small">还没有测试记录。</div>'}`;
};
function chart(list, prof) {
  if (!list.length) return '<div class="muted small">完成第一次测试后这里显示分数变化。不同试卷难度不同，走势仅供参考。</div>';
  const W = 460, H = 170, pad = 28, max = list[0].max || 100; const x = i => pad + (list.length === 1 ? (W - 2 * pad) / 2 : i * (W - 2 * pad) / (list.length - 1)); const y = v => H - pad - (v / max) * (H - 2 * pad);
  const line = (v, c, t) => v ? `<line x1="${pad}" x2="${W - pad}" y1="${y(v)}" y2="${y(v)}" stroke="${c}" stroke-dasharray="4 4"/><text x="${W - pad}" y="${y(v) - 4}" font-size="11" text-anchor="end" fill="${c}">${v} ${t}</text>` : "";
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="测试分数走势">${line(prof.pass, "#C98A0B", "通过")}${line(prof.excellent, "#12936F", "优秀")}<polyline fill="none" stroke="#1C2430" stroke-width="2" points="${list.map((e, i) => x(i) + "," + y(e.total)).join(" ")}"/>${list.map((e, i) => `<circle cx="${x(i)}" cy="${y(e.total)}" r="4" fill="#1C2430"><title>${e.total} 分</title></circle>`).join("")}</svg><div class="small muted">不同试卷难度不同，走势仅供参考。</div>`;
}
V.exams.after = () => {
  $("#eType").value = EO.type; $("#eScope").value = EO.scope; $("#eSrc").value = EO.src;
  $("#eType").onchange = e => { EO.type = e.target.value; if (EO.type === "monthly") $("#eScope").value = "all"; };
  $$("[data-ps]").forEach(b => b.onclick = () => { EO.sched = b.dataset.ps; EO.type = b.dataset.pt; EO.scope = EO.type === "monthly" ? "all" : "learned"; render(); });
  $$("[data-pk]").forEach(b => twoStep(b, "确认跳过", async () => { await api("/api/exams/skip", { body: { date: b.dataset.pk } }); render(); }));
  $("#eCreate").onclick = async () => {
    Object.assign(EO, { type: $("#eType").value, scope: $("#eScope").value, src: $("#eSrc").value, minutes: +$("#eMin").value, allow_recent: $("#eRecent").checked });
    const btn = $("#eCreate"); btn.disabled = true; btn.textContent = EO.src === "ai" ? "AI 出题中（约 30–90 秒）…" : "组卷中…";
    try { const r = await api(EO.src === "ai" ? "/api/exams/ai" : "/api/exams", { body: { type: EO.type, scope: EO.scope, allow_recent: EO.allow_recent, sched_date: EO.sched, minutes: EO.minutes } });
      if (r.gaps) { $("#eGap").innerHTML = `<div class="notice" style="margin-top:10px"><b>题量不够，没有组卷。</b>${r.gaps.map(g => `<div>${esc(g.section)}：需要 ${g.need} 道（${g.types.join("/")}，${g.tiers.join("/")}），当前范围只有 ${g.have} 道</div>`).join("")}${r.excluded_recent ? `<div>已排除近期测过的 ${r.excluded_recent} 道。</div>` : ""}<div>可以扩大范围、允许近期题、改用 AI 出新题，或去导入更多题。</div></div>`; return; }
      EO.sched = null; location.hash = "#exam-" + r.id;
    } catch (e) { $("#eGap").innerHTML = `<div class="notice" style="margin-top:10px">${esc(e.message)}</div>`; } finally { btn.disabled = false; btn.textContent = "组卷"; }
  };
};

/* ---- single exam: ready / running / report ---- */
let EX = null, exCur = 0, exTimer = null, exSaveT = null, exDirty = {};
V.exam = async (id) => {
  EX = await api("/api/exams/" + id); clearInterval(exTimer);
  const P = EX.paper;
  if (EX.status === "ready") return `<a href="#exams" class="small">返回测试</a><h1>${esc(P.name)} · ${EX.type === "monthly" ? "月测" : EX.type === "weekly" ? "周测" : "自定义"}</h1>
    <div class="panel"><div class="kv"><b>题目</b><span>${P.items.length} 题，满分 ${P.total}</span><b>时长</b><span>${P.duration} 分钟（点开始后计时，离开页面不暂停）</span>${P.pass ? `<b>通过线</b><span>${P.pass}${P.excellent ? "，优秀 " + P.excellent : ""}</span>` : ""}<b>来源</b><span>${P.source === "ai" ? "AI 出题（未核验）" : "题库抽题"}</span></div>
    <div class="row" style="margin-top:14px"><button class="btn pri" id="exStart">开始测试</button><button class="btn" id="exDrop">放弃这套卷</button></div></div>`;
  if (EX.status === "done" || EX.status === "grading") return examReport();
  exCur = Math.min(exCur, P.items.length - 1);
  const it = P.items[exCur]; const ans = EX.answers[it.qid];
  let area = "";
  if (["single", "multi"].includes(it.type)) area = it.options.map((o, i) => `<label class="opt-row"><input type="${it.type === "single" ? "radio" : "checkbox"}" name="eo" value="${i}" ${it.type === "single" ? (ans === i ? "checked" : "") : ((ans || []).includes(i) ? "checked" : "")}><span class="lt">${"ABCDEFGH"[i]}</span><span>${esc(o)}</span></label>`).join("");
  if (it.type === "judge") area = [[true, "正确"], [false, "错误"]].map(([v, t]) => `<label class="opt-row"><input type="radio" name="eo" value="${v}" ${ans === v ? "checked" : ""}><span>${t}</span></label>`).join("");
  if (it.type === "fill") { const n = it.extra.blanks || Math.max(1, (it.stem.match(/_{2,}|（\s*）|\(\s*\)/g) || []).length); area = [...Array(n)].map((_, i) => `<div style="margin:6px 0">第 ${i + 1} 空：<input class="blank" data-eb="${i}" value="${esc((ans || [])[i] || "")}"></div>`).join(""); }
  if (it.type === "short") area = `<textarea id="eShort" rows="8" style="width:100%">${esc(ans || "")}</textarea>`;
  if (it.type === "code") area = `<div class="row" style="justify-content:space-between;margin:8px 0"><span class="small muted">语言：${LANG_NAME[B.goal.lang]}</span>${B.languages[B.goal.lang] ? '<button class="btn sm" id="eRun">自测样例</button>' : ""}</div><textarea class="editor" id="eCode" spellcheck="false">${esc(ans?.code ?? `# 实现 solve 并 return 结果\ndef solve(${(it.extra.params || ["a"]).join(", ")}):\n    pass\n`)}</textarea><div class="res" id="eRes"></div>`;
  return `<div class="row" style="justify-content:space-between"><h1>测试进行中</h1><div class="timer" id="timer">--:--</div></div>
  <div class="row" style="margin:8px 0 14px"><div class="answer-card">${P.items.map((x, i) => `<button class="${i === exCur ? "on" : ""} ${EX.answers[x.qid] !== undefined && EX.answers[x.qid] !== "" ? "ans" : ""} ${EX.flags[x.qid] ? "flag" : ""}" data-ei="${i}" aria-label="第 ${i + 1} 题">${i + 1}</button>`).join("")}</div>
    <span class="saving" id="eSave">已保存</span><span style="margin-left:auto" class="row"><button class="btn pri" id="eSubmit">交卷</button><button class="btn" id="eAbort">放弃</button></span></div>
  <div class="pwrap"><div class="panel"><div class="row" style="justify-content:space-between"><b>第 ${exCur + 1} 题 · ${esc(it.section)} · ${it.points} 分 ${typeBadge(it.type)}</b><label class="row small"><input type="checkbox" id="eFlag" ${EX.flags[it.qid] ? "checked" : ""}>标记待检查</label></div>
    <h2>${esc(it.title)}</h2><div class="desc">${it.type === "code" ? esc(it.stem) : md(it.stem)}</div>${(it.extra.examples || []).map((e, i) => `<div class="ex"><b>示例 ${i + 1}</b><br>输入：<code>${esc(e.input)}</code><br>输出：<code>${esc(e.output)}</code></div>`).join("")}</div>
    <div class="panel">${area}<div class="row" style="justify-content:space-between;margin-top:12px"><button class="btn" id="ePrev" ${exCur === 0 ? "disabled" : ""}>上一题</button><button class="btn" id="eNext" ${exCur === P.items.length - 1 ? "disabled" : ""}>下一题</button></div></div></div>`;
};
function examReport() {
  const P = EX.paper, R = EX.result || { items: [] };
  return `<a href="#exams" class="small">返回测试</a><h1>测试报告</h1>
  <div class="hero"><div><div class="days">${R.total ?? "—"}<small>/ ${R.max ?? P.total}</small></div><div class="hero-cap">${R.auto ? "到时自动交卷 · " : ""}用时 ${R.used_min ?? "—"} 分钟${R.pending ? " · 有题待评分" : ""}</div></div><div>${scoreRuler(R.total, profile())}</div></div>
  <div class="panel tscroll"><table class="t"><tr><th>题目</th><th>得分</th><th>情况</th><th>答案与解析</th><th>复核</th></tr>
  ${P.items.map((it, i) => { const r = R.items[i] || {}; return `<tr><td>${i + 1}. ${esc(it.title)} ${typeBadge(it.type)}${it.qid && !it.qid.startsWith("ai-") ? ` <a class="small" href="#q-${esc(it.qid)}">重做</a>` : ""}</td><td class="scorecell" style="font-size:16px">${r.score ?? "—"}/${it.points}${r.adjusted ? '<div class="small muted">已复核</div>' : ""}</td><td class="small">${esc(r.kind || "")}${r.ai ? "<br>AI 辅助评分：" + esc(r.reason || "") : ""}</td><td class="small">${it.type === "code" ? "见题目页参考解" : esc(fmtAnswer(it))}${it.analysis ? "<div class='muted'>" + esc(it.analysis).slice(0, 200) + "</div>" : ""}</td><td><button class="btn sm" data-adj="${esc(it.qid)}" data-max="${it.points}">调整</button></td></tr>`; }).join("")}</table></div>
  ${(EX.adjustments || []).length ? `<h3>复核记录</h3>${EX.adjustments.map(a => `<div class="small">${esc(a.qid)}：${a.old} → ${a.new}，理由：${esc(a.reason)}（${new Date(a.at * 1000).toLocaleString()}）</div>`).join("")}` : ""}
  <div class="row" style="margin-top:14px"><button class="btn pri" id="exCoach">请考前教练分析这次测试</button></div><div id="exCoachOut"></div>`;
}
function fmtAnswer(it) { const a = it.answer; if (it.type === "single") return "ABCDEFGH"[a] || ""; if (it.type === "multi") return (a || []).map(i => "ABCDEFGH"[i]).join(""); if (it.type === "judge") return a ? "正确" : "错误"; if (it.type === "fill") return (a || []).map(b => (Array.isArray(b) ? b : [b]).join("/")).join("；"); return String(a || "").slice(0, 120); }
function collectExamAnswer() {
  const it = EX.paper.items[exCur]; if (!it || EX.status !== "running") return;
  let v;
  if (it.type === "single") { const c = $("input[name=eo]:checked"); v = c ? +c.value : undefined; }
  else if (it.type === "multi") v = $$("input[name=eo]:checked").map(c => +c.value);
  else if (it.type === "judge") { const c = $("input[name=eo]:checked"); v = c ? c.value === "true" : undefined; }
  else if (it.type === "fill") v = $$("[data-eb]").map(x => x.value);
  else if (it.type === "short") v = $("#eShort").value;
  else if (it.type === "code") v = { lang: B.goal.lang, code: $("#eCode").value };
  if (v !== undefined) { EX.answers[it.qid] = v; exDirty[it.qid] = v; }
}
async function flushExam() { const d = exDirty; exDirty = {}; if (!Object.keys(d).length) return; const s = $("#eSave"); if (s) s.textContent = "保存中…";
  try { await api(`/api/exams/${EX.id}/answers`, { method: "PUT", body: { answers: d, flags: EX.flags } }); if ($("#eSave")) $("#eSave").textContent = "已保存 " + new Date().toTimeString().slice(0, 8); try { localStorage.removeItem("sa_exam_" + EX.id); } catch (e) { } }
  catch (e) { Object.assign(exDirty, d); try { localStorage.setItem("sa_exam_" + EX.id, JSON.stringify(EX.answers)); } catch (_) { } if ($("#eSave")) $("#eSave").textContent = "保存失败，已暂存在本机，联网后自动重试"; } }
V.exam.after = (id) => {
  if (EX.status === "ready") { $("#exStart").onclick = async () => { await api(`/api/exams/${id}/start`, { body: {} }); render(); }; twoStep($("#exDrop"), "确认放弃", async () => { await api("/api/exams/" + id, { method: "DELETE" }); location.hash = "#exams"; }); return; }
  if (EX.status !== "running") {
    $$("[data-adj]").forEach(b => b.onclick = async () => { const tr = b.closest("tr"); if (tr.nextElementSibling?.classList.contains("adjrow")) return; tr.insertAdjacentHTML("afterend", `<tr class="adjrow"><td colspan="5"><div class="row small">新分数 <input type="number" id="adjS" min="0" max="${b.dataset.max}" style="width:80px"> 理由 <input type="text" id="adjR" style="flex:1" placeholder="例如：AI 评分漏看了第二个要点"><button class="btn sm pri" id="adjOk">保存</button></div></td></tr>`);
      $("#adjOk").onclick = async () => { try { await api(`/api/exams/${id}/adjust`, { body: { qid: b.dataset.adj, score: +$("#adjS").value, reason: $("#adjR").value } }); toast("已复核，保留原分数记录"); render(); } catch (e) { toast(e.message); } }; });
    $("#exCoach").onclick = async () => { const out = $("#exCoachOut"); let text = ""; out.innerHTML = '<div class="aibox">分析中…</div>';
      try { const cv = await api("/api/conversations", { body: { agent: "coach", title: "测试分析" } }); const R = EX.result;
        const desc = EX.paper.items.map((it, i) => `${i + 1}. ${it.title}（${B.types[it.type]}，L${it.tier}）${R.items[i].score}/${it.points}，${R.items[i].kind}`).join("\n");
        await stream(`/api/conversations/${cv.id}/send`, { text: `这是我刚做完的测试（${R.total}/${R.max}，用时 ${R.used_min} 分钟）：\n${desc}\n请分析失分原因、薄弱知识点和时间分配，给出接下来几天的针对性练习清单。` }, ev => { if (ev.type === "delta") { text += ev.text; out.innerHTML = `<div class="aibox">${md(text)}</div>`; } if (ev.type === "proposal") out.insertAdjacentHTML("beforeend", proposalHtml(ev.proposal)); if (ev.type === "error") out.innerHTML = `<div class="aibox">${esc(ev.message)}</div>`; });
        bindProposals(out); } catch (e) { out.innerHTML = `<div class="aibox">${esc(e.message)}</div>`; } };
    return;
  }
  try { const local = JSON.parse(localStorage.getItem("sa_exam_" + id) || "null"); if (local) { Object.assign(EX.answers, local); exDirty = { ...local }; flushExam(); } } catch (e) { }
  const skew = Date.now() / 1000 - EX.now;
  const tick = () => { const left = EX.deadline_at - (Date.now() / 1000 - skew); const el = $("#timer"); if (!el) { clearInterval(exTimer); return; }
    if (left <= 0) { clearInterval(exTimer); collectExamAnswer(); finishExam(true); return; }
    const m = Math.floor(left / 60), s = Math.floor(left % 60); el.textContent = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`; el.classList.toggle("warn", left < 600); };
  tick(); exTimer = setInterval(tick, 1000);
  const changed = () => { collectExamAnswer(); clearTimeout(exSaveT); $("#eSave").textContent = "未保存"; exSaveT = setTimeout(flushExam, 1500); };
  $$("#main input, #main textarea").forEach(el => { if (el.id !== "eFlag") { el.addEventListener("input", changed); el.addEventListener("change", changed); } });
  const ec = $("#eCode"); if (ec) ec.onkeydown = e => { if (e.key === "Tab") { e.preventDefault(); ec.setRangeText("    ", ec.selectionStart, ec.selectionEnd, "end"); changed(); } };
  $("#eFlag").onchange = e => { EX.flags[EX.paper.items[exCur].qid] = e.target.checked; exDirty.__f = 1; delete exDirty.__f; api(`/api/exams/${id}/answers`, { method: "PUT", body: { answers: {}, flags: EX.flags } }).catch(() => { }); render(); };
  const go = i => { collectExamAnswer(); flushExam(); exCur = i; render(); };
  $$("[data-ei]").forEach(b => b.onclick = () => go(+b.dataset.ei));
  $("#ePrev").onclick = () => go(exCur - 1); $("#eNext").onclick = () => go(exCur + 1);
  if ($("#eRun")) $("#eRun").onclick = async () => { const res = $("#eRes"); res.innerHTML = '<div class="muted">运行中…</div>'; try { const r = await api(`/api/exams/${id}/run`, { body: { qid: EX.paper.items[exCur].qid, lang: B.goal.lang, code: $("#eCode").value } }); res.innerHTML = r.error ? `<div class="case bad">${esc(r.error)}</div>` : r.results.map((c, i) => `<div class="case ${c.pass ? "ok" : "bad"}">样例 ${i + 1} ${c.pass ? "通过" : "未通过"}\n实际：${esc(c.err || c.got || "—")}</div>`).join(""); } catch (e) { res.innerHTML = `<div class="case bad">${esc(e.message)}</div>`; } };
  twoStep($("#eSubmit"), "确认交卷", () => { collectExamAnswer(); finishExam(false); });
  twoStep($("#eAbort"), "确认放弃（不记录成绩）", async () => { clearInterval(exTimer); await api("/api/exams/" + id, { method: "DELETE" }); location.hash = "#exams"; });
};
let finishing = false;
async function finishExam(auto) {
  if (finishing) return; finishing = true; clearInterval(exTimer); clearTimeout(exSaveT); exDirty = {};
  const b = $("#eSubmit"); if (b) { b.disabled = true; b.textContent = "判分中…"; }
  try { await api(`/api/exams/${EX.id}/submit`, { body: { answers: EX.answers } }); toast(auto ? "时间到，已自动交卷" : "已交卷"); exCur = 0; render(); }
  catch (e) { toast("交卷失败：" + e.message + "。答案已暂存，可重试"); if (b) { b.disabled = false; b.textContent = "交卷"; } }
  finally { finishing = false; }
}

/* ============ chat (agents) ============ */
let CHAT = { conv: null, agent: "tutor", detach: null, running: false };
let RUNNING_IDS = new Set();
function proposalHtml(p) { return `<div class="proposal" data-pid="${p.id}"><div><b>建议：</b>${esc(p.summary)}</div><div class="row"><button class="btn sm pri" data-pok="${p.id}">确认</button><button class="btn sm" data-pno="${p.id}">不用</button></div></div>`; }
function bindProposals(scope) {
  $$("[data-pok]", scope).forEach(b => b.onclick = async () => { try { await api("/api/proposals/" + b.dataset.pok, { body: { accept: true } }); b.closest(".proposal").innerHTML = '<span class="small">已确认并生效</span>'; refreshCounts(); } catch (e) { toast(e.message); } });
  $$("[data-pno]", scope).forEach(b => b.onclick = async () => { await api("/api/proposals/" + b.dataset.pno, { body: { accept: false } }); b.closest(".proposal").innerHTML = '<span class="small muted">已忽略</span>'; refreshCounts(); });
}
V.chat = async (arg) => {
  if (arg && B.agents.some(a => a.key === arg)) { CHAT.agent = arg; CHAT.conv = null; }
  if (arg && /^\d+$/.test(arg)) CHAT.conv = +arg;
  const [convs, pend, runs] = await Promise.all([api("/api/conversations"), api("/api/proposals"), api("/api/runs")]);
  RUNNING_IDS = new Set(runs.map(r => r.conv_id));
  let conv = null; if (CHAT.conv) { try { conv = await api("/api/conversations/" + CHAT.conv); CHAT.agent = conv.agent; } catch (e) { CHAT.conv = null; } }
  const ag = B.agents.find(a => a.key === CHAT.agent);
  CHAT.running = !!(conv && conv.running);
  const running = (await api("/api/exams")).exams.some(e => e.status === "running");
  return `<h1>智能体</h1><p class="lead">每个智能体只能使用分配给它的工具：读取进度、搜索题库、搜视频。要改计划、题目状态或题库时，会先给你确认按钮，确认后才生效。</p>
  ${running ? '<div class="notice" style="margin-bottom:12px">测试进行中，智能体已关闭。<a href="#exams">回到测试</a></div>' : ""}
  ${pend.length ? `<div class="panel" style="margin-bottom:14px"><h3 style="margin-top:0">待确认的建议（${pend.length}）</h3><div id="pendBox">${pend.map(proposalHtml).join("")}</div></div>` : ""}
  <div class="grid3" style="margin-bottom:14px">${B.agents.map(a => `<div class="agentcard ${a.key === CHAT.agent ? "on" : ""}" data-agent="${a.key}" tabindex="0"><b>${esc(a.name)}</b><div class="small muted">${esc(a.desc)}</div></div>`).join("")}</div>
  <div class="chatwrap"><div class="panel"><button class="btn sm pri" id="newConv" style="width:100%">新对话</button><div class="convs" style="margin-top:8px">${convs.filter(c => c.agent === CHAT.agent).map(c => `<a href="#chat-${c.id}" class="${c.id === CHAT.conv ? "on" : ""}">${esc(c.title)}${RUNNING_IDS.has(c.id) ? ' <span class="small muted">· 生成中</span>' : ""}</a>`).join("") || '<div class="small muted">还没有对话</div>'}</div></div>
    <div class="panel"><div class="row" style="justify-content:space-between;margin-bottom:8px"><b>${esc(ag.name)}</b><span class="row small"><label>模型 <select id="cModel"><option value="">按任务默认</option>${B.models.filter(m => m.enabled).map(m => `<option value="${m.id}">${esc(m.name)} · ${esc(m.model)}</option>`).join("")}</select></label>${conv ? '<button class="btn sm" id="cRegen">重新生成</button><button class="btn sm" id="cDel">删除对话</button>' : ""}</span></div>
      <div class="chat" id="chat">${conv ? conv.messages.filter(m => !(m.role === "assistant" && m.status === "streaming")).map(m => `<div class="msg ${m.role === "user" ? "u" : "a"}">${m.role === "user" ? esc(m.content) : md(m.content || "（空）")}${m.model && m.role === "assistant" ? `<div class="small muted" style="margin-top:4px">${esc(m.model)}${m.status === "error" ? " · 未完成" : ""}</div>` : ""}</div>`).join("") : `<div class="muted small">可以这样问：<br>· 根据我的进度，今天先做哪三道题？<br>· 讲讲单调栈，用题库里的题举例<br>· 给我推荐学回溯的视频<br>· 出一道考滑动窗口的选择题考考我</div>`}</div>
      <div class="row" style="margin-top:12px;flex-wrap:nowrap"><textarea id="cin" rows="2" style="flex:1;min-width:0" placeholder="Enter 发送，Shift+Enter 换行。回复在后台生成，切到别的页面也不会中断。" ${running ? "disabled" : ""}></textarea><div style="display:flex;flex-direction:column;gap:6px"><button class="btn pri" id="csend" ${running ? "disabled" : ""}>发送</button><button class="btn sm" id="cstop" hidden>停止生成</button></div></div>
      <div class="small muted" style="margin-top:6px">工具：${ag.tools.map(t => ({ get_progress: "读进度", search_questions: "搜题库", get_question: "读题目", get_today_plan: "读今日计划", get_review_queue: "读错题本", list_categories: "读模块", search_videos: "搜视频", propose_status_change: "建议改状态", propose_skip_question: "建议跳题", propose_plan_change: "建议改计划", propose_add_question: "建议加题" }[t] || t)).join("、")}</div></div></div>`;
};
V.chat.after = () => {
  bindProposals($("#main"));
  $$("[data-agent]").forEach(el => el.onclick = () => { CHAT.agent = el.dataset.agent; CHAT.conv = null; location.hash = "#chat"; render(); });
  $("#newConv").onclick = () => { CHAT.conv = null; location.hash = "#chat"; render(); };
  if ($("#cDel")) twoStep($("#cDel"), "确认删除", async () => { await api("/api/conversations/" + CHAT.conv, { method: "DELETE" }); CHAT.conv = null; location.hash = "#chat"; });
  const chat = $("#chat"); chat.scrollTop = chat.scrollHeight;
  let convId = CHAT.conv;
  const busy = on => { $("#cstop").hidden = !on; $("#csend").disabled = on; $("#cin").disabled = on; if ($("#cRegen")) $("#cRegen").disabled = on; };
  // Render a live run (new send, regenerate, or reattach after leaving the page)
  const follow = async (doFetch) => {
    if (chat.querySelector(".muted.small") && !chat.querySelector(".msg")) chat.innerHTML = "";
    const pend = document.createElement("div"); pend.className = "msg a"; pend.textContent = "思考中…"; chat.appendChild(pend); chat.scrollTop = chat.scrollHeight;
    let text = ""; CHAT.detach = new AbortController(); busy(true);
    try {
      await doFetch(ev => {
        if (CHAT.conv !== convId || !pend.isConnected) return;
        if (ev.type === "thinking" && !text) pend.textContent = "思考中（模型在推理）…";
        if (ev.type === "delta") { text += ev.text; pend.innerHTML = md(text); }
        if (ev.type === "tool") chat.insertBefore(Object.assign(document.createElement("div"), { className: "msg tool", textContent: "调用工具：" + ev.name }), pend);
        if (ev.type === "tool_result") chat.insertBefore(Object.assign(document.createElement("div"), { className: "msg tool", textContent: "↳ " + ev.summary }), pend);
        if (ev.type === "proposal" && !chat.querySelector(`[data-pid="${ev.proposal.id}"]`) && !$(`#pendBox [data-pid="${ev.proposal.id}"]`)) { const d = document.createElement("div"); d.innerHTML = proposalHtml(ev.proposal); chat.appendChild(d); bindProposals(d); }
        if (ev.type === "error") { pend.innerHTML = (text ? md(text) + "<br>" : "") + `<span class="bad-t">${esc(ev.message)}</span>`; }
        if (ev.type === "stopped") pend.insertAdjacentHTML("beforeend", '<div class="small muted">已停止生成</div>');
        if (ev.type === "done") { if (!text && ev.content) pend.innerHTML = md(ev.content); if (ev.model) pend.insertAdjacentHTML("beforeend", `<div class="small muted" style="margin-top:4px">${esc(ev.model)}</div>`); }
        chat.scrollTop = chat.scrollHeight;
      }, CHAT.detach.signal);
    } catch (e) { if (e.name !== "AbortError" && pend.isConnected) pend.innerHTML = `<span class="bad-t">${esc(e.message)}</span>`; }
    finally { if (CHAT.conv === convId && $("#cstop")) busy(false); CHAT.detach = null; refreshCounts(); }
  };
  const send = async () => {
    const v = $("#cin").value.trim(); if (!v || $("#csend").disabled) return; $("#cin").value = "";
    if (!CHAT.conv) { const c = await api("/api/conversations", { body: { agent: CHAT.agent } }); CHAT.conv = c.id; convId = c.id; history.replaceState(null, "", "#chat-" + c.id); }
    const id = CHAT.conv;
    if (!chat.querySelector(".msg")) chat.innerHTML = "";
    chat.insertAdjacentHTML("beforeend", `<div class="msg u">${esc(v)}</div>`);
    await follow((on, sig) => stream(`/api/conversations/${id}/send`, { text: v, model_id: $("#cModel").value || null }, on, sig));
  };
  $("#csend").onclick = send; $("#cin").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  $("#cstop").onclick = async () => { $("#cstop").textContent = "正在停止…"; await api(`/api/conversations/${CHAT.conv}/stop`, { body: {} }).catch(() => { }); };
  if ($("#cRegen")) $("#cRegen").onclick = async () => {
    const last = [...chat.children].reverse().find(x => x.classList.contains("u")); if (last) { while (last.nextSibling) last.nextSibling.remove(); }
    const id = CHAT.conv; await follow((on, sig) => stream(`/api/conversations/${id}/regenerate`, { model_id: $("#cModel").value || null }, on, sig));
  };
  if (CHAT.running) follow((on, sig) => attachStream(`/api/conversations/${convId}/attach?from=0`, on, sig));
};
async function attachStream(path, onEvent, signal) {
  const r = await fetch(path, { headers: { Authorization: "Bearer " + TOKEN }, signal });
  if (!r.ok) return null;
  const rd = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
  while (true) { const { value, done } = await rd.read(); if (done) break; buf += dec.decode(value, { stream: true }); let i;
    while ((i = buf.indexOf("\n\n")) >= 0) { const chunk = buf.slice(0, i); buf = buf.slice(i + 2); for (const line of chunk.split("\n")) if (line.startsWith("data: ")) { try { const ev = JSON.parse(line.slice(6)); if (ev.type) onEvent(ev); } catch (e) { } } } }
}

/* ============ resources ============ */
V.resources = async () => {
  const favs = await api("/api/resources");
  return `<h1>学习资源</h1><p class="lead">按关键词搜索学习视频。配置了 YouTube Data API Key 时直接显示视频列表；其它平台（B 站、中国大学 MOOC 等）提供搜索链接，在原站观看。可以把视频收藏到某个模块，它会出现在该模块课程旁边。</p>
  <div class="panel"><div class="row"><input type="text" id="rq" placeholder="例如：单调栈 讲解" style="flex:1;min-width:220px"><button class="btn pri" id="rgo">搜索</button></div><div id="rout" style="margin-top:12px"></div></div>
  <h2>我的收藏（${favs.length}）</h2>${favs.length ? `<div class="panel tscroll"><table class="t"><tr><th>标题</th><th>平台</th><th>模块</th><th></th></tr>${favs.map(f => `<tr><td><a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.title)}</a></td><td>${esc(f.platform)}</td><td>${esc(f.category_id ? catName(f.category_id) : "—")}</td><td><button class="btn sm" data-rdel="${f.id}">移除</button></td></tr>`).join("")}</table></div>` : '<div class="panel muted small">还没有收藏。</div>'}`;
};
V.resources.after = () => {
  const catSel = `<select class="rcat">${CATS.filter(c => !c.lesson_only).map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>`;
  const go = async () => { const v = $("#rq").value.trim(); const out = $("#rout"); if (!v) { out.innerHTML = '<span class="small muted">先输入关键词。</span>'; return; } out.innerHTML = '<span class="muted">搜索中…</span>';
    try { const r = await api("/api/resources/search?q=" + encodeURIComponent(v));
      out.innerHTML = `<div class="small muted">${r.sources.map(s => `${esc(s.name)}：${esc(s.status)}`).join("；")}</div>` +
        (r.results.length ? `<h3>视频（${r.results.length}）</h3>${r.results.map((x, i) => `<div class="row" style="border-bottom:1px solid var(--rule2);padding:8px 0;align-items:flex-start;flex-wrap:nowrap"><div style="flex:1;min-width:0"><a href="${esc(x.url)}" target="_blank" rel="noopener"><b>${esc(x.title)}</b></a><div class="small muted">${esc(x.platform)} · ${esc(x.author || "")}${x.published ? " · " + esc(x.published.slice(0, 10)) : ""}</div><div class="small">${esc((x.desc || "").slice(0, 120))}</div></div><div class="row small">${catSel}<button class="btn sm" data-rfav="${i}">收藏</button></div></div>`).join("")}` : "") +
        `<h3>在各平台搜索</h3><div class="linkcol">${r.links.map(l => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.platform)}</a>`).join("")}</div>`;
      $$("[data-rfav]").forEach(b => b.onclick = async () => { const x = r.results[+b.dataset.rfav]; await api("/api/resources", { body: { ...x, category_id: +b.parentElement.querySelector(".rcat").value } }); b.textContent = "已收藏"; });
    } catch (e) { out.innerHTML = `<div class="notice">${esc(e.message)}</div>`; } };
  $("#rgo").onclick = go; $("#rq").onkeydown = e => { if (e.key === "Enter") go(); };
  $$("[data-rdel]").forEach(b => b.onclick = async () => { await api("/api/resources/" + b.dataset.rdel, { method: "DELETE" }); render(); });
};

/* ============ import ============ */
let IMP = { text: "", name: "", source: "", job: null, items: null };
V.import = async () => {
  const I = IMP; const j = I.job;
  return `<a href="#bank" class="small">返回题库</a><h1>导入题目</h1>
  <p class="lead">粘贴题目文字，或上传 .txt / .md / .json / .csv / .pdf / .docx。模型会拆出每道题（单选、多选、判断、填空、简答、编程），整理题干、选项、答案，并判断模块和层级。你确认后才写入题库；原文没有答案的不会编造。</p>
  <div class="panel"><label class="f">题目文字<textarea id="iText" rows="8" placeholder="把题目粘贴到这里">${esc(I.text)}</textarea></label>
    <div class="row" style="margin-top:10px"><label class="btn">选择文件<input type="file" id="iFile" accept=".txt,.md,.json,.csv,.pdf,.docx" hidden></label><span class="small muted">${esc(I.name || "未选择文件")}</span>
      <label class="f" style="margin-left:auto">来源名称<input type="text" id="iSrc" value="${esc(I.source)}" placeholder="例如：2026 真题回忆版"></label>
      ${j && j.status === "running" ? `<button class="btn" id="iStop">停止</button>` : `<button class="btn pri" id="iRun">开始拆题和分类</button>`}</div>
    ${j && j.status === "running" ? `<div class="small muted" style="margin-top:8px">处理中：第 ${j.done}/${j.total || "?"} 段…</div>` : ""}
    ${j && j.error ? `<div class="notice" style="margin-top:10px">处理中断：${esc(j.error)}</div>` : ""}</div>
  ${I.items && I.items.length ? `<h2>识别出 ${I.items.length} 道题，请确认</h2><p class="small muted">有问题的题（缺答案、缺选项等）和题库里已有同名题默认不勾选；可以改题名、模块、层级。新模块名称会在导入时自动创建。</p>
   <div class="panel tscroll"><table class="t"><tr><th>导入</th><th>题目</th><th>题型</th><th>模块</th><th>层级</th><th>检查</th></tr>
   ${I.items.map((it, i) => `<tr><td><input type="checkbox" data-ii="${i}" ${it.include ? "checked" : ""} aria-label="导入"></td>
     <td><input type="text" data-it="${i}" value="${esc(it.title)}" style="width:100%;min-width:160px"><details class="small"><summary>看题目</summary><div class="desc">${esc(it.stem)}</div>${it.options.map((o, k) => `<div>${"ABCDEFGH"[k]}. ${esc(o)}</div>`).join("")}<div class="muted">答案：${esc(JSON.stringify(it.answer))}</div></details></td>
     <td>${esc(B.types[it.type])}</td>
     <td><select data-ic="${i}">${it.cls.category_name ? `<option value="new" selected>新建：${esc(it.cls.category_name)}</option>` : ""}<option value="" ${!it.cls.category_name && !it.cls.category_id ? "selected" : ""}>未分类</option>${CATS.filter(c => !c.lesson_only).map(c => `<option value="${c.id}" ${c.id === it.cls.category_id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></td>
     <td><select data-itr="${i}">${[1, 2, 3, 4].map(n => `<option value="${n}" ${n === it.cls.tier ? "selected" : ""}>L${n} ${B.tiers[n].name}</option>`).join("")}</select><div class="small muted">${esc(it.cls.reason || "")}</div></td>
     <td class="small">${it.dup ? '<div style="color:var(--amber)">已有同名题</div>' : ""}${it.problems.length ? `<div style="color:var(--red)">${esc(it.problems.join("、"))}</div>` : '<span class="ok-t">完整</span>'}</td></tr>`).join("")}</table></div>
   <div class="row" style="margin-top:12px"><button class="btn pri" id="iSave">导入勾选的 ${I.items.filter(x => x.include).length} 道题</button><button class="btn" id="iClear">清空结果</button></div>` : ""}`;
};
let impPoll = null;
V.import.after = () => {
  const keep = () => { IMP.text = $("#iText").value; IMP.source = $("#iSrc").value; };
  $("#iFile").onchange = async e => { const f = e.target.files[0]; if (!f) return; keep(); const fd = new FormData(); fd.append("file", f); try { const r = await api("/api/import/extract", { body: fd }); IMP.text = r.text; IMP.name = r.name; IMP.source = IMP.source || f.name.replace(/\.[^.]+$/, ""); render(); } catch (err) { toast(err.message); } };
  if ($("#iRun")) $("#iRun").onclick = async () => { keep(); if (!IMP.text.trim()) return toast("先粘贴内容或选择文件"); try { IMP.items = null; IMP.job = await api("/api/jobs/import", { body: { text: IMP.text } }); poll(); render(); } catch (e) { toast(e.message); } };
  if ($("#iStop")) $("#iStop").onclick = () => api(`/api/jobs/${IMP.job.id}/cancel`, { body: {} });
  const poll = () => { clearInterval(impPoll); impPoll = setInterval(async () => { try { const j = await api("/api/jobs/" + IMP.job.id); IMP.job = j; if (j.result) IMP.items = j.result; if (j.status !== "running") { clearInterval(impPoll); if (j.status === "done" && !(j.result || []).length) IMP.job.error = "没有识别出完整的题目"; } if (ROUTE.view === "import") render(); } catch (e) { clearInterval(impPoll); } }, 1200); };
  $$("[data-ii]").forEach(c => c.onchange = () => { IMP.items[+c.dataset.ii].include = c.checked; $("#iSave").textContent = `导入勾选的 ${IMP.items.filter(x => x.include).length} 道题`; });
  $$("[data-it]").forEach(c => c.oninput = () => { IMP.items[+c.dataset.it].title = c.value; });
  $$("[data-ic]").forEach(c => c.onchange = () => { const it = IMP.items[+c.dataset.ic]; if (c.value === "new") { it.cls.category_id = null; } else if (c.value === "") { it.cls.category_id = null; it.cls.category_name = null; } else { it.cls.category_id = +c.value; it.cls.category_name = null; } it.cls.edited = true; });
  $$("[data-itr]").forEach(c => c.onchange = () => { const it = IMP.items[+c.dataset.itr]; it.cls.tier = +c.value; it.cls.edited = true; });
  if ($("#iSave")) $("#iSave").onclick = async () => { keep(); try { const r = await api("/api/import/save", { body: { items: IMP.items, source: IMP.source || "导入" } }); CATS = await api("/api/categories"); toast(`已导入 ${r.ids.length} 道题`); IMP = { text: "", name: "", source: "", job: null, items: null }; location.hash = "#bank"; } catch (e) { toast(e.message); } };
  if ($("#iClear")) $("#iClear").onclick = () => { IMP.items = null; IMP.job = null; render(); };
};

/* ============ classify ============ */
let CLS = { job: null };
V.classify = async () => {
  const j = CLS.job; const qs = await api("/api/questions"); const byId = Object.fromEntries(qs.map(q => [q.id, q]));
  const rows = j && j.result ? Object.entries(j.result).filter(([id]) => byId[id]).map(([id, c]) => ({ q: byId[id], c, changed: c.category_id !== byId[id].category_id || c.tier !== byId[id].tier })) : [];
  return `<a href="#bank" class="small">返回题库</a><h1>AI 分类分层</h1><p class="lead">让模型判断每道题属于哪个模块、哪一层（L1 入门 → L4 挑战）和知识点。结果先列出来对照，你确认后才写入题库。</p>
  <div class="panel row" style="gap:14px;align-items:flex-end"><label class="f">范围<select id="cScope"><option value="default">还没确认过分层的题（${qs.filter(q => q.cls_by === "default").length}）</option><option value="all">全部题目（${qs.length}）</option><option value="mine">我导入或录入的题</option>${Object.entries(B.types).map(([k, v]) => `<option value="${k}">全部${v}题</option>`).join("")}</select></label>
    ${j && j.status === "running" ? `<button class="btn" id="cStop">停止</button><span class="small">已完成 ${j.done}/${j.total}…</span>` : `<button class="btn pri" id="cRun">开始分类</button>`}<span class="small muted">每次调用处理 10 题。</span></div>
  ${j && j.error ? `<div class="notice" style="margin-top:10px">中断：${esc(j.error)}。已完成的部分可以先确认。</div>` : ""}
  ${rows.length ? `<h2>模型建议（${rows.length} 题，${rows.filter(r => r.changed).length} 题和当前不同）</h2><div class="row" style="margin-bottom:8px"><button class="btn pri" id="cAll">全部采用</button><button class="btn" id="cSel">采用勾选的</button><button class="btn" id="cDrop">放弃这批结果</button></div>
   <div class="panel tscroll"><table class="t"><tr><th></th><th>题目</th><th>当前</th><th>建议</th><th>知识点与理由</th></tr>${rows.map(({ q, c, changed }) => `<tr><td><input type="checkbox" data-cs="${esc(q.id)}" checked aria-label="采用"></td><td><a href="#q-${esc(q.id)}">${esc(q.title)}</a> ${typeBadge(q.type)}</td><td class="small">${esc(catName(q.category_id))}<br>${tierChip(q.tier)}</td><td class="small" style="${changed ? "background:var(--amber-soft)" : ""}">${esc(catName(c.category_id))}<br>${tierChip(c.tier)} <span class="muted">难度 ${c.score}/10</span></td><td class="small">${esc(c.points.join("、"))}<div class="muted">${esc(c.reason)}</div></td></tr>`).join("")}</table></div>` : ""}`;
};
let clsPoll = null;
V.classify.after = () => {
  if ($("#cRun")) $("#cRun").onclick = async () => { try { CLS.job = await api("/api/jobs/classify", { body: { scope: $("#cScope").value } }); render(); clearInterval(clsPoll); clsPoll = setInterval(async () => { const j = await api("/api/jobs/" + CLS.job.id); CLS.job = j; if (j.status !== "running") clearInterval(clsPoll); if (ROUTE.view === "classify") render(); }, 1500); } catch (e) { toast(e.message); } };
  if ($("#cStop")) $("#cStop").onclick = () => api(`/api/jobs/${CLS.job.id}/cancel`, { body: {} });
  const apply = async ids => { const res = Object.fromEntries(ids.map(id => [id, CLS.job.result[id]])); const r = await api("/api/classify/apply", { body: { results: res } }); toast(`已采用 ${r.applied} 题`); CLS.job = null; render(); };
  if ($("#cAll")) $("#cAll").onclick = () => apply(Object.keys(CLS.job.result));
  if ($("#cSel")) $("#cSel").onclick = () => apply($$("[data-cs]").filter(c => c.checked).map(c => c.dataset.cs));
  if ($("#cDrop")) twoStep($("#cDrop"), "确认放弃", () => { CLS.job = null; render(); });
};

/* ============ models ============ */
V.models = async () => {
  const M = await api("/api/models"); const U = await api("/api/usage?days=30");
  return `<h1>模型</h1><p class="lead">平台通过两种接口接入模型：OpenAI 兼容接口（DeepSeek、通义千问、Kimi、智谱、OpenAI，以及本地部署的模型）和 Anthropic 接口（Claude）。API Key 只保存在运行平台的电脑上，页面和日志里不会显示完整 Key。</p>
  <div class="panel"><h3 style="margin-top:0">添加模型</h3><div class="row" style="gap:12px;align-items:flex-end">
    <label class="f">服务商<select id="mPreset">${M.presets.map(p => `<option value="${p.key}">${esc(p.name)}</option>`).join("")}</select></label>
    <label class="f">显示名称<input type="text" id="mName"></label><label class="f">API 地址<input type="text" id="mUrl" style="min-width:260px"></label>
    <label class="f">模型名<input type="text" id="mModel"></label><label class="f">API Key<input type="password" id="mKey" autocomplete="off"></label>
    <label class="f">超时（秒）<input type="number" id="mTimeout" value="60" style="width:80px"></label></div>
    <div class="row small" style="margin-top:10px"><label class="row"><input type="checkbox" id="cTools">支持工具调用</label><label class="row"><input type="checkbox" id="cStream">支持流式输出</label><label class="row"><input type="checkbox" id="cJson">支持 JSON 模式</label><label class="row"><input type="checkbox" id="cVision">支持图片</label>
      <label>输入价格（元/百万 tokens）<input type="number" id="mPin" step="0.01" style="width:80px"></label><label>输出价格<input type="number" id="mPout" step="0.01" style="width:80px"></label><label>价格来源与日期<input type="text" id="mPnote" placeholder="例如：官网定价 2026-11"></label></div>
    <div class="row" style="margin-top:12px"><button class="btn pri" id="mAdd">添加</button><span class="small muted">模型名以服务商控制台为准；不支持的能力会在使用时自动关闭。</span></div></div>
  <h2>已接入（${M.models.length}）</h2>${M.models.length ? `<div class="panel tscroll"><table class="t"><tr><th>名称</th><th>接口 / 地址</th><th>模型</th><th>Key</th><th>能力</th><th>状态</th><th></th></tr>${M.models.map(m => `<tr><td>${esc(m.name)}${m.owner_id ? "" : ' <span class="chip">平台共享</span>'}</td><td class="small">${m.provider === "anthropic" ? "Anthropic" : "OpenAI 兼容"}<br>${esc(m.base_url)}</td><td><input type="text" value="${esc(m.model)}" data-mm="${m.id}" style="width:150px"></td><td class="small">${esc(m.key_hint)} <button class="btn sm" data-mk="${m.id}">更换</button></td><td class="small">${["tools", "stream", "json", "vision"].filter(k => m.caps[k]).map(k => ({ tools: "工具", stream: "流式", json: "JSON", vision: "图片" }[k])).join("、") || "—"}</td><td><span class="status-dot ${m.enabled ? "ok" : "off"}"></span>${m.enabled ? "启用" : "停用"}<div class="small" id="mt-${m.id}"></div></td><td><div class="row"><button class="btn sm" data-mt="${m.id}">测试连接</button><button class="btn sm" data-me="${m.id}" data-en="${m.enabled}">${m.enabled ? "停用" : "启用"}</button><button class="btn sm" data-md="${m.id}">删除</button></div></td></tr>`).join("")}</table></div>` : '<div class="panel muted small">还没有接入模型。</div>'}
  <h2>按任务选择模型</h2><div class="panel"><div class="kv">${Object.entries(M.tasks).map(([k, v]) => `<b>${esc(v)}</b><select data-route="${k}"><option value="">默认（第一个可用模型）</option>${M.models.map(m => `<option value="${m.id}" ${M.routes[k] === m.id ? "selected" : ""}>${esc(m.name)} · ${esc(m.model)}</option>`).join("")}</select>`).join("")}</div>
    <p class="small muted">失败时不会自动切换到其它服务商的模型，避免重复扣费和数据发到你没选的服务商。</p></div>
  <h2>同题多模型对比</h2><div class="panel"><textarea id="cmpQ" rows="3" style="width:100%" placeholder="输入一个问题，比较不同模型的回答"></textarea><div class="row small" style="margin-top:6px">${M.models.filter(m => m.enabled).map(m => `<label class="row"><input type="checkbox" data-cmp="${m.id}">${esc(m.name)}</label>`).join("")}<button class="btn sm pri" id="cmpGo">对比</button></div><div id="cmpOut" class="grid2" style="margin-top:10px"></div><p class="small muted">各模型回答分别展示，不合并成一个结论。</p></div>
  <h2>近 30 天用量</h2>${U.length ? `<div class="panel tscroll"><table class="t"><tr><th>模型</th><th>任务</th><th>结果</th><th>次数</th><th>输入 tokens</th><th>输出 tokens</th><th>平均耗时</th><th>估算费用</th></tr>${U.map(r => `<tr><td>${esc(r.name || "已删除")}</td><td>${esc(M.tasks[r.task] || r.task)}</td><td>${r.status === "ok" ? "成功" : esc(r.status)}</td><td>${r.n}</td><td>${r.pin || 0}${r.unknown ? `<div class="small muted">${r.unknown} 次未知</div>` : ""}</td><td>${r.pout || 0}</td><td>${Math.round(r.lat || 0)} ms</td><td>${r.cost == null ? '<span class="muted">未知（未填价格）</span>' : "¥" + r.cost + (r.price_note ? `<div class="small muted">${esc(r.price_note)}</div>` : "")}</td></tr>`).join("")}</table></div>` : '<div class="panel muted small">还没有调用记录。</div>'}`;
};
V.models.after = async () => {
  const M = await api("/api/models");
  const fill = () => { const p = M.presets.find(x => x.key === $("#mPreset").value); $("#mName").value = p.name; $("#mUrl").value = p.base_url; $("#mModel").value = p.model; $("#cTools").checked = p.caps.tools; $("#cStream").checked = p.caps.stream; $("#cJson").checked = p.caps.json; $("#cVision").checked = p.caps.vision; };
  $("#mPreset").onchange = fill; fill();
  $("#mAdd").onclick = async () => { try { const p = M.presets.find(x => x.key === $("#mPreset").value); await api("/api/models", { body: { preset: p.key, name: $("#mName").value, base_url: $("#mUrl").value, model: $("#mModel").value, api_key: $("#mKey").value, timeout: +$("#mTimeout").value, caps: { ...p.caps, tools: $("#cTools").checked, stream: $("#cStream").checked, json: $("#cJson").checked, vision: $("#cVision").checked }, price_in: $("#mPin").value ? +$("#mPin").value : null, price_out: $("#mPout").value ? +$("#mPout").value : null, price_note: $("#mPnote").value } }); await reloadBoot(); toast("已添加，点「测试连接」确认可用"); render(); } catch (e) { toast(e.message); } };
  $$("[data-mt]").forEach(b => b.onclick = async () => { const o = $("#mt-" + b.dataset.mt); o.textContent = "测试中…"; const r = await api(`/api/models/${b.dataset.mt}/test`, { body: {} }); o.innerHTML = r.ok ? `<span class="ok-t">连接正常（${r.ms} ms）${r.tools === false ? "；不支持工具调用" : r.tools ? "；工具调用正常" : ""}</span>` : `<span class="bad-t">${esc(r.error)}</span>`; });
  $$("[data-me]").forEach(b => b.onclick = async () => { await api("/api/models/" + b.dataset.me, { method: "PUT", body: { enabled: b.dataset.en === "1" ? 0 : 1 } }); await reloadBoot(); render(); });
  $$("[data-md]").forEach(b => twoStep(b, "确认删除", async () => { await api("/api/models/" + b.dataset.md, { method: "DELETE" }); await reloadBoot(); render(); }));
  $$("[data-mm]").forEach(i => i.onchange = async () => { await api("/api/models/" + i.dataset.mm, { method: "PUT", body: { model: i.value } }); toast("已更新模型名"); });
  $$("[data-mk]").forEach(b => b.onclick = () => { b.outerHTML = `<input type="password" data-mkv="${b.dataset.mk}" placeholder="新 Key，回车保存" style="width:150px">`; const i = $(`[data-mkv="${b.dataset.mk}"]`); i.focus(); i.onkeydown = async e => { if (e.key === "Enter" && i.value.trim()) { await api("/api/models/" + i.dataset.mkv, { method: "PUT", body: { api_key: i.value.trim() } }); toast("Key 已更换"); render(); } }; });
  $$("[data-route]").forEach(s => s.onchange = async () => { await api("/api/routes", { method: "PUT", body: { [s.dataset.route]: s.value ? +s.value : null } }); toast("已保存"); });
  $("#cmpGo").onclick = async () => { const ids = $$("[data-cmp]").filter(c => c.checked).map(c => +c.dataset.cmp); if (ids.length < 2) return toast("至少选两个模型"); const out = $("#cmpOut"); out.innerHTML = '<div class="muted">请求中…</div>'; const r = await api("/api/compare", { body: { prompt: $("#cmpQ").value, model_ids: ids } }); out.innerHTML = r.map(x => `<div class="panel"><b>${esc(x.model)}</b> <span class="small muted">${x.ms} ms${x.usage && x.usage.out ? " · 输出 " + x.usage.out + " tokens" : ""}</span><div class="lesson-text small" style="margin-top:6px">${x.error ? `<span class="bad-t">${esc(x.error)}</span>` : md(x.content)}</div></div>`).join(""); };
};

/* ============ settings ============ */
V.settings = async () => {
  const S = await api("/api/system"); const isAdmin = B.user.role === "admin"; const users = isAdmin ? await api("/api/users") : [];
  const me = users.find(u => u.id === B.user.id);
  return `<h1>设置</h1><div class="grid2">
  <div class="panel"><h3 style="margin-top:0">设备与互通</h3>
    <p class="small">同一个平台可以在电脑、手机、平板上一起用，数据都存在运行平台的这台电脑上，所有设备看到的是同一份进度。</p>
    <div class="kv"><b>当前地址</b><span>${esc(location.origin)}</span><b>局域网地址</b><span>${S.lan.length ? S.lan.map(u => `<code>${esc(u)}</code>`).join("<br>") : "—"}</span>
    <b>允许手机连接</b><span>${isAdmin ? `<label class="row"><input type="checkbox" id="lanToggle" ${S.lan_config ? "checked" : ""}> 开启后，同一 Wi-Fi 的手机 App 或浏览器可以连接这台电脑</label>` : (S.lan_running ? "已开启" : "未开启")}
      <div class="small ${S.lan_config !== S.lan_running ? "bad-t" : "muted"}" id="lanMsg">${S.lan_config !== S.lan_running ? "设置已保存，重新打开 StudyAgent 后生效。" : S.lan_running ? "正在接受局域网连接。手机 App 里填上面的局域网地址。" : ""}</div></span>
    ${IN_APP ? `<b>手机 App</b><span><a class="btn sm" href="${APP_HOME}">连接其它电脑</a></span>` : ""}
    ${me ? `<b>我的访问码</b><span><code id="myCode" style="word-break:break-all">${esc(me.code)}</code> <button class="btn sm" id="copyCode">复制</button></span>` : ""}</div>
    <p class="small muted">其它设备第一次打开时输入访问码即可登录。外部程序调用接口时在请求头加 <code>Authorization: Bearer 访问码</code>，接口列表见 <a href="/api/docs" target="_blank">/api/docs</a>。</p>
    <h3>备份与迁移</h3><p class="small">导出你的全部学习记录（进度、作答、复习、测试、目标、对话、自己的题），可在另一台电脑的平台上导入。</p>
    <div class="row"><button class="btn" id="exp">导出备份</button><label class="btn">导入备份<input type="file" id="impF" accept=".json" hidden></label></div>
    <p class="small muted">数据目录：${esc(S.data_dir)}</p></div>
  <div class="panel"><h3 style="margin-top:0">个人</h3><label class="f">昵称<input type="text" id="meName" value="${esc(B.user.name)}"></label><button class="btn sm" id="meSave" style="margin-top:8px">保存</button>
    ${isAdmin ? `<h3>用户（多人使用）</h3><p class="small muted">每个用户有自己的进度、错题、测试、对话和私有题库；平台题库和平台共享模型大家共用。</p>
    <div class="tscroll"><table class="t small"><tr><th>名称</th><th>角色</th><th>访问码</th><th></th></tr>${users.map(u => `<tr><td>${esc(u.name)}</td><td>${u.role === "admin" ? "管理员" : "用户"}</td><td><code style="word-break:break-all">${esc(u.code.slice(0, 6))}…</code></td><td><button class="btn sm" data-reset="${u.id}">重置访问码</button></td></tr>`).join("")}</table></div>
    <div class="row" style="margin-top:8px"><input type="text" id="nuName" placeholder="新用户名称"><button class="btn sm" id="nuAdd">添加用户</button></div><div id="nuOut" class="small"></div>
    <h3>视频接口</h3><label class="f">YouTube Data API Key（可选，填了会直接显示视频搜索结果）<input type="password" id="ytKey" placeholder="${S.youtube ? "已配置，填新值可更换" : "未配置"}"></label><button class="btn sm" id="ytSave" style="margin-top:6px">保存</button>` : ""}
  </div></div>
  <h2>学科与模块</h2><div class="panel">${B.subjects.map(s => `<div style="margin-bottom:10px"><b>${esc(s.name)}</b>${s.id === B.goal.subject_id ? ' <span class="chip s1">当前</span>' : ""}<div class="small muted">${esc(s.description || "")}</div></div>`).join("")}
    <div class="row" style="align-items:flex-end;margin-top:10px"><label class="f">新学科名称<input type="text" id="nsName" placeholder="例如：软考中级"></label><label class="f" style="flex:1">模块（逗号分隔）<input type="text" id="nsCats" placeholder="例如：计算机基础, 数据结构, 操作系统, 网络"></label><button class="btn" id="nsAdd">创建学科</button></div>
    <p class="small muted">新学科使用通用试卷结构（单选/判断 + 多选/填空 + 简答/编程）。创建后在「学习计划」里切换学科，在「题库 → 导入题目」导入题，在每个模块里让 AI 生成课程。</p>
    <h3>当前学科的模块</h3><div class="row">${CATS.map(c => `<span class="chip">${esc(c.name)}</span>`).join("")}</div>
    <div class="row" style="margin-top:8px"><input type="text" id="ncName" placeholder="新模块名称"><button class="btn sm" id="ncAdd">添加模块</button></div></div>`;
};
V.settings.after = () => {
  if ($("#lanToggle")) $("#lanToggle").onchange = async e => { const r = await api("/api/settings/lan", { method: "PUT", body: { lan: e.target.checked } }); $("#lanMsg").textContent = r.restart_needed ? "设置已保存，重新打开 StudyAgent 后生效。" : (r.lan ? "正在接受局域网连接。" : ""); $("#lanMsg").className = "small " + (r.restart_needed ? "bad-t" : "muted"); };
  if ($("#copyCode")) $("#copyCode").onclick = async () => { try { await navigator.clipboard.writeText($("#myCode").textContent); toast("已复制"); } catch (e) { toast("请手动选中复制"); } };
  $("#exp").onclick = async () => { const r = await fetch("/api/export", { headers: { Authorization: "Bearer " + TOKEN } }); const blob = await r.blob(); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "studyagent-backup-" + todayStr() + ".json"; a.click(); };
  $("#impF").onchange = async e => { const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f); try { const r = await api("/api/import-data", { body: fd }); toast(`已导入 ${r.rows} 条记录`); await reloadBoot(); render(); } catch (err) { toast(err.message); } };
  $("#meSave").onclick = async () => { await api("/api/me", { method: "PUT", body: { name: $("#meName").value } }); await reloadBoot(); toast("已保存"); };
  if ($("#nuAdd")) $("#nuAdd").onclick = async () => { const r = await api("/api/users", { body: { name: $("#nuName").value } }); $("#nuOut").innerHTML = `已添加「${esc(r.name)}」，访问码：<code style="word-break:break-all">${esc(r.code)}</code>（请交给对方）`; };
  $$("[data-reset]").forEach(b => twoStep(b, "确认重置（旧访问码失效）", async () => { const r = await api(`/api/users/${b.dataset.reset}/reset`, { body: {} }); $("#nuOut").innerHTML = `新访问码：<code style="word-break:break-all">${esc(r.code)}</code>`; if (+b.dataset.reset === B.user.id) { TOKEN = r.code; localStorage.setItem("sa_token", TOKEN); } }));
  if ($("#ytSave")) $("#ytSave").onclick = async () => { await api("/api/settings/youtube_key", { method: "PUT", body: { key: $("#ytKey").value.trim() } }); toast("已保存"); };
  $("#nsAdd").onclick = async () => { const name = $("#nsName").value.trim(); if (!name) return toast("先填学科名称"); await api("/api/subjects", { body: { name, categories: $("#nsCats").value.split(/[,，、]/).map(s => s.trim()).filter(Boolean) } }); await reloadBoot(); toast("已创建，在「学习计划」里切换到这个学科"); render(); };
  $("#ncAdd").onclick = async () => { const n = $("#ncName").value.trim(); if (!n) return; await api("/api/categories", { body: { name: n } }); CATS = await api("/api/categories"); render(); };
};

boot();

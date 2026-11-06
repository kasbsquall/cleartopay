"use strict";

/* ---------- Vocabulary ---------- */
const NAMES = {
  ofac: "OFAC sanctions search",
  sam: "SAM.gov exclusions",
  colorado: "Colorado business registry",
  vendor_site: "Vendor website (untrusted)",
};
const SHORT = { ofac: "OFAC sanctions", sam: "SAM.gov exclusions", colorado: "Colorado registry", vendor_site: "Vendor website" };
const ILLUS = {
  ofac: "/material/scan-ofac.jpg",
  sam: "/material/scan-sam.jpg",
  colorado: "/material/scan-registro.jpg",
  vendor_site: "/material/scan-web-proveedor.jpg",
};
const VERDICTS = {
  clear: { label: "Clear", icon: "ph-check-circle" },
  verified: { label: "Verified", icon: "ph-seal-check" },
  review: { label: "Review", icon: "ph-warning" },
  hit: { label: "Hit", icon: "ph-prohibit" },
  error: { label: "Error", icon: "ph-warning-octagon" },
  contained: { label: "Contained", icon: "ph-shield-warning" },
};
const DECISIONS = {
  clear_to_pay: { label: "Clear to pay", icon: "ph-check-circle", gate: "Gate open, waiting for a person to approve", gateIcon: "ph-door-open" },
  needs_human: { label: "Needs a human", icon: "ph-user-focus", gate: "Payment held at the gate", gateIcon: "ph-hand-palm" },
  blocked: { label: "Blocked", icon: "ph-prohibit", gate: "Payment stopped at the gate", gateIcon: "ph-prohibit" },
};
const WHY = {
  review: "A person should look at the evidence before paying.",
  hit: "The vendor is listed. Do not pay.",
  error: "The check did not finish. An unfinished check never clears a vendor.",
  contained: "The vendor's website tried to give instructions to the agent. Contained inside its microVM.",
};
const STATE_NAMES = { CO: "Colorado" };
const POLL_MS = 2000;
const SAMPLE = { legal_name: "Ball Corporation", state: "CO" };

/* ---------- Helpers ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (name) => `<i class="ph-light ${name}" aria-hidden="true"></i>`;
const app = $("#app");
const live = $("#live");
const announce = (msg) => { live.textContent = ""; setTimeout(() => { live.textContent = msg; }, 30); };
const shortHash = (h) => (h ? `${h.slice(0, 12)}…${h.slice(-4)}` : "");
const secs = (n) => `${Number(n).toFixed(1)} s`;
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
const stateName = (code) => STATE_NAMES[code] || code;
const shotUrl = (id, check) => `/api/runs/${encodeURIComponent(id)}/checks/${encodeURIComponent(check)}/screenshot`;
const viewVerdict = (rec) => (rec.injection ? "contained" : rec.verdict in VERDICTS ? rec.verdict : "error");

const fmtDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
const fmtTime = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit", timeZoneName: "short" });
const when = (iso, f = fmtDate) => { const d = new Date(iso); return isNaN(d) ? "" : f.format(d); };

async function api(path, opts = {}) {
  const headers = { Accept: "application/json" };
  if (opts.body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...opts, headers });
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  return { ok: res.ok, status: res.status, body };
}
const detailOf = (body, fallback) => (body && typeof body.detail === "string" ? body.detail : fallback);

/* ---------- Sound (Kenney CC0, see /sfx/License.txt) ---------- */
const sound = { on: true, clips: {} };
try { sound.on = localStorage.getItem("ctp-sound") !== "off"; } catch { /* storage blocked */ }
for (const n of ["select", "sealed", "approved"]) {
  const a = new Audio(`/sfx/${n}.mp3`);
  a.preload = "auto";
  a.volume = n === "select" ? 0.2 : 0.3;
  sound.clips[n] = a;
}
function play(name) {
  if (!sound.on) return;
  const a = sound.clips[name];
  if (!a) return;
  try { a.currentTime = 0; a.play().catch(() => {}); } catch { /* ignore */ }
}
function paintSound() {
  const b = $("#sound");
  b.setAttribute("aria-pressed", String(sound.on));
  b.innerHTML = `${icon(sound.on ? "ph-speaker-simple-high" : "ph-speaker-simple-slash")}<span>${sound.on ? "Sound on" : "Sound off"}</span>`;
}
$("#sound").addEventListener("click", () => {
  sound.on = !sound.on;
  try { localStorage.setItem("ctp-sound", sound.on ? "on" : "off"); } catch { /* ignore */ }
  paintSound();
  play("select");
});
paintSound();

/* ---------- Router ---------- */
let view = null; // current run view state
const startedHere = new Set();

function route() {
  stopRun();
  const id = new URLSearchParams(location.search).get("run");
  const nav = $("#nav-new");
  if (id) nav.removeAttribute("aria-current");
  else nav.setAttribute("aria-current", "page");
  if (id) showRun(id);
  else showHome();
}
function go(url) {
  history.pushState(null, "", url);
  route();
  window.scrollTo(0, 0);
}
window.addEventListener("popstate", route);
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-nav]");
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  go(a.getAttribute("href"));
});

/* ---------- Recent files (shared by both screens) ---------- */
function recentSkeleton() {
  return `<ul class="history" aria-busy="true">${[0, 1, 2].map(() =>
    `<li><span style="display:block;padding:12px 0;border-top:1px solid var(--line)"><span class="sk" style="width:60%"></span><br><span class="sk" style="width:40%;margin-top:6px"></span></span></li>`).join("")}</ul>`;
}
function decisionChip(item) {
  if (item.status !== "done") {
    const label = item.status === "queued" ? "Queued" : "Running";
    return `<span class="h-dec running">${icon("ph-circle-notch")}${label}</span>`;
  }
  const d = DECISIONS[item.decision];
  return d ? `<span class="h-dec ${item.decision}">${icon(d.icon)}${d.label}</span>` : `<span class="h-dec">No decision</span>`;
}
async function loadRecent(target, currentId) {
  if (!target) return;
  if (!target.querySelector(".history a")) target.innerHTML = recentSkeleton();
  let res;
  try { res = await api("/api/runs"); } catch { res = null; }
  if (!target.isConnected) return;
  if (!res || !res.ok || !Array.isArray(res.body)) {
    target.innerHTML = `<div class="notice err">${icon("ph-warning-circle")}<span>Could not load recent vendor files. <button class="btn-link" type="button" data-retry>Try again</button></span></div>`;
    $("[data-retry]", target).addEventListener("click", () => loadRecent(target, currentId));
    return;
  }
  if (!res.body.length) {
    target.innerHTML = `<p class="empty-state">No vendor files yet.<small>Check a vendor and its file will appear here.</small></p>`;
    return;
  }
  target.innerHTML = `<ul class="history">${res.body.slice(0, 8).map((r, i) => {
    const v = r.vendor || {};
    const cur = r.id === currentId ? ' aria-current="page"' : "";
    return `<li style="--r:${Math.min(i, 7)}"><a href="/?run=${encodeURIComponent(r.id)}" data-nav${cur}>
      <span class="h-name">${esc(v.legal_name)}${v.state ? `, ${esc(v.state)}` : ""}</span>${decisionChip(r)}
      <span class="h-note">Requested ${esc(when(r.requested_at))}${v.website ? ` · website given` : ""}</span></a></li>`;
  }).join("")}</ul>`;
}
const EVAL_BLOCK = `<div class="eval"><b>0 of 18</b><p>dangerous vendors cleared in the eval of 30 vendors with known answers.</p>
  <p>27 of 30 decisions correct. About 28 s per vendor for three checks.</p></div>`;

/* ---------- Home: check a vendor ---------- */
function showHome() {
  document.title = "Check a vendor · ClearToPay";
  const stations = ["ofac", "sam", "colorado", "vendor_site"].map((c, i) => `
    <div class="station">
      <span class="film" aria-hidden="true"><img src="${ILLUS[c]}" alt="" width="800" height="537" loading="lazy"><span class="sweep" style="--i:${i}"></span></span>
      <b>${icon(["ph-scales", "ph-bank", "ph-buildings", "ph-globe-simple"][i])}${esc(NAMES[c])}</b>
      <span>${esc(["Treasury sanctions list, name score 90 and up.", "Active federal exclusions.", "Registration and standing with the Colorado Secretary of State.", "Optional. Opened as untrusted content; instructions on the page are contained."][i])}</span>
    </div>`).join("");
  app.innerHTML = `
  <div class="home">
    <section class="intake" aria-labelledby="h-check">
      <div class="rise">
        <h1 id="h-check">Check a vendor</h1>
        <p class="lede">Before you pay a new vendor, ClearToPay searches three official sources. Each search runs a real browser inside its own disposable microVM, then the file comes back with screenshots, hashes and a decision.</p>
      </div>
      <form class="form rise" style="--i:1" id="check-form" novalidate>
        <div class="field">
          <label for="f-name">Legal name</label>
          <input id="f-name" name="legal_name" autocomplete="organization" required minlength="2" maxlength="120" placeholder="Exact legal name, as registered" aria-describedby="e-name">
          <span class="err-msg" id="e-name" hidden></span>
        </div>
        <div class="field">
          <label for="f-state">State</label>
          <input id="f-state" name="state" class="upper" value="CO" required maxlength="2" autocomplete="off" aria-describedby="e-state">
          <span class="err-msg" id="e-state" hidden></span>
        </div>
        <div class="field">
          <label for="f-web">Website <span style="color:var(--ink-3);font-weight:400">(optional)</span></label>
          <input id="f-web" name="website" inputmode="url" maxlength="200" autocomplete="url" placeholder="example.com" aria-describedby="e-web h-web">
          <span class="hint" id="h-web">Opened as untrusted content in its own microVM.</span>
          <span class="err-msg" id="e-web" hidden></span>
        </div>
        <div class="notice" id="form-msg" hidden></div>
        <div class="row-actions">
          <button class="btn btn-metal" type="submit" id="go">${icon("ph-scan")}<span>Run the checks</span></button>
          <button class="btn btn-ghost" type="button" id="sample">${icon("ph-package")}<span>Try a sample vendor</span></button>
          <span class="why">${icon("ph-timer")}About 28 s per vendor. One vendor runs at a time.</span>
        </div>
      </form>
      <div class="stations rise" style="--i:2" role="list" aria-label="What gets checked">${stations.replace(/<div class="station">/g, '<div class="station" role="listitem">')}</div>
    </section>
    <aside class="side rise" style="--i:3" aria-labelledby="h-recent">
      <h2 id="h-recent">${icon("ph-clock-counter-clockwise")}Recent vendor files</h2>
      <div id="recent"></div>
      ${EVAL_BLOCK}
    </aside>
  </div>`;
  loadRecent($("#recent"), null);
  const form = $("#check-form");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const payload = readForm(form);
    if (payload) startRun(payload, $("#go"));
  });
  $("#sample").addEventListener("click", () => startRun({ ...SAMPLE }, $("#sample")));
}

function setFieldError(id, msg) {
  const input = $(`#f-${id}`);
  const out = $(`#e-${id}`);
  if (!input || !out) return;
  input.setAttribute("aria-invalid", msg ? "true" : "false");
  out.hidden = !msg;
  out.textContent = msg || "";
}
function readForm(form) {
  const name = form.legal_name.value.trim();
  const state = form.state.value.trim().toUpperCase();
  const website = form.website.value.trim();
  let ok = true;
  const errs = {
    name: name.length < 2 ? "Enter the vendor's legal name, at least 2 characters." : name.length > 120 ? "Keep the name under 120 characters." : "",
    state: /^[A-Z]{2}$/.test(state) ? "" : "Use the two-letter state code, for example CO.",
    web: website.length > 200 ? "Keep the website under 200 characters." : "",
  };
  for (const [k, m] of Object.entries(errs)) { setFieldError(k, m); if (m) ok = false; }
  if (!ok) { const first = form.querySelector('[aria-invalid="true"]'); if (first) first.focus(); return null; }
  return { legal_name: name, state, website };
}
function formMessage(kind, text) {
  const box = $("#form-msg");
  if (!box) return;
  box.hidden = !text;
  box.className = `notice ${kind}`;
  box.innerHTML = text ? `${icon(kind === "err" ? "ph-warning-circle" : "ph-hourglass-medium")}<span>${esc(text)}</span>` : "";
}
async function startRun(payload, btn) {
  const buttons = [$("#go"), $("#sample")].filter(Boolean);
  buttons.forEach((b) => { b.disabled = true; });
  btn.setAttribute("aria-busy", "true");
  const label = btn.querySelector("span");
  const was = label.textContent;
  label.textContent = "Starting…";
  formMessage("", "");
  let res;
  try {
    res = await api("/api/runs", { method: "POST", body: JSON.stringify(payload) });
  } catch {
    res = null;
  }
  buttons.forEach((b) => { b.disabled = false; });
  btn.removeAttribute("aria-busy");
  label.textContent = was;
  if (!res) { formMessage("err", "Could not reach ClearToPay. Check your connection and try again."); return; }
  if (res.status === 202 && res.body && res.body.id) {
    startedHere.add(res.body.id);
    go(`/?run=${encodeURIComponent(res.body.id)}`);
    return;
  }
  if (res.status === 429) { formMessage("warn", detailOf(res.body, "Too many vendors waiting. Try again in a minute.")); return; }
  if (res.status === 422 && res.body && Array.isArray(res.body.detail)) {
    const map = { legal_name: "name", state: "state", website: "web" };
    for (const d of res.body.detail) {
      const field = map[(d.loc || []).slice(-1)[0]];
      if (field) setFieldError(field, cap(d.msg || "This value is not valid."));
    }
    formMessage("err", "Some fields need a fix before the checks can run.");
    return;
  }
  formMessage("err", detailOf(res.body, `The server could not start the checks (status ${res.status}). Try again.`));
}

/* ---------- Vendor file ---------- */
function stopRun() {
  if (!view) return;
  clearTimeout(view.timer);
  if (view.ctrl) view.ctrl.abort();
  view.dead = true;
  view = null;
}

function showRun(id) {
  view = { id, run: null, selected: null, userPicked: false, timer: 0, ctrl: null, failures: 0, gateSig: "", consoleSig: "", dead: false, firstPaint: true };
  document.title = "Vendor file · ClearToPay";
  app.innerHTML = `
  <section class="vendor" aria-busy="true" id="vendor">
    <h1><span class="sk" style="width:14ch;height:.8em"></span></h1>
    <div class="meta"><span class="sk" style="width:10ch"></span><span class="sk" style="width:18ch"></span><span class="sk" style="width:14ch"></span></div>
  </section>
  <section class="scene" aria-label="Checks and decision">
    <div class="belt" id="belt">
      <div class="belt-head" id="belt-head"><strong><span class="sk" style="width:24ch"></span></strong><span class="sk" style="width:16ch"></span></div>
      <div id="belt-note"></div>
      <div class="parcels" role="tablist" aria-label="Checks" id="parcels" style="--n:3">${[0, 1, 2].map(() => `
        <div class="parcel" aria-hidden="true"><span class="tag"><span class="sk" style="width:9ch"></span><span class="sk"></span><span class="sk" style="width:12ch"></span><span class="sk"></span></span>
        <span class="film empty"></span><span class="reading"><span class="sk" style="width:80%"></span></span></div>`).join("")}</div>
      <div class="rollers" aria-hidden="true"><span>${icon("ph-arrow-right")}Order of the run, left to right</span></div>
    </div>
    <aside class="gate" id="gate" data-decision="pending" aria-labelledby="decision">
      <div class="barrier" aria-hidden="true"></div>
      <div class="gate-state">${icon("ph-circle-notch")}Loading the vendor file</div>
      <h2 id="decision"><span class="sk"></span><span class="sk"></span></h2>
    </aside>
  </section>
  <section class="console" aria-label="Selected check">
    <div class="pane" id="evidence"><h3>${icon("ph-image-square")}Evidence</h3><span class="sk" style="width:100%;height:180px;display:block"></span></div>
    <div class="pane" id="contain"><h3>${icon("ph-cube-transparent")}What the microVM contained</h3><span class="sk" style="width:70%;height:2em;display:block"></span></div>
    <div class="pane"><h3>${icon("ph-clock-counter-clockwise")}Recent vendor files</h3><div id="recent"></div>${EVAL_BLOCK}</div>
  </section>`;
  loadRecent($("#recent"), id);
  poll();
}

async function poll() {
  const v = view;
  if (!v || v.dead) return;
  v.ctrl = new AbortController();
  let res;
  try {
    res = await api(`/api/runs/${encodeURIComponent(v.id)}`, { signal: v.ctrl.signal });
  } catch (err) {
    if (v.dead || (err && err.name === "AbortError")) return;
    res = null;
  }
  if (v.dead) return;
  if (res && res.status === 404) { notFound(v.id); return; }
  if (!res || !res.ok || !res.body) {
    v.failures += 1;
    if (!v.run) {
      if (v.failures >= 3) { loadFailed(res ? res.status : 0); return; }
    } else {
      $("#belt-note").innerHTML = `<div class="notice warn" style="margin-bottom:12px">${icon("ph-wifi-slash")}<span>Lost contact with the server. Retrying every 2 s; nothing on this page changed meanwhile.</span></div>`;
    }
    v.timer = setTimeout(poll, POLL_MS);
    return;
  }
  v.failures = 0;
  $("#belt-note").innerHTML = "";
  update(res.body);
  if (res.body.status !== "done") v.timer = setTimeout(poll, POLL_MS);
}

function notFound(id) {
  document.title = "Vendor file not found · ClearToPay";
  app.innerHTML = `<section class="page-msg rise">
    <h1>No vendor file with that id</h1>
    <p>The link points to <span class="mono">${esc(id)}</span>, which this server does not have. It may have been mistyped.</p>
    <div class="row-actions"><a class="btn btn-metal" href="/" data-nav>${icon("ph-scan")}Check a vendor</a></div></section>`;
}
function loadFailed(status) {
  app.innerHTML = `<section class="page-msg rise">
    <h1>The vendor file did not load</h1>
    <p>${status ? `The server answered with status ${status}.` : "The server could not be reached."} The checks keep running on the server even when this page cannot reach it.</p>
    <div class="row-actions"><button class="btn btn-metal" type="button" id="retry">${icon("ph-arrow-clockwise")}Try again</button>
    <a class="btn btn-ghost" href="/" data-nav>Back to check a vendor</a></div></section>`;
  const id = view.id;
  $("#retry").addEventListener("click", () => { stopRun(); showRun(id); });
}

/* ---------- Update cycle ---------- */
function update(run) {
  const v = view;
  const prev = v.run;
  v.run = run;
  const checks = Array.isArray(run.checks) ? run.checks : [];
  const pending = Array.isArray(run.pending) ? run.pending : [];

  // Announce newly finished checks and the decision.
  if (prev) {
    const before = new Set((prev.checks || []).map((c) => c.check));
    for (const c of checks) if (!before.has(c.check)) announce(`${NAMES[c.check] || c.check} finished: ${VERDICTS[viewVerdict(c)].label}.`);
    if (prev.status !== run.status && run.status !== "done") loadRecent($("#recent"), run.id);
    if (prev.status !== "done" && run.status === "done") {
      const d = DECISIONS[run.decision];
      announce(`Decision: ${d ? d.label : "none"}.`);
      if (startedHere.has(run.id)) play("sealed");
      loadRecent($("#recent"), run.id);
    }
  }

  // Default selection: follow the newest finished check while running; once done, the one that needs attention.
  if (!v.userPicked && checks.length) {
    if (run.status !== "done") v.selected = checks[checks.length - 1].check;
    else {
      const rank = { contained: 0, hit: 1, error: 2, review: 3, verified: 4, clear: 5 };
      v.selected = [...checks].sort((a, b) => rank[viewVerdict(a)] - rank[viewVerdict(b)])[0].check;
    }
  }

  renderVendor(run);
  renderBelt(run, checks, pending);
  renderGate(run, checks, pending);
  renderConsole(run, checks);
  if (v.firstPaint) {
    const box = $("#parcels");
    const sel = box.querySelector('[aria-selected="true"]');
    if (sel && box.scrollWidth > box.clientWidth) box.scrollLeft = sel.offsetLeft - 16;
  }
  v.firstPaint = false;
}

function renderVendor(run) {
  const v = run.vendor || {};
  document.title = `${v.legal_name || "Vendor file"} · ClearToPay`;
  const total = run.finished_at ? (new Date(run.finished_at) - new Date(run.requested_at)) / 1000 : null;
  const web = v.website
    ? `<span>${icon("ph-globe-simple")}<span class="mono">${esc(v.website)}</span><span class="tagline">opened as untrusted</span></span>`
    : `<span>${icon("ph-globe-simple")}No website given</span>`;
  const seal = run.status === "done" && run.manifest_sha256
    ? `<span title="Manifest SHA-256 ${esc(run.manifest_sha256)}">${icon("ph-seal-check")}File sealed, manifest SHA-256&nbsp;<span class="mono">${esc(shortHash(run.manifest_sha256))}</span></span>`
    : `<span>${icon("ph-seal")}Sealed when the last check finishes</span>`;
  const el = $("#vendor");
  el.removeAttribute("aria-busy");
  el.innerHTML = `<h1>${esc(v.legal_name)}</h1>
    <div class="meta">
      <span>${icon("ph-map-pin")}${esc(stateName(v.state))}</span>
      ${web}
      <span>${icon("ph-calendar-blank")}Requested ${esc(when(run.requested_at))}</span>
      ${total !== null && total >= 0 ? `<span>${icon("ph-timer")}${Math.round(total)} s from request to sealed file</span>` : ""}
      ${seal}
    </div>`;
}

function slots(checks) {
  const total = checks.reduce((s, c) => s + ((c.containment && c.containment.seconds) || 0), 0);
  let start = 0;
  const out = {};
  for (const c of checks) {
    const d = (c.containment && c.containment.seconds) || 0;
    out[c.check] = { start, dur: d, total };
    start += d;
  }
  return { out, total };
}

function renderBelt(run, checks, pending) {
  const v = view;
  const names = [...checks.map((c) => c.check), ...pending.filter((p) => !checks.some((c) => c.check === p))];
  const n = names.length;
  const done = checks.length;
  const { out: slot, total } = slots(checks);
  const head = $("#belt-head");
  const belt = $("#belt");
  belt.toggleAttribute("data-running", run.status !== "done");
  let status;
  if (run.status === "queued") status = `${icon("ph-hourglass-medium")}Waiting in line for a free microVM host`;
  else if (run.status === "running") status = `${icon("ph-circle-notch")}${done} of ${n} finished, now scanning ${esc(SHORT[pending[0]] || pending[0] || "")}`;
  else status = `${icon("ph-check-circle")}${done} of ${n} finished in ${secs(total)} of microVM time, run one after another`;
  head.innerHTML = `<strong>${n} ${n === 1 ? "check" : "checks"}, each in its own disposable microVM on Vultr</strong><span>${status}</span>`;
  if (run.error) {
    $("#belt-note").innerHTML = `<div class="notice err" style="margin-bottom:12px">${icon("ph-warning-octagon")}<span>The run stopped early: ${esc(run.error)}. Unfinished checks count as needing a human.</span></div>`;
  }

  const box = $("#parcels");
  if (v.firstPaint) box.innerHTML = "";
  box.style.setProperty("--n", Math.max(n, 1));
  names.forEach((name, i) => {
    const rec = checks.find((c) => c.check === name);
    const state = rec ? "done" : run.status === "running" && name === pending[0] ? "scanning" : "pending";
    const key = rec ? `${name}:${viewVerdict(rec)}:${rec.screenshot_sha256}` : `${name}:${state}`;
    let node = box.children[i];
    if (node && node.dataset.key === key) {
      if (rec) paintSlot(node, slot[name], total, rec);
      return;
    }
    const fresh = buildParcel(run, name, rec, state, i, n);
    if (!node) fresh.classList.add("enter");
    if (rec) fresh.classList.add("scanned");
    fresh.style.setProperty("--d", v.firstPaint ? `${i * 260}ms` : "0ms");
    if (node) box.replaceChild(fresh, node); else box.appendChild(fresh);
  });
  while (box.children.length > n) box.lastElementChild.remove();
  // Every finished slot moves when the total grows.
  [...box.children].forEach((node) => {
    const rec = checks.find((c) => c.check === node.dataset.check);
    if (rec) paintSlot(node, slot[rec.check], total, rec);
  });
  syncSelection();
}

function paintSlot(node, s, total, rec) {
  const bar = $(".slot-bar", node);
  const txt = $(".slot-txt", node);
  if (!bar || !s) return;
  const t = total || 1;
  bar.style.left = `${(s.start / t) * 100}%`;
  bar.style.width = `${(s.dur / t) * 100}%`;
  txt.textContent = `+${s.start.toFixed(1)} s to +${(s.start + s.dur).toFixed(1)} s`;
}

function buildParcel(run, name, rec, state, i, n) {
  const el = document.createElement(rec ? "button" : "div");
  el.className = "parcel";
  el.dataset.check = name;
  el.dataset.state = state;
  el.dataset.key = rec ? `${name}:${viewVerdict(rec)}:${rec.screenshot_sha256}` : `${name}:${state}`;
  if (!rec) {
    const scanning = state === "scanning";
    el.setAttribute("aria-label", `${NAMES[name] || name}: ${scanning ? "scanning now" : "waiting"}`);
    el.innerHTML = `
      <span class="tag"><span class="src">${esc(SHORT[name] || name)}</span>
        <span class="verdict ${scanning ? "v-scanning" : "v-pending"}">${icon(scanning ? "ph-circle-notch" : "ph-hourglass-medium")}${scanning ? "Scanning" : "Queued"}</span>
        <span class="hash"><span class="sk" style="width:13ch"></span></span><span class="secs"><span class="sk" style="width:4ch"></span></span></span>
      <span class="film empty"><span class="wait">${icon(scanning ? "ph-cube-transparent" : "ph-package")}${scanning ? "microVM running" : "Waiting for its microVM"}</span><span class="sweep"></span></span>
      <span class="reading"><span class="sk" style="width:75%"></span></span>
      <span class="slot"><span class="slot-track"></span><span class="slot-txt">${scanning ? "Running now" : "Not started"}</span></span>`;
    return el;
  }
  const vv = viewVerdict(rec);
  const V = VERDICTS[vv];
  const sec = rec.containment && rec.containment.seconds;
  el.type = "button";
  el.setAttribute("role", "tab");
  el.setAttribute("aria-controls", "evidence");
  el.id = `tab-${name}`;
  el.innerHTML = `
    <span class="tag">
      <span class="src">${esc(SHORT[name] || name)}</span>
      <span class="verdict v-${vv}">${icon(V.icon)}${V.label}</span>
      <span class="hash mono" title="Screenshot SHA-256 ${esc(rec.screenshot_sha256)}">${esc(shortHash(rec.screenshot_sha256)) || "no screenshot hash"}</span>
      <span class="secs">${sec != null ? secs(sec) : "–"}</span>
    </span>
    <span class="film" data-shot="loading">
      <img class="illus" src="${ILLUS[name] || ILLUS.ofac}" alt="" width="800" height="537">
      <span class="xray"><img class="glow" alt="" aria-hidden="true" width="1280" height="900" decoding="async"><img class="base" alt="X-ray view of the ${esc(NAMES[name] || name)} capture, check ${i + 1} of ${n}: ${esc(V.label.toLowerCase())}" width="1280" height="900" decoding="async"></span>
      <span class="illus-note">${icon("ph-image")}<span>Illustration while the capture loads</span></span>
      <span class="dim"></span><span class="sweep"></span>
      ${rec.injection ? `<span class="box"><span class="box-label">Hidden instruction</span></span>` : ""}
    </span>
    <span class="reading">${esc(cap(rec.reason || rec.error || ""))}</span>
    <span class="slot"><span class="slot-track"><span class="slot-bar v-${vv}"></span></span><span class="slot-txt"></span></span>`;
  const film = $(".film", el);
  const img = $(".xray img.base", el);
  $(".xray img.glow", el).src = shotUrl(run.id, name);
  const ok = () => { film.dataset.shot = "ready"; };
  const fail = () => {
    film.dataset.shot = "failed";
    $(".illus-note span", el).textContent = "Illustration. Capture not available";
  };
  img.addEventListener("load", ok, { once: true });
  img.addEventListener("error", fail, { once: true });
  img.src = shotUrl(run.id, name);
  el.addEventListener("click", () => select(name, true));
  return el;
}

function syncSelection() {
  const box = $("#parcels");
  [...box.children].forEach((node) => {
    if (node.dataset.state !== "done") return;
    const on = node.dataset.check === view.selected;
    node.setAttribute("aria-selected", String(on));
    node.tabIndex = on ? 0 : -1;
  });
}
function select(name, byUser) {
  if (!view || !view.run) return;
  if (byUser) { view.userPicked = true; if (view.selected !== name) play("select"); }
  view.selected = name;
  syncSelection();
  renderConsole(view.run, view.run.checks || []);
}
document.addEventListener("keydown", (e) => {
  const cur = e.target.closest && e.target.closest('.parcel[role="tab"]');
  if (!cur || !["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
  const tabs = [...document.querySelectorAll('.parcel[role="tab"]')];
  let i = tabs.indexOf(cur);
  if (e.key === "ArrowRight") i = (i + 1) % tabs.length;
  if (e.key === "ArrowLeft") i = (i - 1 + tabs.length) % tabs.length;
  if (e.key === "Home") i = 0;
  if (e.key === "End") i = tabs.length - 1;
  e.preventDefault();
  select(tabs[i].dataset.check, true);
  tabs[i].focus();
  tabs[i].scrollIntoView({ block: "nearest", inline: "nearest" });
});

/* ---------- Gate ---------- */
function renderGate(run, checks, pending) {
  const sig = `${run.status}|${run.decision}|${JSON.stringify(run.approval)}|${checks.length}`;
  if (sig === view.gateSig) return;
  const animate = view.gateSig.split("|")[0] !== "done" && run.status === "done";
  view.gateSig = sig;
  const gate = $("#gate");
  const done = run.status === "done";
  const d = done ? DECISIONS[run.decision] : null;
  gate.dataset.decision = done && d ? run.decision : "pending";
  let reasons = "";
  if (done) {
    const flagged = checks.filter((c) => !["clear", "verified"].includes(viewVerdict(c)));
    const items = flagged.map((c) => {
      const vv = viewVerdict(c);
      return `<li>${icon(VERDICTS[vv].icon).replace('class="ph-light', `class="ph-light v-${vv}`)}<span>${esc(NAMES[c.check] || c.check)}: ${esc(c.reason || c.error || VERDICTS[vv].label)}<small>${esc(WHY[vv] || "")}</small></span></li>`;
    });
    if (pending.length) items.push(`<li>${icon("ph-warning-octagon").replace('class="ph-light', 'class="ph-light v-error')}<span>${pending.length} ${pending.length === 1 ? "check" : "checks"} did not run: ${esc(pending.map((p) => NAMES[p] || p).join(", "))}<small>An unfinished file can never be clear to pay.</small></span></li>`);
    if (!items.length) {
      checks.forEach((c) => items.push(`<li>${icon(VERDICTS[viewVerdict(c)].icon).replace('class="ph-light', `class="ph-light v-${viewVerdict(c)}`)}<span>${esc(NAMES[c.check] || c.check)}: ${esc(c.reason)}</span></li>`));
    }
    reasons = `<ul class="reasons ${animate ? "reveal" : ""}">${items.join("")}</ul>`;
  }
  const canApprove = done && run.decision === "clear_to_pay" && !run.approval;
  let actions;
  if (run.approval) {
    actions = `<div class="approved">${icon("ph-check-circle")}<span>Approved by ${esc(run.approval.by)}, ${esc(when(run.approval.at))}.<small>Payment release is simulated. No money moved.</small></span></div>`;
  } else {
    const why = !done
      ? "Available when every check is clear. Payment release is simulated."
      : canApprove
        ? "Payment release is simulated. No money moves."
        : "Only a file where every check is clear can be approved here. Payment release is simulated.";
    actions = `<form class="actions-form" id="approve-form" novalidate style="display:flex;flex-direction:column;gap:8px">
        <div class="field"><label for="f-approver">Your name</label>
          <input id="f-approver" name="approver" autocomplete="name" minlength="2" maxlength="80" ${canApprove ? "" : "disabled"} aria-describedby="e-approver why"></div>
        <span class="err-msg" id="e-approver" hidden style="font-size:12.5px;color:var(--alarm-hi)"></span>
        <button class="btn ${canApprove ? "btn-primary" : "btn-ghost"}" type="submit" id="approve" ${canApprove ? "" : "disabled"}>${icon(canApprove ? "ph-currency-circle-dollar" : "ph-lock-simple")}<span>Approve vendor and release payment</span></button>
        <div id="approve-msg"></div>
        <p class="why" id="why">${icon("ph-info")}${esc(why)}</p></form>`;
  }
  const stateLine = done && d
    ? `${icon(d.gateIcon)}${esc(run.approval ? "Approved by a person, payment simulated" : d.gate)}`
    : `${icon("ph-circle-notch")}${run.status === "queued" ? "Queued, the gate stays closed" : "Checks running, the gate stays closed"}`;
  gate.innerHTML = `
    <div class="barrier" aria-hidden="true"></div>
    <div class="gate-state ${animate ? "reveal" : ""}">${stateLine}</div>
    <h2 id="decision" class="${animate ? "reveal" : ""}">${done && d ? esc(d.label) : `<span class="sk"></span><span class="sk"></span><span class="sr">Decision pending until every check finishes</span>`}</h2>
    ${reasons}
    <div class="actions">${actions}</div>`;
  const form = $("#approve-form");
  if (form && canApprove) form.addEventListener("submit", (e) => { e.preventDefault(); approve(run.id); });
}

async function approve(id) {
  const input = $("#f-approver");
  const err = $("#e-approver");
  const name = input.value.trim();
  if (name.length < 2 || name.length > 80) {
    input.setAttribute("aria-invalid", "true");
    err.hidden = false;
    err.textContent = "Enter your name, 2 to 80 characters, so the file records who approved.";
    input.focus();
    return;
  }
  input.setAttribute("aria-invalid", "false");
  err.hidden = true;
  const btn = $("#approve");
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  let res;
  try { res = await api(`/api/runs/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ approver: name }) }); } catch { res = null; }
  if (!view || view.id !== id) return;
  if (res && res.ok && res.body) {
    play("approved");
    announce(`Approved by ${name}. Payment release simulated.`);
    update(res.body);
    loadRecent($("#recent"), id);
    return;
  }
  btn.disabled = false;
  btn.removeAttribute("aria-busy");
  const msg = !res
    ? "Could not reach ClearToPay. Nothing was approved. Try again."
    : res.status === 409
      ? detailOf(res.body, "This file cannot be approved.")
      : detailOf(res.body, `Approval failed (status ${res.status}). Nothing was approved.`);
  $("#approve-msg").innerHTML = `<div class="notice err">${icon("ph-warning-circle")}<span>${esc(msg)}</span></div>`;
}

/* ---------- Console: evidence and containment ---------- */
function renderConsole(run, checks) {
  const rec = checks.find((c) => c.check === view.selected);
  const sig = rec ? `${rec.check}:${rec.screenshot_sha256}:${viewVerdict(rec)}:${checks.length}` : `none:${run.status}`;
  if (sig === view.consoleSig) return;
  view.consoleSig = sig;
  const ev = $("#evidence");
  const co = $("#contain");
  ev.removeAttribute("aria-labelledby");
  if (!rec) {
    const msg = run.status === "done"
      ? "No check finished in this file, so there is no evidence to show."
      : "The evidence for each check appears here as soon as its microVM finishes.";
    ev.innerHTML = `<h3>${icon("ph-image-square")}Evidence</h3><p class="none">${esc(msg)}</p>`;
    co.innerHTML = `<h3>${icon("ph-cube-transparent")}What the microVM contained</h3><p class="none">Limits, allowed hosts and proof of destruction appear with each finished check.</p>`;
    return;
  }
  ev.setAttribute("aria-labelledby", `tab-${rec.check}`);
  ev.innerHTML = evidenceHtml(run, rec, checks);
  co.innerHTML = containHtml(rec);
  const img = $(".shot-img", ev);
  if (img) {
    img.addEventListener("error", () => {
      const a = img.closest(".shot");
      const div = document.createElement("div");
      div.className = "shot";
      div.innerHTML = `<div class="shot-bar"><i></i><i></i><i></i><span>${esc(rec.url)}</span></div><p class="shot-missing">${icon("ph-image-broken")}The capture for this check is not available on the server.</p>`;
      a.replaceWith(div);
    }, { once: true });
  }
}

function recordMeta(r) {
  if (r.score) return `score ${r.score}${r.list ? `, ${r.list}` : ""}`;
  if (r.status) return r.status;
  if (r.list) return r.list;
  return "";
}
function norm(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim(); }

function evidenceHtml(run, rec, checks) {
  const i = checks.indexOf(rec);
  const n = checks.length + (run.pending || []).length;
  const vv = viewVerdict(rec);
  const V = VERDICTS[vv];
  const url = shotUrl(run.id, rec.check);
  const vendorName = norm(run.vendor && run.vendor.legal_name);
  const records = Array.isArray(rec.records) ? rec.records : [];
  const shown = records.slice(0, 5);
  const recordsHtml = records.length
    ? `<ul class="records">${shown.map((r) => `<li class="${norm(r.name) === vendorName ? "match" : ""}"><span class="r-name">${esc(r.name)}</span><span class="r-meta">${esc(recordMeta(r))}</span></li>`).join("")}
       ${records.length > shown.length ? `<li class="more">and ${records.length - shown.length} more in the capture</li>` : ""}</ul>`
    : `<p class="none">${rec.result_count ? "This check does not list names. See the capture." : "No names on the page."}</p>`;
  const inj = rec.injection
    ? `<div class="hidden-text" role="note"><b>${icon("ph-shield-warning")}Hidden instruction found on the page, shown as data</b>“${esc(rec.injection.text)}”
       <span style="display:block;margin-top:8px;font-family:var(--sans);font-size:12.5px">${rec.injection.followed === false ? "The agent did not follow it." : "The record does not confirm the agent ignored it."}${Array.isArray(rec.injection.found_by) && rec.injection.found_by.length ? ` Found by ${esc(rec.injection.found_by.join(" and "))}.` : ""}</span></div>`
    : "";
  return `
    <h3>${icon("ph-image-square")}<span>Evidence, check ${i + 1} of ${n}: ${esc(NAMES[rec.check] || rec.check)}</span></h3>
    <a class="shot" href="${url}" target="_blank" rel="noopener">
      <div class="shot-bar"><i></i><i></i><i></i><span>${esc(rec.url)}</span></div>
      <img class="shot-img" src="${url}" alt="Screenshot of ${esc(rec.url)} as the browser in the microVM saw it" width="1280" height="900" loading="lazy">
      <span class="shot-open">${icon("ph-arrows-out-simple")}Open full size</span>
    </a>
    ${inj}
    <dl class="facts">
      <dt>Verdict</dt><dd><span class="verdict v-${vv}">${icon(V.icon)}${V.label}</span></dd>
      <dt>Reason</dt><dd>${esc(cap(rec.reason)) || "–"}</dd>
      <dt>Searched for</dt><dd>${esc(rec.query)}</dd>
      <dt>Results</dt><dd>${rec.result_count == null ? "Not counted" : `${rec.result_count} ${rec.result_count === 1 ? "record" : "records"} on the page`}</dd>
      <dt>Captured</dt><dd>${esc(when(rec.captured_at, fmtTime))}${rec.containment && rec.containment.seconds != null ? `, in ${secs(rec.containment.seconds)}` : ""}</dd>
      <dt>Screenshot SHA-256</dt><dd class="mono">${esc(rec.screenshot_sha256) || "–"}</dd>
      <dt>Page text SHA-256</dt><dd class="mono">${esc(rec.page_text_sha256) || "–"}</dd>
      <dt>URL</dt><dd class="mono"><a href="${esc(rec.url)}" target="_blank" rel="noopener noreferrer">${esc(rec.url)}</a></dd>
      ${rec.error ? `<dt>Error</dt><dd>${esc(rec.error)}</dd>` : ""}
    </dl>
    <h4>${icon("ph-list-bullets")}Names on the page</h4>
    ${recordsHtml}
    <h4>${icon("ph-eye")}Second reading of the screenshot</h4>
    ${verifierHtml(rec.verifier)}`;
}

function verifierHtml(vf) {
  if (!vf) return `<p class="none">No second reading for this check.</p>`;
  if (vf.skipped) return `<p class="none">Second reading skipped for this check.</p>`;
  const agrees = vf.agrees
    ? `<span class="agree v-clear">${icon("ph-check-circle")}Agrees with the page parser</span>`
    : `<span class="agree v-review">${icon("ph-warning")}Reads it differently, sent to review</span>`;
  let note = String(vf.note || "").trim();
  if (note && !/[.!?)"”]$/.test(note)) note += "…";
  const count = vf.result_count_seen == null ? "did not count results" : `counted ${vf.result_count_seen} ${vf.result_count_seen === 1 ? "result" : "results"}`;
  return `<div class="second">
    <div class="second-head"><span class="mono">${esc(vf.model)}</span><span>${vf.seconds != null ? `in ${secs(vf.seconds)}` : ""}, ${esc(count)}</span>${agrees}</div>
    ${note ? `<p>${esc(note)}</p>` : `<p class="none">No note.</p>`}</div>`;
}

function containHtml(rec) {
  const c = rec.containment || {};
  const L = c.limits || {};
  const mem = L.memory_mib != null ? (L.memory_mib % 1024 === 0 ? [L.memory_mib / 1024, "GiB"] : [L.memory_mib, "MiB"]) : null;
  const hostList = (arr, cls, emptyText) => (arr && arr.length
    ? `<span class="hosts">${arr.map((h) => `<span class="host ${cls}">${esc(h)}</span>`).join("")}</span>`
    : `<span class="none">${emptyText}</span>`);
  const env = Array.isArray(c.env_names_in_sandbox) ? c.env_names_in_sandbox : [];
  const looksSecret = env.filter((e) => /KEY|TOKEN|SECRET|PASSW/i.test(e));
  const envNote = env.length
    ? looksSecret.length ? `Names that look like secrets: ${looksSecret.join(", ")}.` : "Names only. None of them is a key, token or password."
    : "";
  const limit = (val, unit, label) => (val == null ? "" : `<div class="limit"><b>${esc(val)}<small>${unit}</small></b><span>${label}</span></div>`);
  return `
    <h3>${icon("ph-cube-transparent")}What the microVM contained</h3>
    <div class="limits">
      ${limit(L.cpus, "", L.cpus === 1 ? "vCPU" : "vCPUs")}
      ${mem ? limit(mem[0], ` ${mem[1]}`, "memory") : ""}
      ${limit(L.max_seconds, " s", "max run time")}
      ${limit(c.seconds != null ? Number(c.seconds).toFixed(1) : null, " s", "used")}
    </div>
    <dl class="facts">
      <dt>Sandbox</dt><dd class="mono">${esc(c.sandbox) || "–"}</dd>
      <dt>Allowed hosts</dt><dd>${hostList(c.allowed_hosts, "ok", "None")}</dd>
      <dt>Blocked hosts</dt><dd>${hostList(c.blocked_hosts, "no", "None attempted")}</dd>
      <dt>Environment</dt><dd>${env.length ? `<span class="env">${env.map(esc).join(", ")}</span><br><span class="none">${esc(envNote)}</span>` : `<span class="none">Not recorded</span>`}</dd>
    </dl>
    ${rec.injection ? `<div class="contained">${icon("ph-shield-warning")}<span>The page tried to give the agent instructions. They were kept as page text${rec.injection.followed === false ? " and not followed" : ""}.${c.blocked_hosts && c.blocked_hosts.length ? ` Requests to ${c.blocked_hosts.map((h) => `<span class="mono">${esc(h)}</span>`).join(", ")} were blocked.` : ""}${rec.injection.why_not ? `<small style="display:block;margin-top:4px;color:var(--ink-2)">${esc(rec.injection.why_not)}</small>` : ""}</span></div>` : ""}
    ${c.destroyed
      ? `<div class="destroyed">${icon("ph-trash-simple")}Destroyed after the check, confirmed afterwards</div>`
      : `<div class="destroyed no">${icon("ph-warning-octagon")}Destruction not confirmed for this microVM</div>`}`;
}

route();

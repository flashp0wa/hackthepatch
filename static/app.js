// hackthepatch UI: one page, four features, plain JS against the FastAPI routes.
const $ = (sel) => document.querySelector(sel);
const api = async (path, opts = {}) => {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const ROLE_LABELS = { investor: "Investor", founder: "Founder", hiring: "Hiring", open_to_work: "Open to work", connecting: "Building connections" };
const roleBadge = (p) => p.role && p.role !== "connecting" ? `<span class="role role-${esc(p.role)}">${esc(ROLE_LABELS[p.role] || p.role)}</span>` : "";
const tags = (list, cls = "") => `<div class="tags">${(list || []).map((t) => `<span class="tag ${cls}">${esc(t)}</span>`).join("")}</div>`;
const toast = (msg, ms = 3500) => { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), ms); };

const state = { attendees: [], selected: null, network: null, me: null };

// ---- tabs ----------------------------------------------------------------
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "room") loadRoomGraph();
  if (name === "ask") loadQuestions();
  if (name === "matches" && state.selected) loadMatches(state.selected);
  if (name === "me") loadMe();
  if (name === "event") loadEvent();
}

// ---- event page: agenda + Interests ---------------------------------------------
function sessionCard(s, rank) {
  const cls = rank == null ? "" : rank < 3 ? "best" : s.score < 25 ? "dim" : "";
  return `<div class="card session ${cls}" id="session-${esc(s.id)}">
    ${rank != null ? `<span class="score">${s.score}</span>` : ""}
    <p class="meta">${esc(s.time)} · ${esc(s.track)}</p><h4>${esc(s.title)}</h4><p class="headline">${esc(s.speaker)}</p>
    <p>${esc(s.abstract)}</p>
    ${rank != null ? `<div class="fit">${esc(s.reason)}</div>` : ""}</div>`;
}
async function loadEvent() {
  const ev = await api("/api/event");
  $("#event-name").textContent = ev.name;
  $("#agenda").innerHTML = ev.sessions.map((s) => sessionCard(s, null)).join("");
  $("#interests-note").textContent = "";
}
$("#btn-interests").addEventListener("click", async () => {
  if (!state.me) { toast("Sign in with LinkedIn first, so there is a profile to match."); showTab("me"); return; }
  const btn = $("#btn-interests"); btn.disabled = true; btn.textContent = "Matching…";
  try {
    const r = await api("/api/event/interests", { method: "POST" });
    $("#agenda").innerHTML = r.sessions.map((s, i) => sessionCard(s, i)).join("");
    const note = $("#interests-note");
    note.textContent = r.source === "llm" ? `Ranked by the LLM for ${r.person.name}: best fit first.`
      : `LLM unavailable (${r.source.replace(/^fallback: /, "")}); showing keyword overlap for ${r.person.name} instead.`;
    note.classList.toggle("warn", r.source !== "llm");
  } catch (err) { toast(err.message, 8000); } finally { btn.disabled = false; btn.textContent = "Interests"; }
});

// ---- attendees -----------------------------------------------------------
async function loadAttendees() {
  state.attendees = await api("/api/attendees");
  $("#attendee-count").textContent = state.attendees.length;
  $("#attendee-list").innerHTML = state.attendees.map((p) => `
    <li data-id="${esc(p.id)}" class="${p.id === state.selected ? "selected" : ""}">
      <span>${esc(p.name)} ${roleBadge(p)}<span class="sub">${esc(p.headline)}</span></span>
    </li>`).join("");
  document.querySelectorAll("#attendee-list li").forEach((li) => li.addEventListener("click", () => selectPerson(li.dataset.id)));
  $("#ask-as").innerHTML = `<option value="">Asking as: anonymous</option>` +
    state.attendees.map((p) => `<option value="${esc(p.id)}" ${state.me && state.me.id === p.id ? "selected" : ""}>Asking as: ${esc(p.name)}</option>`).join("");
}

// ---- my profile: LinkedIn login, auto-populate, active project -------------------
async function loadMe() {
  const data = await api("/api/me");
  state.me = data.user;
  renderAuthBox(data);
  $("#me-signed-out").classList.toggle("hidden", !!data.user);
  $("#me-signed-in").classList.toggle("hidden", !data.user);
  $("#form-dev-login").classList.toggle("hidden", !data.dev_login);
  $("#btn-login-big").classList.toggle("hidden", !data.oidc_enabled);
  if (!data.oidc_enabled && !data.dev_login) $("#me-signed-out p").textContent = "LinkedIn login is not configured yet (LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET in .env).";
  if (!data.user) return;
  const p = data.user;
  renderMeCard(p);
  if (data.job && !["done", "failed"].includes(data.job.status)) setTimeout(loadMe, 4000);
  if (p.project) {
    $("#project-text").value = p.project.description;
    $("#project-updated").textContent = `analysed ${new Date(p.project.updated_at * 1000).toLocaleTimeString()}`;
    renderProject(p.project, await api("/api/me/connections"));
  } else {
    $("#project-result").classList.add("hidden");
  }
}

function renderMeCard(p) {
  $("#me-card").innerHTML = `${p.picture ? `<img src="${esc(p.picture)}" alt="">` : ""}<h4>${esc(p.name)} ${roleBadge(p)}</h4>
    <p class="headline">${esc(p.headline || "No headline yet: press Edit profile and describe yourself.")}</p>
    ${p.statement ? `<p class="statement">${esc(p.statement)}</p>` : ""}
    ${p.summary ? `<p>${esc(p.summary)}</p>` : ""}${p.building ? `<p><b>Building:</b> ${esc(p.building)}</p>` : ""}
    ${p.email ? `<p class="hint">${esc(p.email)}</p>` : ""}
    <div class="label">Technologies</div>${tags(p.technologies)}
    <div class="label">Interests</div>${tags(p.interests, "link")}
    <div class="label">Can offer</div>${tags(p.can_offer, "fill")}
    <div class="label">Looking for</div>${tags(p.looking_for, "need")}
    <div class="row" style="margin-top:10px"><button type="button" id="me-edit-btn" class="secondary">Edit profile</button></div>`;
  $("#me-edit-btn").addEventListener("click", () => openMeEditor(p));
}

// Edit form: text fields plus tag lists kept in local state; one PUT /api/me/profile on Save.
const meDraft = {};
function openMeEditor(p) {
  const form = $("#me-edit");
  ["name", "headline", "summary", "building", "url", "statement"].forEach((f) => { form.elements[f].value = p[f] || ""; });
  form.elements.role.value = p.role || "connecting";
  ["technologies", "interests", "can_offer", "looking_for"].forEach((f) => { meDraft[f] = [...p[f]]; renderDraftTags(f); });
  $("#me-card").classList.add("hidden"); form.classList.remove("hidden");
}
function renderDraftTags(field) {
  const box = $(`#me-edit .tags.editable[data-field="${field}"]`);
  const cls = box.dataset.cls;
  box.innerHTML = meDraft[field].map((t) => `<span class="tag ${cls}">${esc(t)}<button type="button" class="x" data-tag="${esc(t)}" title="remove">×</button></span>`).join("")
    + `<input class="tag-input" placeholder="add…">`;
  box.querySelectorAll(".x").forEach((b) => b.addEventListener("click", () => { meDraft[field] = meDraft[field].filter((t) => t !== b.dataset.tag); renderDraftTags(field); }));
  const input = box.querySelector(".tag-input");
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== ",") return;
    e.preventDefault();
    input.value.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean).forEach((t) => { if (!meDraft[field].includes(t)) meDraft[field].push(t); });
    renderDraftTags(field); $(`#me-edit .tags.editable[data-field="${field}"] .tag-input`).focus();
  });
}
$("#me-edit").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target; const btn = form.querySelector("button[type=submit]"); btn.disabled = true;
  const body = { ...meDraft };
  ["name", "headline", "summary", "building", "url", "statement", "role"].forEach((f) => { body[f] = form.elements[f].value; });
  try {
    state.me = await api("/api/me/profile", { method: "PUT", body: JSON.stringify(body) });
    form.classList.add("hidden"); $("#me-card").classList.remove("hidden");
    toast("Profile saved."); await loadAttendees(); loadMe();
  } catch (err) { toast(err.message, 8000); } finally { btn.disabled = false; }
});
$("#me-cancel").addEventListener("click", () => { $("#me-edit").classList.add("hidden"); $("#me-card").classList.remove("hidden"); });

function renderAuthBox(data) {
  const box = $("#auth-box");
  if (data.user) {
    box.innerHTML = `${data.user.picture ? `<img src="${esc(data.user.picture)}" alt="">` : ""}<span class="who">${esc(data.user.name)}<small>signed in</small></span><button id="btn-logout" class="secondary">Sign out</button>`;
    $("#btn-logout").addEventListener("click", async () => { await api("/auth/logout", { method: "POST" }); state.me = null; loadMe(); loadAttendees(); });
  } else if (data.oidc_enabled) {
    box.innerHTML = `<a class="button" href="/auth/login">Sign in with LinkedIn</a>`;
  } else {
    box.innerHTML = `<span class="hint">LinkedIn login not configured</span>`;
  }
}

function renderProject(project, connections) {
  $("#project-result").classList.remove("hidden");
  $("#pain-points").innerHTML = project.pain_points.map((x) => `<li>${esc(x)}</li>`).join("") || "<li>None found.</li>";
  $("#project-needs").innerHTML = tags(project.needs, "need") + (project.domains.length ? `<div class="label">Domains</div>${tags(project.domains)}` : "");
  $("#connection-ideas").innerHTML = project.connection_ideas.map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>";
  $("#connections").innerHTML = connections.length ? connections.map((c) => `
    <div class="card"><span class="score">${c.score}</span><h4>${esc(c.person.name)}</h4><p class="headline">${esc(c.person.headline)}</p>
      ${c.covers.length ? `<div class="label">Covers</div>${tags(c.covers, "fill")}` : ""}
      ${c.shared_domains.length ? `<div class="label">Same domain</div>${tags(c.shared_domains, "link")}` : ""}
    </div>`).join("") : `<div class="card muted">Nobody in the room covers these needs yet.</div>`;
}

$("#form-dev-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await api("/auth/dev-login", { method: "POST", body: JSON.stringify({ name: $("#dev-name").value }) }); await loadAttendees(); loadMe(); }
  catch (err) { toast(err.message); }
});
$("#form-project").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button"); btn.disabled = true;
  try {
    const r = await api("/api/me/project", { method: "PUT", body: JSON.stringify({ description: $("#project-text").value }) });
    renderProject(r.project, r.connections); $("#project-updated").textContent = "analysed just now"; await loadAttendees();
  } catch (err) { toast(err.message, 8000); } finally { btn.disabled = false; }
});

function selectPerson(id) {
  state.selected = id;
  document.querySelectorAll("#attendee-list li").forEach((li) => li.classList.toggle("selected", li.dataset.id === id));
  showTab("matches");
}

$("#form-text").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button"); btn.disabled = true;
  try {
    const p = await api("/api/attendees/text", { method: "POST", body: JSON.stringify({ name: $("#text-name").value, text: $("#text-about").value }) });
    toast(`${p.name} added.`); e.target.reset(); await loadAttendees(); selectPerson(p.id);
  } catch (err) { toast(err.message, 8000); } finally { btn.disabled = false; }
});

$("#btn-reset").addEventListener("click", async () => {
  if (!confirm("Remove every attendee and question?")) return;
  await api("/api/attendees", { method: "DELETE" }); state.selected = null;
  await loadAttendees(); loadRoomGraph(); $("#match-list").innerHTML = ""; $("#inbox").innerHTML = ""; $("#person-card").textContent = "No attendee selected.";
});

// ---- feature 1: complementary matching ------------------------------------
async function loadMatches(id) {
  const data = await api(`/api/matches/${id}`);
  const p = data.person;
  $("#person-card").className = "card";
  $("#person-card").innerHTML = `<h4>${esc(p.name)} ${roleBadge(p)}</h4><p class="headline">${esc(p.headline)}</p>
    ${p.statement ? `<p class="statement">${esc(p.statement)}</p>` : ""}
    ${p.building ? `<p>${esc(p.building)}</p>` : ""}
    <div class="label">Can offer</div>${tags(p.can_offer, "fill")}
    <div class="label">Looking for</div>${tags(p.looking_for, "need")}`;
  $("#match-list").innerHTML = data.matches.length ? data.matches.map((m) => `
    <div class="card"><span class="score">${m.score}</span><h4>${esc(m.person.name)} ${roleBadge(m.person)}</h4><p class="headline">${esc(m.person.headline)}</p>
      ${m.pair ? `<p class="hint">${esc(m.pair)}</p>` : ""}${m.person.statement ? `<p class="statement">${esc(m.person.statement)}</p>` : ""}
      ${m.fills.length ? `<div class="label">Fills your gaps</div>${tags(m.fills, "fill")}` : ""}
      ${m.they_need.length ? `<div class="label">Needs what you have</div>${tags(m.they_need, "need")}` : ""}
      ${m.overlap.length ? `<div class="label">Overlap (not what you need more of)</div>${tags(m.overlap)}` : ""}
    </div>`).join("") : `<div class="card muted">No complementary match yet: nobody in the room covers what this person is looking for.</div>`;
  const inbox = await api(`/api/inbox/${id}`);
  $("#inbox").innerHTML = inbox.length ? inbox.map(questionCard).join("") : `<div class="card muted">No questions routed here yet.</div>`;
}

// ---- feature 2: ask the room --------------------------------------------------
function questionCard(q) {
  const asker = state.attendees.find((p) => p.id === q.asker_id);
  return `<div class="card question"><h4>“${esc(q.text)}”</h4><p class="headline">asked by ${esc(asker ? asker.name : "anonymous")}</p>
    ${q.routed_to.map((r) => `<span class="pick"><b>${esc(r.name)}</b><span class="why">${esc(r.reason)}</span>${r.hits && r.hits.length ? tags(r.hits, "fill") : ""}</span>`).join("")}</div>`;
}
async function loadQuestions() {
  const qs = await api("/api/questions");
  $("#question-feed").innerHTML = qs.length ? qs.map(questionCard).join("") : `<div class="card muted">No questions yet. Ask one.</div>`;
}
$("#form-ask").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button"); btn.disabled = true;
  try {
    const q = await api("/api/questions", { method: "POST", body: JSON.stringify({ text: $("#ask-text").value, asker_id: $("#ask-as").value }) });
    $("#ask-text").value = ""; toast(`Routed to ${q.routed_to.map((r) => r.name).join(", ")}.`); await loadQuestions();
  } catch (err) { toast(err.message, 8000); } finally { btn.disabled = false; }
});

// ---- feature 3: live room graph -----------------------------------------------
const PALETTE = ["#7cc4ff", "#ffb86b", "#9be7b8", "#d9b8ff", "#ff8fab", "#ffe66d", "#8be9fd", "#f1a3ff"];
async function loadRoomGraph() {
  const g = await api("/api/room-graph");
  const bridges = new Set(g.bridges);
  const nodes = g.nodes.map((n) => ({
    id: n.id, label: n.name, title: `${n.name}\n${n.headline}\ncluster ${n.cluster + 1} · touches ${n.other_clusters} other cluster(s)`,
    color: { background: PALETTE[n.cluster % PALETTE.length], border: bridges.has(n.id) ? "#ffffff" : PALETTE[n.cluster % PALETTE.length] },
    borderWidth: bridges.has(n.id) ? 4 : 1, size: bridges.has(n.id) ? 34 : 20, font: { color: "#e8eaf0", size: bridges.has(n.id) ? 18 : 14 },
  }));
  const edges = g.edges.map((e) => ({ from: e.from, to: e.to, value: e.weight, title: e.shared.join(", "), color: { color: "#3a4052", opacity: 0.7 } }));
  const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
  const options = { nodes: { shape: "dot" }, edges: { smooth: false, scaling: { min: 1, max: 6 } },
    physics: { barnesHut: { gravitationalConstant: -6000, springLength: 140 }, stabilization: { iterations: 200 } }, interaction: { hover: true } };
  if (state.network) state.network.setData(data); else {
    state.network = new vis.Network($("#graph"), data, options);
    state.network.on("click", (params) => { if (params.nodes.length) selectPerson(params.nodes[0]); });
  }
  const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
  $("#bridges").innerHTML = g.bridges.length ? g.bridges.map((id) => { const n = byId[id]; return `
    <div class="card"><span class="score">bridge</span><h4>${esc(n.name)}</h4><p class="headline">${esc(n.headline)}</p>
      <div class="label">Reaches ${n.other_clusters} other cluster(s) · ${n.degree} connections. Introduce them to everyone.</div></div>`; }).join("")
    : `<div class="card muted">${g.nodes.length ? `${g.clusters} cluster(s), no bridges yet.` : "Empty room. Load the demo room or add attendees."}</div>`;
}

loadMe().then(loadAttendees).then(() => { if (location.hash === "#me") showTab("me"); else loadRoomGraph(); });

"use strict";

const $ = (id) => document.getElementById(id);
const STATE_LABELS = {
  reviewed: "reviewed by hand",
  detected: "detected automatically",
  detecting: "detecting…",
  failed: "detection failed, showing the last known conflicts",
};
let token = "";
try { token = sessionStorage.getItem("adminToken") || ""; } catch { /* storage unavailable */ }
let pollTimer = null;

async function api(path, options = {}) {
  const res = await fetch(path, { ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(body.detail || `HTTP ${res.status}`), { status: res.status });
  return body;
}

function cell(text, className) {
  const td = document.createElement("td");
  td.textContent = text;
  if (className) td.className = className;
  return td;
}

function render(status) {
  $("unlock").hidden = true;
  $("panel").hidden = false;

  $("docs").replaceChildren(...status.documents.map((doc) => {
    const tr = document.createElement("tr");
    tr.append(cell(doc.title), cell(doc.file, "mono"), cell(String(doc.chunks)),
              cell(doc.source === "upload" ? "uploaded" : "built-in"));
    const actions = document.createElement("td");
    if (doc.source === "upload") {
      const btn = document.createElement("button");
      btn.className = "btn-ghost";
      btn.textContent = "Remove";
      btn.addEventListener("click", async () => {
        if (!confirm(`Remove ${doc.file}? It will no longer be searched.`)) return;
        btn.disabled = true;
        try { render(await api(`/api/admin/documents/${encodeURIComponent(doc.file)}`, { method: "DELETE" })); }
        catch (e) { alert(e.message); btn.disabled = false; }
      });
      actions.append(btn);
    }
    tr.append(actions);
    return tr;
  }));

  $("conflict-state").textContent = STATE_LABELS[status.conflict_state] || status.conflict_state || "";
  $("conflicts").replaceChildren(...(status.conflicts.length ? status.conflicts : [{ topic: "None found", claims: 0 }])
    .map((c) => { const li = document.createElement("li"); li.textContent = c.claims ? `${c.topic} (${c.claims} sides)` : c.topic; return li; }));

  clearTimeout(pollTimer);
  if (status.conflict_state === "detecting") pollTimer = setTimeout(refresh, 4000);
}

async function refresh() {
  try { render(await api("/api/admin/status")); }
  catch (e) {
    $("unlock").hidden = false;
    $("panel").hidden = true;
    if (token) { $("unlock-error").textContent = e.status === 401 ? "Wrong token." : e.message; $("unlock-error").hidden = false; }
  }
}

$("unlock-form").addEventListener("submit", (e) => {
  e.preventDefault();
  token = $("token").value.trim();
  try { sessionStorage.setItem("adminToken", token); } catch { /* storage unavailable */ }
  $("unlock-error").hidden = true;
  refresh();
});

$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = $("file").files[0];
  if (!file) return;
  const note = $("upload-status");
  note.hidden = false;
  note.className = "admin-note";
  note.textContent = `Uploading and ingesting ${file.name}…`;
  $("upload-btn").disabled = true;
  try {
    const status = await api("/api/admin/documents", {
      method: "POST", body: file, headers: { "Content-Type": "application/pdf", "X-Filename": file.name },
    });
    const doc = status.documents.find((d) => d.file === file.name);
    note.textContent = `${file.name} is live: ${doc ? doc.chunks : "?"} sections are now searchable. Conflict detection is running.`;
    $("upload-form").reset();
    render(status);
  } catch (err) {
    note.className = "admin-note admin-error";
    note.textContent = err.message;
  } finally {
    $("upload-btn").disabled = false;
  }
});

if (token) refresh();

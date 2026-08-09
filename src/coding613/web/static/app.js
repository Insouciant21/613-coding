const state = { runId: null, timer: null };

const $ = (id) => document.getElementById(id);
const show = (id, value) => { $(id).hidden = false; $(id).textContent = value; };
const hide = (id) => { $(id).hidden = true; };

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `Request failed (${response.status})`);
  return response.json();
}

function setError(error) { show("error", error.message || String(error)); }
function clearMessages() { hide("error"); hide("notice"); }

function renderSummary(summary) {
  const status = String(summary.status || "unknown").toLowerCase();
  const chip = $("run-state"); chip.className = `state-chip ${status}`; chip.textContent = status;
  $("run-id").textContent = summary.run_id || state.runId || "—";
  $("stop-reason").textContent = summary.stop_reason || "—";
  $("supervisor-state").textContent = status === "completed" ? "complete" : status;
  $("worker-state").textContent = summary.changed_files?.length ? "artifact exported" : "working";
  const files = summary.changed_files || [];
  $("file-count").textContent = String(files.length);
  $("changed-files").innerHTML = files.length ? files.map((file) => `<li class="mono">${escapeHtml(file)}</li>`).join("") : '<li class="empty">No changes exported.</li>';
  const evidence = summary.validation_evidence || [];
  $("evidence").innerHTML = evidence.length ? evidence.map((item) => `<li class="${item.passed ? "pass" : "fail"}">${escapeHtml(item.command || item.kind || "validation")}: ${item.passed ? "passed" : "failed"}</li>`).join("") : '<li class="empty">Validation has not run.</li>';
  const approvals = summary.approvals || [];
  if (approvals.length) {
    $("approval-card").hidden = false;
    $("approval-empty").hidden = true;
    $("approval-card").dataset.approvalId = approvals[approvals.length - 1];
    $("approval-detail").textContent = "A scoped worker action is waiting for your decision.";
  }
}

function renderEvents(events) {
  $("event-count").textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
  $("timeline").innerHTML = events.length ? events.map((event) => {
    const type = event.event_type || event.type || "event";
    const tone = type.includes("failure") || type.includes("blocked") ? "warning" : type.includes("completed") || type.includes("success") ? "success" : "";
    return `<li class="${tone}"><div class="event-type">${escapeHtml(type)}</div><div class="event-meta">${escapeHtml(event.timestamp || `v${event.version ?? "—"}`)}</div></li>`;
  }).join("") : '<li class="empty">No events yet.</li>';
}

function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char])); }

async function refresh() {
  if (!state.runId) return;
  try {
    const [summary, events] = await Promise.all([request(`/api/runs/${state.runId}`), request(`/api/runs/${state.runId}/events`)]);
    renderSummary(summary); renderEvents(events);
    if (["completed", "failed", "cancelled"].includes(String(summary.status).toLowerCase()) && state.timer) { clearInterval(state.timer); state.timer = null; }
  } catch (error) { setError(error); }
}

$("task-form").addEventListener("submit", async (event) => {
  event.preventDefault(); clearMessages();
  try {
    const run = await request("/api/runs", { method: "POST", body: JSON.stringify({ task: $("task").value }) });
    state.runId = run.id || run.run_id; show("notice", "Run created. Supervisor is preparing the first worker wave.");
    renderSummary({ run_id: state.runId, status: run.state || "running" });
    await refresh();
    if (!state.timer) state.timer = setInterval(refresh, 3000);
  } catch (error) { setError(error); }
});

$("approve").addEventListener("click", () => resolveApproval("approve"));
$("reject").addEventListener("click", () => resolveApproval("reject"));
$("resume").addEventListener("click", () => transitionRun("resume"));
$("cancel").addEventListener("click", () => transitionRun("cancel"));
async function transitionRun(action) {
  if (!state.runId) return;
  try { await request(`/api/runs/${state.runId}/${action}`, { method: "POST" }); show("notice", `Run ${action} requested.`); await refresh(); }
  catch (error) { setError(error); }
}
async function resolveApproval(decision) {
  const approvalId = $("approval-card").dataset.approvalId;
  if (!approvalId) return;
  try { await request(`/api/approvals/${approvalId}`, { method: "POST", body: JSON.stringify({ decision }) }); hide("approval-card"); show("notice", `Approval ${decision}d.`); await refresh(); }
  catch (error) { setError(error); }
}

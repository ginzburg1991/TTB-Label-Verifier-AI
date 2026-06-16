/* TTB Label Verification — frontend logic. Vanilla JS, no dependencies. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const ICONS = { pass: "\u2713", confirmed: "\u2713", review: "!", attention: "\u00d7", rejected: "\u2298" };
const escapeHtml = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------- engine status ---------- */
async function loadEngine() {
  try {
    const r = await fetch("/api/health");
    const d = await r.json();
    $("#engine").textContent = d.ocr_ready ? `Engine: ${d.ocr_provider}` : "Engine: not ready";
    if (!d.ocr_ready) $("#engine").title = d.ocr_error || "";
  } catch {
    $("#engine").textContent = "Engine: offline";
  }
}

/* ---------- tabs ---------- */
function setTab(which) {
  const single = which === "single";
  $("#tab-single").classList.toggle("is-active", single);
  $("#tab-batch").classList.toggle("is-active", !single);
  $("#tab-single").setAttribute("aria-selected", String(single));
  $("#tab-batch").setAttribute("aria-selected", String(!single));
  $("#panel-single").hidden = !single;
  $("#panel-batch").hidden = single;
}
$("#tab-single").addEventListener("click", () => setTab("single"));
$("#tab-batch").addEventListener("click", () => setTab("batch"));

/* ---------- single: file handling ---------- */
const drop = $("#drop"), fileInput = $("#file"), preview = $("#preview");
let chosenFile = null;

function showPreview(file) {
  chosenFile = file;
  const url = URL.createObjectURL(file);
  preview.src = url;
  preview.hidden = false;
  $(".drop-empty", drop).style.display = "none";
}
drop.addEventListener("click", () => fileInput.click());
drop.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener("change", () => fileInput.files[0] && showPreview(fileInput.files[0]));
["dragover", "dragenter"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("is-over"); }));
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("is-over"); }));
drop.addEventListener("drop", (e) => {
  const f = e.dataTransfer.files[0];
  if (f && f.type.startsWith("image/")) showPreview(f);
});

/* ---------- rendering + reviewer decisions ---------- */
// A reviewer can act on a field when EITHER the image is low quality OR the
// field is "Review recommended". The actions are:
//   - Confirm correct   -> field is fine
//   - Mark incorrect    -> field is genuinely wrong (a confirmed problem)
// On a low-quality image the reviewer can also declare the whole label correct,
// or declare the image too low quality for even a human to read (reject).
// A clear photo with a hard mismatch/missing offers NO actions (real finding).
let lastResult = null;
let decisions = new Map();        // single: field name -> "correct" | "incorrect"
let labelDecision = null;         // single: null | "correct" | "unreadable"

const SEV = { match: 0, not_checked: 0, confirmed: 0, review: 1, missing: 2, mismatch: 2, incorrect: 2 };
const isFlagged = (s) => s === "review" || s === "mismatch" || s === "missing";

function statusWord(s) {
  return { match: "Pass", review: "Review", mismatch: "Mismatch", missing: "Missing",
           confirmed: "Confirmed", incorrect: "Incorrect", not_checked: "—" }[s] || s;
}

// Can the reviewer act on this field?
function fieldActionable(f, lowQuality) {
  return (lowQuality && isFlagged(f.status)) || f.status === "review";
}

// Effective status after applying decisions.
function effStatus(f, decisionMap, labelDec) {
  const dec = decisionMap.get(f.field);
  if (dec === "correct") return "confirmed";
  if (dec === "incorrect") return "incorrect";
  if (labelDec === "correct" && isFlagged(f.status)) return "confirmed";
  return f.status;
}

// opts: { lowQuality, decisionMap, labelDec, row }
function fieldRow(f, opts = {}) {
  const { lowQuality = false, decisionMap = new Map(), labelDec = null, row = null } = opts;
  const status = effStatus(f, decisionMap, labelDec);
  const dec = decisionMap.get(f.field);
  const cmp = [];
  if (f.expected) cmp.push(`<div><span class="lbl">Application</span> <code>${escapeHtml(f.expected)}</code></div>`);
  if (f.found)    cmp.push(`<div><span class="lbl">On label</span> <code>${escapeHtml(f.found)}</code></div>`);

  const rowAttr = row != null ? ` data-row="${row}"` : "";
  const fieldAttr = ` data-field="${escapeHtml(f.field)}"`;
  let controls = "";
  if (fieldActionable(f, lowQuality)) {
    if (dec || labelDec === "correct") {
      const tag = (dec === "incorrect")
        ? `<span class="decided-tag bad">✕ Marked incorrect by reviewer</span>`
        : `<span class="decided-tag ok">✓ Confirmed correct by reviewer</span>`;
      // Allow undo only for an explicit per-field decision (not a label-wide one).
      const undo = dec ? `<button class="rev-btn undo" data-action="undo"${fieldAttr}${rowAttr}>Undo</button>` : "";
      controls = `<div class="rev-controls">${tag}${undo}</div>`;
    } else {
      controls = `<div class="rev-controls">
        <button class="rev-btn ok" data-action="correct"${fieldAttr}${rowAttr}>Confirm correct</button>
        <button class="rev-btn bad" data-action="incorrect"${fieldAttr}${rowAttr}>Mark incorrect</button>
      </div>`;
    }
  }

  return `
    <div class="fr ${status}">
      <div class="fr-head">
        <span class="pill ${status}">${escapeHtml(statusWord(status))}</span>
        <span class="fr-name">${escapeHtml(f.field)}</span>
      </div>
      <p class="fr-reason">${escapeHtml(f.reason)}</p>
      ${cmp.length ? `<div class="fr-compare">${cmp.join("")}</div>` : ""}
      ${controls}
    </div>`;
}

// Recompute the overall verdict from the reviewer's decisions.
function computeVerdict(d, decisionMap, labelDec) {
  const lowQuality = !!d.image_quality_note;
  if (labelDec === "unreadable") {
    return { verdict: "rejected", label: "Rejected — image unreadable",
             summary: "Reviewer confirmed the image is too low quality to read. A clearer photo is needed." };
  }
  const eff = d.fields.map((f) => effStatus(f, decisionMap, labelDec));
  let worst = 0;
  eff.forEach((s) => { worst = Math.max(worst, SEV[s] ?? 0); });

  const flagged = d.fields.filter((f) => isFlagged(f.status));
  const anyIncorrect = eff.includes("incorrect");
  const allFlaggedCorrect = flagged.length > 0 &&
    flagged.every((f) => decisionMap.get(f.field) === "correct" || labelDec === "correct");
  const qualityVouched = labelDec === "correct" || allFlaggedCorrect;
  const lowqUnresolved = lowQuality && !qualityVouched && !anyIncorrect;
  if (lowqUnresolved) worst = Math.max(worst, 1);

  const anyDecision = decisionMap.size > 0 || !!labelDec;

  if (worst === 0) {
    return anyDecision
      ? { verdict: "confirmed", label: "Confirmed by reviewer",
          summary: "Flagged items were reviewed and confirmed correct." }
      : { verdict: "pass", label: "All checks passed",
          summary: "Every checked field matches the application." };
  }
  const nRev = eff.filter((s) => s === "review").length + (lowqUnresolved ? 1 : 0);
  if (worst >= 2) {
    const nInc = eff.filter((s) => s === "incorrect").length;
    const nAuto = eff.filter((s) => s === "mismatch" || s === "missing").length;
    const revTail = nRev ? `, ${nRev} to review` : "";
    // Marking something incorrect always rejects -- even on a low-quality image.
    if (nInc > 0) {
      return { verdict: "rejected", label: "Rejected",
               summary: `Reviewer marked ${nInc} item(s) incorrect${revTail}.` };
    }
    // Auto-detected discrepancies: a low-quality image needs a human look (OCR
    // may be wrong); a clear image that doesn't match is a definitive rejection.
    if (lowQuality) {
      return { verdict: "attention", label: "Needs attention",
               summary: `Low-quality image with ${nAuto} unverified item(s)${revTail} — review the photo.` };
    }
    return { verdict: "rejected", label: "Rejected",
             summary: `${nAuto} item(s) don't match the application${revTail}.` };
  }
  return { verdict: "review", label: "Review recommended",
           summary: `${nRev} item(s) to review or confirm.` };
}

// Low-quality note + whole-label actions (only when the image is low quality).
function qualityBoxHtml(d, labelDec, row) {
  if (!d.image_quality_note) return "";
  const rowAttr = row != null ? ` data-row="${row}"` : "";
  let actions;
  if (labelDec === "correct") {
    actions = `<span class="decided-tag ok">✓ Reviewer confirmed the label is correct</span>
               <button class="rev-label undo" data-action="label-undo"${rowAttr}>Undo</button>`;
  } else if (labelDec === "unreadable") {
    actions = `<span class="decided-tag bad">⊘ Reviewer marked the image unreadable</span>
               <button class="rev-label undo" data-action="label-undo"${rowAttr}>Undo</button>`;
  } else {
    actions = `
      <button class="rev-label ok" data-action="label-correct"${rowAttr}>I checked the image — confirm the label is correct</button>
      <button class="rev-label bad" data-action="label-unreadable"${rowAttr}>Image is too low quality to read</button>`;
  }
  return `<div class="note quality"><p>${escapeHtml(d.image_quality_note)}</p><div class="rev-controls">${actions}</div></div>`;
}

function renderResult(d) {
  const lowQuality = !!d.image_quality_note;
  const v = computeVerdict(d, decisions, labelDecision);
  const meta = [];
  if (typeof d.ocr_confidence === "number") meta.push(`OCR confidence ${d.ocr_confidence}%`);
  meta.push(`${d.elapsed_ms} ms`);
  meta.push(escapeHtml(d.ocr_provider));

  return `
    <div class="verdict ${v.verdict}">
      <span class="vicon">${ICONS[v.verdict] || "?"}</span>
      <div>
        <h3>${escapeHtml(v.label)}</h3>
        <p>${escapeHtml(v.summary)}</p>
      </div>
    </div>
    <div class="meta">${meta.join("  ·  ")}</div>
    ${qualityBoxHtml(d, labelDecision, null)}
    <div class="fieldlist">${d.fields.map((f) => fieldRow(f, { lowQuality, decisionMap: decisions, labelDec: labelDecision })).join("")}</div>
    ${d.ocr_text ? `<details class="ocr-toggle"><summary>Show what the scanner read</summary><pre>${escapeHtml(d.ocr_text)}</pre></details>` : ""}
  `;
}

function showResult(d) {
  lastResult = d;
  decisions = new Map();
  labelDecision = null;
  $("#single-result").innerHTML = renderResult(d);
}

// Single-mode decision clicks.
$("#single-result").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-action]");
  if (!btn || !lastResult) return;
  const action = btn.dataset.action;
  const fieldName = btn.dataset.field;
  if (action === "correct") decisions.set(fieldName, "correct");
  else if (action === "incorrect") decisions.set(fieldName, "incorrect");
  else if (action === "undo") decisions.delete(fieldName);
  else if (action === "label-correct") labelDecision = "correct";
  else if (action === "label-unreadable") labelDecision = "unreadable";
  else if (action === "label-undo") labelDecision = null;
  else return;
  $("#single-result").innerHTML = renderResult(lastResult);
});

/* ---------- wine / beer detection -> alcohol content optional ---------- */
// Wine: any class/type containing "wine". Beer / malt beverage: these terms,
// matched as whole words so "single malt" whisky isn't treated as beer.
const BEER_RE = /\b(beer|ale|lager|stout|porter|pilsner|ipa|malt\s+beverage|malt\s+liquor)\b/i;
const WINE_RE = /wine/i;

function isWineOrBeer(classType) {
  const t = (classType || "").trim();
  return WINE_RE.test(t) || BEER_RE.test(t);
}

function updateAbvRequirement() {
  const form = $("#single-form");
  const exempt = isWineOrBeer(form.class_type.value);
  $("#abv-required").hidden = exempt;       // hide the "required" tag
  const note = $("#abv-note");
  if (exempt) {
    note.hidden = false;
    note.textContent =
      "Not required for wine or beer. Confirm the product is 0.5% ABV or higher — " +
      "below 0.5% it isn't regulated as an alcohol beverage.";
  } else {
    note.hidden = true;
  }
}
$("#single-form").class_type.addEventListener("input", updateAbvRequirement);
updateAbvRequirement(); // set initial state

// Required fields. Alcohol content is conditional (handled separately).
const REQUIRED_FIELDS = [
  ["brand_name", "Brand name"],
  ["class_type", "Class / type"],
  ["net_contents", "Net contents"],
  ["origin", "Place of origin"],
];

function clearFieldErrors(form) {
  $$(".field.invalid", form).forEach((el) => el.classList.remove("invalid"));
  $$(".field-err", form).forEach((el) => el.remove());
}

function markInvalid(input, message) {
  const field = input.closest(".field");
  field.classList.add("invalid");
  const err = document.createElement("span");
  err.className = "field-err";
  err.textContent = message;
  field.appendChild(err);
}

function validateRequired(form) {
  clearFieldErrors(form);
  let firstBad = null;
  for (const [name, label] of REQUIRED_FIELDS) {
    if (!form[name].value.trim()) {
      markInvalid(form[name], `${label} is required.`);
      firstBad = firstBad || form[name];
    }
  }
  // Alcohol content: required unless wine or beer.
  if (!isWineOrBeer(form.class_type.value) && !form.alcohol_content.value.trim()) {
    markInvalid(form.alcohol_content, "Alcohol content is required (not wine or beer).");
    firstBad = firstBad || form.alcohol_content;
  }
  if (firstBad) firstBad.focus();
  return !firstBad;
}

/* ---------- single: submit ---------- */
$("#single-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const out = $("#single-result");

  if (!validateRequired(form)) return;
  if (!chosenFile) {
    out.innerHTML = `<div class="error-box">Please add a label photo first.</div>`;
    return;
  }

  const btn = $("#single-submit");
  btn.disabled = true; btn.textContent = "Checking…";
  out.innerHTML = `<div class="result-empty"><span class="spinner"></span> Reading the label…</div>`;

  const fd = new FormData();
  fd.append("image", chosenFile);
  ["brand_name", "class_type", "alcohol_content", "net_contents", "origin"]
    .forEach((k) => { if (form[k].value.trim()) fd.append(k, form[k].value.trim()); });

  try {
    const r = await fetch("/api/verify", { method: "POST", body: fd });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${r.status})`);
    }
    showResult(await r.json());
  } catch (err) {
    out.innerHTML = `<div class="error-box">${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "Check this label";
  }
});

/* ---------- batch: submit ---------- */
$("#batch-submit").addEventListener("click", async () => {
  const manifest = $("#batch-manifest").files[0];
  const images = $("#batch-images").files;
  const out = $("#batch-result");

  if (!manifest) { out.innerHTML = `<div class="error-box">Add a manifest CSV.</div>`; return; }
  if (!images.length) { out.innerHTML = `<div class="error-box">Add at least one label image.</div>`; return; }

  const btn = $("#batch-submit");
  btn.disabled = true; btn.textContent = "Checking…";
  out.innerHTML = `<div class="result-empty"><span class="spinner"></span> Processing ${images.length} image(s)…</div>`;

  const fd = new FormData();
  fd.append("manifest", manifest);
  [...images].forEach((f) => fd.append("images", f));

  try {
    const r = await fetch("/api/verify-batch", { method: "POST", body: fd });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${r.status})`);
    }
    renderBatch(await r.json(), out);
  } catch (err) {
    out.innerHTML = `<div class="error-box">${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "Check all labels";
  }
});

/* ---------- batch rendering + per-row decisions ---------- */
let batchData = null;
let batchState = [];   // per row: { decisions:Map, label:null|"correct"|"unreadable" }

function batchOpenRows() {
  return new Set([...document.querySelectorAll("#batch-result .batch-row[open]")]
    .map((el) => Number(el.dataset.idx)));
}

function renderBatchHtml(openSet) {
  const data = batchData;
  const counts = { pass: 0, confirmed: 0, review: 0, attention: 0, rejected: 0 };

  const rows = data.results.map((d, i) => {
    const st = batchState[i];
    const v = computeVerdict(d, st.decisions, st.label);
    counts[v.verdict] = (counts[v.verdict] || 0) + 1;
    const lowQuality = !!d.image_quality_note;
    const pillClass = (v.verdict === "pass" || v.verdict === "confirmed") ? "match"
      : v.verdict === "review" ? "review"
      : v.verdict === "rejected" ? "rejected"
      : v.verdict === "attention" ? "attention" : "mismatch";
    const open = openSet && openSet.has(i) ? " open" : "";
    return `
      <details class="batch-row ${v.verdict}" data-idx="${i}"${open}>
        <summary>
          <span class="pill ${pillClass}">${escapeHtml(v.label)}</span>
          <span class="batch-id">${escapeHtml(d.label_id || "(unnamed)")}</span>
          <span class="batch-sub">${escapeHtml(v.summary)}</span>
        </summary>
        ${qualityBoxHtml(d, st.label, i)}
        ${d.fields && d.fields.length
          ? `<div class="fieldlist">${d.fields.map((f) => fieldRow(f, { lowQuality, decisionMap: st.decisions, labelDec: st.label, row: i })).join("")}</div>`
          : ""}
      </details>`;
  }).join("");

  const passed = (counts.pass || 0) + (counts.confirmed || 0);
  const summary = `
    <div class="batch-summary">
      <span class="chip total">${data.total} total</span>
      <span class="chip attention">${counts.attention || 0} need attention</span>
      <span class="chip review">${counts.review || 0} to review</span>
      <span class="chip pass">${passed} passed</span>
      ${counts.rejected ? `<span class="chip rejected">${counts.rejected} rejected</span>` : ""}
    </div>`;

  return summary + rows;
}

function renderBatch(data, out) {
  batchData = data;
  batchState = data.results.map(() => ({ decisions: new Map(), label: null }));
  out.innerHTML = renderBatchHtml(new Set());
}

// Batch decision clicks. Re-render preserves which rows are expanded.
$("#batch-result").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-action]");
  if (!btn || !batchData) return;
  const i = Number(btn.dataset.row);
  if (Number.isNaN(i) || !batchState[i]) return;
  const st = batchState[i];
  const action = btn.dataset.action;
  const fieldName = btn.dataset.field;
  if (action === "correct") st.decisions.set(fieldName, "correct");
  else if (action === "incorrect") st.decisions.set(fieldName, "incorrect");
  else if (action === "undo") st.decisions.delete(fieldName);
  else if (action === "label-correct") st.label = "correct";
  else if (action === "label-unreadable") st.label = "unreadable";
  else if (action === "label-undo") st.label = null;
  else return;
  const open = batchOpenRows();
  open.add(i);
  $("#batch-result").innerHTML = renderBatchHtml(open);
});

loadEngine();

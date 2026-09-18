/**
 * Finance Intelligence Platform Frontend Client Logic
 */

// State
let currentOrg = "org_default";
let currentDocType = "invoice"; // 'invoice' or 'po'
let selectedFile = null;
let copilotContext = null;

// DOM Elements
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initDashboard();
  initIngestion();
  initCopilot();
  initInvestigation();
  initSearchAndGraph();

  // Listen to org ID change
  const orgInput = document.getElementById("orgIdInput");
  if (orgInput) {
    orgInput.addEventListener("change", (e) => {
      currentOrg = e.target.value.trim() || "org_default";
      loadDashboard();
      loadGraphStats();
    });
  }
});

// ── Tab Management ────────────────────────────────────────────────────────────

function initTabs() {
  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabContents = document.querySelectorAll(".tab-content");

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-tab");

      // Update button active states
      tabButtons.forEach((b) => {
        b.classList.remove("active");
        b.classList.add("text-slate-400");
      });
      btn.classList.add("active");
      btn.classList.remove("text-slate-400");

      // Show target tab
      tabContents.forEach((content) => {
        if (content.id === `tab-${targetTab}`) {
          content.classList.remove("hidden");
        } else {
          content.classList.add("hidden");
        }
      });

      if (targetTab === "dashboard") loadDashboard();
      if (targetTab === "search") loadGraphStats();
    });
  });
}

// ── TAB 1: Dashboard ──────────────────────────────────────────────────────────

function initDashboard() {
  document.getElementById("refreshDashboardBtn").addEventListener("click", loadDashboard);
  loadDashboard();
}

async function loadDashboard() {
  try {
    const res = await fetch(`/analytics/dashboard?organization_id=${encodeURIComponent(currentOrg)}`);
    if (!res.ok) throw new Error("Failed to load dashboard summary");
    const data = await res.json();

    document.getElementById("kpi-spend").textContent = `₹${Number(data.total_invoice_spend || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
    document.getElementById("kpi-invoices").textContent = data.total_invoices || 0;
    document.getElementById("kpi-pos").textContent = data.total_purchase_orders || 0;
    document.getElementById("kpi-violations").textContent = data.open_violations_count || 0;
    document.getElementById("kpi-duplicates").textContent = data.open_duplicates_count || 0;
    document.getElementById("kpi-anomalies").textContent = data.open_anomalies_count || 0;

    document.getElementById("violationCountBadge").textContent = `${data.open_violations_count || 0} Open`;
    document.getElementById("anomalyCountBadge").textContent = `${(data.open_anomalies_count || 0) + (data.open_duplicates_count || 0)} Flagged`;

    // Load violations list
    loadViolations();
    loadAnomalies();
  } catch (err) {
    console.error("Dashboard error:", err);
  }
}

async function loadViolations() {
  const container = document.getElementById("violationsList");
  try {
    const res = await fetch(`/analytics/violations?organization_id=${encodeURIComponent(currentOrg)}&status=OPEN&limit=5`);
    if (!res.ok) return;
    const items = await res.json();
    if (!items || items.length === 0) {
      container.innerHTML = '<p class="text-slate-500 italic">No open rule violations recorded.</p>';
      return;
    }
    container.innerHTML = items.map(v => `
      <div class="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 flex justify-between items-center">
        <div>
          <span class="font-semibold text-amber-400">[${v.severity}] ${v.rule_name}</span>
          <p class="text-slate-400 text-[11px]">Entity: ${v.entity_type} ${v.entity_id}</p>
        </div>
        <span class="badge badge-yellow">${v.status}</span>
      </div>
    `).join("");
  } catch (e) {
    console.error(e);
  }
}

async function loadAnomalies() {
  const container = document.getElementById("anomaliesList");
  try {
    const res = await fetch(`/analytics/anomalies?organization_id=${encodeURIComponent(currentOrg)}&status=OPEN&limit=5`);
    if (!res.ok) return;
    const items = await res.json();
    if (!items || items.length === 0) {
      container.innerHTML = '<p class="text-slate-500 italic">No active anomalies flagged.</p>';
      return;
    }
    container.innerHTML = items.map(a => `
      <div class="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 flex justify-between items-center">
        <div>
          <span class="font-semibold text-rose-400">${a.anomaly_type}</span>
          <p class="text-slate-400 text-[11px]">Observed: ₹${a.observed_value} (Z-Score: ${a.z_score || "N/A"})</p>
        </div>
        <span class="badge badge-red">${a.status}</span>
      </div>
    `).join("");
  } catch (e) {
    console.error(e);
  }
}

// ── TAB 2: Document Ingestion ─────────────────────────────────────────────────

function initIngestion() {
  const btnInvoice = document.getElementById("docTypeInvoice");
  const btnPO = document.getElementById("docTypePO");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const selectedName = document.getElementById("selectedFileName");
  const uploadBtn = document.getElementById("uploadBtn");
  const toggleJsonBtn = document.getElementById("toggleJsonBtn");

  btnInvoice.addEventListener("click", () => {
    currentDocType = "invoice";
    btnInvoice.className = "px-3 py-2 text-xs font-semibold rounded-lg bg-blue-600 text-white border border-blue-500";
    btnPO.className = "px-3 py-2 text-xs font-semibold rounded-lg bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700";
  });

  btnPO.addEventListener("click", () => {
    currentDocType = "po";
    btnPO.className = "px-3 py-2 text-xs font-semibold rounded-lg bg-indigo-600 text-white border border-indigo-500";
    btnInvoice.className = "px-3 py-2 text-xs font-semibold rounded-lg bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700";
  });

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("border-blue-500", "bg-slate-800/40");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("border-blue-500", "bg-slate-800/40");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("border-blue-500", "bg-slate-800/40");
    if (e.dataTransfer.files.length > 0) {
      selectedFile = e.dataTransfer.files[0];
      selectedName.textContent = selectedFile.name;
      selectedName.classList.remove("hidden");
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      selectedFile = e.target.files[0];
      selectedName.textContent = selectedFile.name;
      selectedName.classList.remove("hidden");
    }
  });

  uploadBtn.addEventListener("click", async () => {
    if (!selectedFile) {
      alert("Please select a file to upload first.");
      return;
    }

    uploadBtn.disabled = true;
    uploadBtn.textContent = "Processing Extraction (OCR + Parsing)...";

    const formData = new FormData();
    formData.append("file", selectedFile);

    const url = currentDocType === "invoice"
      ? `/finance/process?organization_id=${encodeURIComponent(currentOrg)}`
      : `/finance/purchase-orders?organization_id=${encodeURIComponent(currentOrg)}`;

    try {
      const res = await fetch(url, { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Extraction failed");
      }
      const data = await res.json();
      renderExtractionResult(data);
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      uploadBtn.disabled = false;
      uploadBtn.textContent = "Extract & Persist Document";
    }
  });

  toggleJsonBtn.addEventListener("click", () => {
    const rawView = document.getElementById("rawJsonView");
    rawView.classList.toggle("hidden");
  });
}

function renderExtractionResult(data) {
  document.getElementById("ingestionEmptyState").classList.add("hidden");
  document.getElementById("ingestionResultContent").classList.remove("hidden");
  document.getElementById("toggleJsonBtn").classList.remove("hidden");

  const badge = document.getElementById("extractionStatusBadge");
  badge.classList.remove("hidden");
  badge.textContent = data.document_id ? "Persisted" : "Extracted";

  // Raw JSON
  document.getElementById("rawJsonView").textContent = JSON.stringify(data, null, 2);

  // Key fields
  const vendorName = data.invoice?.vendor_name_normalized?.value || data.invoice?.vendor_name_raw?.value
    || data.purchase_order?.vendor_name_raw?.value || "Unknown";
  const num = data.invoice?.invoice_number?.value || data.purchase_order?.po_number?.value || "N/A";
  const total = data.invoice?.total_amount?.value || data.purchase_order?.total_amount?.value || "0.00";
  const invDate = data.invoice?.invoice_date?.value || data.purchase_order?.po_date?.value || "N/A";

  document.getElementById("resVendor").textContent = vendorName;
  document.getElementById("resNumber").textContent = num;
  document.getElementById("resTotal").textContent = `₹${total}`;
  document.getElementById("resDate").textContent = invDate;

  // Line items
  const items = data.invoice?.line_items || data.purchase_order?.line_items || [];
  document.getElementById("lineItemsCount").textContent = items.length;

  const tbody = document.getElementById("lineItemsBody");
  if (items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="p-3 text-center text-slate-500 italic">No line items parsed.</td></tr>';
  } else {
    tbody.innerHTML = items.map(it => `
      <tr class="hover:bg-slate-800/40">
        <td class="p-2 font-medium">${it.description || "Item"}</td>
        <td class="p-2 font-mono text-slate-400 text-[10px]">${it.product_code || "-"}</td>
        <td class="p-2 text-right">${it.quantity || "1"}</td>
        <td class="p-2 text-right">₹${it.unit_price || "0.00"}</td>
        <td class="p-2 text-right font-semibold text-emerald-400">₹${it.total || "0.00"}</td>
      </tr>
    `).join("");
  }
}

// ── TAB 3: Finance Copilot ────────────────────────────────────────────────────

function initCopilot() {
  const form = document.getElementById("copilotForm");
  const qInput = document.getElementById("copilotQuestion");
  const clearBtn = document.getElementById("clearContextBtn");
  const chips = document.querySelectorAll(".copilot-chip");

  chips.forEach(chip => {
    chip.addEventListener("click", () => {
      qInput.value = chip.textContent.trim();
    });
  });

  clearBtn.addEventListener("click", () => {
    copilotContext = null;
    updateContextDisplay();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = qInput.value.trim();
    if (!q) return;

    const submitBtn = document.getElementById("copilotSubmitBtn");
    submitBtn.disabled = true;
    submitBtn.innerHTML = "<span>Thinking...</span> ⏳";

    const includePlan = document.getElementById("includePlanCheck").checked;

    try {
      const res = await fetch(`/copilot/ask?organization_id=${encodeURIComponent(currentOrg)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          organization_id: currentOrg,
          context: copilotContext,
          include_query_plan: includePlan,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Copilot query failed");
      }

      const data = await res.json();
      copilotContext = data.context || copilotContext;
      renderCopilotAnswer(data);
      updateContextDisplay();
    } catch (err) {
      alert("Copilot error: " + err.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerHTML = "<span>Ask Copilot</span> ⚡";
    }
  });

  // Evidence Drawer toggle
  document.getElementById("evidenceToggleBtn").addEventListener("click", () => {
    const drawer = document.getElementById("evidenceDrawer");
    const arrow = document.getElementById("evidenceToggleArrow");
    drawer.classList.toggle("hidden");
    arrow.textContent = drawer.classList.contains("hidden") ? "▼" : "▲";
  });
}

function renderCopilotAnswer(data) {
  const card = document.getElementById("copilotResponseCard");
  card.classList.remove("hidden");

  document.getElementById("resIntentBadge").textContent = data.intent || "QUERY";
  document.getElementById("resConfidenceBadge").textContent = `Confidence ${data.confidence || "1.0"}`;
  document.getElementById("resQueryId").textContent = data.query_id || "";
  document.getElementById("copilotAnswerText").textContent = data.answer || "No answer generated.";

  // Metrics Strip
  const strip = document.getElementById("copilotMetricsStrip");
  if (data.metrics && data.metrics.length > 0) {
    strip.classList.remove("hidden");
    strip.innerHTML = data.metrics.map(m => `
      <span class="badge badge-blue">
        ${m.name || "metric"}: ${m.value || m.total_spend || JSON.stringify(m)}
      </span>
    `).join("");
  } else {
    strip.classList.add("hidden");
  }

  // Evidence
  const evidence = data.evidence || [];
  document.getElementById("evidenceCount").textContent = evidence.length;
  const evDrawer = document.getElementById("evidenceDrawer");
  if (evidence.length === 0) {
    evDrawer.innerHTML = '<p class="text-slate-500 italic">No direct provenance evidence records cited.</p>';
  } else {
    evDrawer.innerHTML = evidence.map((e, idx) => `
      <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
        <div class="flex justify-between items-center font-mono text-[10px]">
          <span class="text-blue-400 font-bold">${e.source_type}</span>
          <span class="text-slate-500">Conf: ${e.confidence}</span>
        </div>
        ${e.source_operation ? `<p class="text-slate-400 text-[10px]">Op: <code class="text-purple-300">${e.source_operation}</code></p>` : ''}
        ${e.source_text ? `<p class="text-slate-200 italic">"${e.source_text}"</p>` : ''}
        ${e.bbox ? `<p class="text-slate-500 text-[10px]">BBox: [${e.bbox.join(", ")}] (Page ${e.page_number || 1})</p>` : ''}
        ${e.metric ? `<pre class="text-[10px] text-emerald-400 font-mono">${JSON.stringify(e.metric, null, 1)}</pre>` : ''}
      </div>
    `).join("");
  }

  // Query Plan
  const planDrawer = document.getElementById("queryPlanDrawer");
  if (data.query_plan) {
    planDrawer.classList.remove("hidden");
    document.getElementById("queryPlanJson").textContent = JSON.stringify(data.query_plan, null, 2);
  } else {
    planDrawer.classList.add("hidden");
  }
}

function updateContextDisplay() {
  document.getElementById("ctxLastVendor").textContent = copilotContext?.last_vendor_name || copilotContext?.last_vendor_id || "-";
  document.getElementById("ctxLastDates").textContent = copilotContext?.last_date_range ? `${copilotContext.last_date_range.start_date} to ${copilotContext.last_date_range.end_date}` : "-";
  document.getElementById("ctxLastIntent").textContent = copilotContext?.last_intent || "-";
}

// ── TAB 4: Investigation Studio ───────────────────────────────────────────────

function initInvestigation() {
  const form = document.getElementById("investigationForm");
  const qInput = document.getElementById("investigationQuestion");
  const chips = document.querySelectorAll(".investigate-chip");

  chips.forEach(c => {
    c.addEventListener("click", () => {
      qInput.value = c.textContent.trim();
    });
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = qInput.value.trim();
    if (!q) return;

    const submitBtn = document.getElementById("investigateSubmitBtn");
    const loading = document.getElementById("investigationLoading");
    const reportCard = document.getElementById("investigationReportCard");

    submitBtn.disabled = true;
    loading.classList.remove("hidden");
    reportCard.classList.add("hidden");

    try {
      const res = await fetch(`/investigate?organization_id=${encodeURIComponent(currentOrg)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          organization_id: currentOrg,
          include_trace: true,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Investigation failed");
      }

      const report = await res.json();
      renderInvestigationReport(report);
    } catch (err) {
      alert("Investigation error: " + err.message);
    } finally {
      submitBtn.disabled = false;
      loading.classList.add("hidden");
    }
  });
}

function renderInvestigationReport(rep) {
  const card = document.getElementById("investigationReportCard");
  card.classList.remove("hidden");

  document.getElementById("repType").textContent = rep.investigation_type;
  document.getElementById("repTitle").textContent = rep.title;
  document.getElementById("repConfidence").textContent = `Confidence ${rep.confidence}`;
  document.getElementById("repId").textContent = rep.investigation_id;

  // Baseline vs Target
  document.getElementById("repBaselineDates").textContent = rep.baseline?.period || "-";
  document.getElementById("repBaselineSpend").textContent = `₹${rep.baseline?.spend || "0.00"}`;
  document.getElementById("repTargetDates").textContent = rep.target?.period || "-";
  document.getElementById("repTargetSpend").textContent = `₹${rep.target?.spend || "0.00"}`;

  const deltaAmt = rep.change?.absolute || "0.00";
  const deltaPct = rep.change?.percentage || "0%";
  const dir = rep.change?.direction === "INCREASE" ? "+" : (rep.change?.direction === "DECREASE" ? "-" : "");
  document.getElementById("repDeltaPct").textContent = `${dir}${deltaPct}`;
  document.getElementById("repDeltaAmount").textContent = `${dir}₹${deltaAmt}`;

  // Summary & Conclusion
  document.getElementById("repSummary").textContent = rep.summary;
  document.getElementById("repConclusion").textContent = rep.conclusion;

  // Drivers
  const driversContainer = document.getElementById("repDriversList");
  if (!rep.drivers || rep.drivers.length === 0) {
    driversContainer.innerHTML = '<p class="text-slate-500 italic">No specific line item drivers isolated.</p>';
  } else {
    driversContainer.innerHTML = rep.drivers.map(d => `
      <div class="p-3 rounded-lg bg-slate-900 border border-slate-800 space-y-1">
        <div class="flex justify-between items-center">
          <span class="badge badge-purple">${d.type}</span>
          <span class="font-bold text-emerald-400">Impact: ₹${d.impact_amount}</span>
        </div>
        <p class="text-slate-200 mt-1">${d.description}</p>
      </div>
    `).join("");
  }

  // Anomalies container
  const anomContainer = document.getElementById("repAnomaliesContainer");
  const anomList = document.getElementById("repAnomaliesList");
  if (rep.anomalies && rep.anomalies.length > 0) {
    anomContainer.classList.remove("hidden");
    anomList.innerHTML = rep.anomalies.map(a => `
      <div class="p-2.5 rounded bg-slate-900 border border-slate-800 flex justify-between">
        <span class="text-rose-400 font-semibold">${a.anomaly_type}</span>
        <span class="text-slate-400">Observed ₹${a.observed_value} (Z-Score: ${a.z_score || 'N/A'})</span>
      </div>
    `).join("");
  } else {
    anomContainer.classList.add("hidden");
  }
}

// ── TAB 5: Search & Graph ─────────────────────────────────────────────────────

function initSearchAndGraph() {
  const searchForm = document.getElementById("searchForm");
  const searchInput = document.getElementById("searchInput");
  const refreshGraphBtn = document.getElementById("refreshGraphBtn");
  const traceBtn = document.getElementById("traceGraphBtn");

  searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = searchInput.value.trim();
    if (!q) return;

    const resultsDiv = document.getElementById("searchResults");
    resultsDiv.innerHTML = '<p class="text-slate-400">Searching vector index...</p>';

    try {
      const res = await fetch("/search/semantic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, organization_id: currentOrg, top_k: 5 }),
      });
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      const results = data.results || [];

      if (results.length === 0) {
        resultsDiv.innerHTML = '<p class="text-slate-500 italic">No matching document chunks found.</p>';
        return;
      }

      resultsDiv.innerHTML = results.map(r => `
        <div class="p-3 bg-slate-900 border border-slate-800 rounded-lg space-y-1">
          <div class="flex justify-between text-[10px] text-slate-500 font-mono">
            <span>Score: <b class="text-blue-400">${r.similarity_score.toFixed(3)}</b></span>
            <span>Doc: ${r.document_id}</span>
          </div>
          <p class="text-slate-200">"${r.text}"</p>
          ${r.bbox ? `<span class="text-[10px] text-slate-500 font-mono">BBox: [${r.bbox.join(", ")}]</span>` : ''}
        </div>
      `).join("");
    } catch (err) {
      resultsDiv.innerHTML = `<p class="text-rose-400">Error: ${err.message}</p>`;
    }
  });

  refreshGraphBtn.addEventListener("click", loadGraphStats);

  traceBtn.addEventListener("click", async () => {
    const vId = document.getElementById("graphVendorInput").value.trim();
    const resultDiv = document.getElementById("graphTraceResult");
    if (!vId) return;

    resultDiv.classList.remove("hidden");
    resultDiv.textContent = "Tracing knowledge graph...";

    try {
      const res = await fetch(`/graph/vendor/${encodeURIComponent(vId)}/network?organization_id=${encodeURIComponent(currentOrg)}`);
      if (!res.ok) throw new Error("Vendor network not found");
      const data = await res.json();
      resultDiv.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      resultDiv.textContent = `Error: ${err.message}`;
    }
  });
}

async function loadGraphStats() {
  try {
    const res = await fetch("/graph/stats");
    if (!res.ok) return;
    const stats = await res.json();
    document.getElementById("graphNodesCount").textContent = stats.total_nodes || 0;
    document.getElementById("graphEdgesCount").textContent = stats.total_edges || 0;
  } catch (e) {
    console.error(e);
  }
}

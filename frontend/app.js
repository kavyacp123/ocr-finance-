/**
 * LedgerLens finance intelligence console.
 * Vanilla JS by design: the backend remains the source of truth for every fact.
 */

const state = {
  organization: localStorage.getItem("ledgerlens.organization") || "org_default",
  activeTab: "dashboard",
  documentType: "invoice",
  selectedFile: null,
  copilotContext: null,
  vaultType: "invoices",
  vaultData: {},
  graphData: null,
  config: null,
};

const tabNames = {
  dashboard: "Overview",
  ingest: "Ingest",
  data: "Data vault",
  copilot: "Finance Copilot",
  investigate: "Investigations",
  search: "Search & graph",
};

document.addEventListener("DOMContentLoaded", function () {
  document.getElementById("orgIdInput").value = state.organization;
  document.getElementById("vaultOrgLabel").textContent = state.organization;
  initNavigation();
  initDashboard();
  initIngestion();
  initDataVault();
  initCopilot();
  initInvestigation();
  initSearchAndGraph();
  initOrganization();
  refreshIcons();
  loadSystemStatus();
  loadDashboard();
});

function refreshIcons() {
  if (window.lucide) {
    window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });
  }
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatCurrency(value, currency) {
  const amount = Number(value || 0);
  const code = currency || "INR";
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: code,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch (_) {
    return "₹" + amount.toLocaleString("en-IN", { minimumFractionDigits: 2 });
  }
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("en-IN");
}

function statusClass(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized.includes("paid") && !normalized.includes("unpaid")) return "paid";
  if (normalized.includes("overdue") || normalized.includes("invalid") || normalized.includes("failed")) return "overdue";
  return "";
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = "Request failed (" + response.status + ")";
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch (_) {
      // Preserve the HTTP status message when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json();
}

function showToast(message, type) {
  const region = document.getElementById("toastRegion");
  const toast = document.createElement("div");
  toast.className = "toast" + (type === "error" ? " error" : "");
  toast.innerHTML = '<i data-lucide="' + (type === "error" ? "circle-alert" : "circle-check") + '"></i><span>' + escapeHtml(message) + "</span>";
  region.appendChild(toast);
  refreshIcons();
  window.setTimeout(function () { toast.remove(); }, 4200);
}

function emptyState(icon, message) {
  return '<div class="empty-state compact"><i data-lucide="' + icon + '"></i><p>' + escapeHtml(message) + "</p></div>";
}

function initNavigation() {
  document.querySelectorAll(".tab-btn").forEach(function (button) {
    button.addEventListener("click", function () { activateTab(button.dataset.tab); });
  });
  document.querySelectorAll(".tab-shortcut").forEach(function (button) {
    button.addEventListener("click", function () { activateTab(button.dataset.targetTab); });
  });
  document.getElementById("mobileMenuBtn").addEventListener("click", function () {
    document.body.classList.toggle("nav-open");
  });
}

function activateTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".tab-btn").forEach(function (button) {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-content").forEach(function (section) {
    section.classList.toggle("hidden", section.id !== "tab-" + tab);
  });
  document.getElementById("activeSectionName").textContent = tabNames[tab] || tab;
  document.body.classList.remove("nav-open");
  if (tab === "dashboard") loadDashboard();
  if (tab === "data") loadDataVault();
  if (tab === "search") loadGraphWorkspace();
}

function initOrganization() {
  const input = document.getElementById("orgIdInput");
  input.addEventListener("change", function () {
    state.organization = input.value.trim() || "org_default";
    input.value = state.organization;
    localStorage.setItem("ledgerlens.organization", state.organization);
    document.getElementById("vaultOrgLabel").textContent = state.organization;
    state.copilotContext = null;
    state.vaultData = {};
    updateContextDisplay();
    showToast("Switched to organization " + state.organization);
    if (state.activeTab === "data") loadDataVault();
    else if (state.activeTab === "search") loadGraphWorkspace();
    else loadDashboard();
  });
}

async function loadSystemStatus() {
  const dot = document.getElementById("systemStatusDot");
  try {
    const responses = await Promise.all([
      fetchJson("/health"),
      fetchJson("/config"),
      fetchJson("/search/stats"),
    ]);
    const health = responses[0];
    state.config = responses[1];
    const search = responses[2];
    dot.className = "status-dot online";
    document.getElementById("systemStatusText").textContent = "Backend online";
    document.getElementById("engineStatusText").textContent = health.inference_engine + " / " + (health.mock_mode ? "mock" : "real") + " mode";
    document.getElementById("storageOcrMode").textContent = health.mock_mode ? "Mock OCR" : "Real OCR";
    document.getElementById("storageOcrEngine").textContent = health.ocr_model;
    document.getElementById("ingestEngineBadge").textContent = health.inference_engine + " / " + (health.mock_mode ? "mock" : "real") + " mode";
    document.getElementById("storageChunkCount").textContent = formatNumber(search.total_chunks) + " chunks";
    document.getElementById("storageDocumentCount").textContent = formatNumber(search.total_indexed_documents) + " documents";
  } catch (error) {
    dot.className = "status-dot offline";
    document.getElementById("systemStatusText").textContent = "Backend unavailable";
    document.getElementById("engineStatusText").textContent = error.message;
  }
}

function initDashboard() {
  document.getElementById("refreshDashboardBtn").addEventListener("click", loadDashboard);
}

async function loadDashboard() {
  try {
    const org = encodeURIComponent(state.organization);
    const responses = await Promise.all([
      fetchJson("/analytics/dashboard?organization_id=" + org),
      fetchJson("/analytics/violations?organization_id=" + org + "&status=OPEN&limit=5"),
      fetchJson("/analytics/anomalies?organization_id=" + org + "&status=OPEN&limit=5"),
      fetchJson("/invoices?organization_id=" + org + "&limit=6"),
      fetchJson("/search/stats"),
      fetchJson("/graph/stats?organization_id=" + org),
    ]);
    const dashboard = responses[0];
    const violations = responses[1].violations || responses[1] || [];
    const anomalies = responses[2].anomalies || responses[2] || [];
    const invoicesPayload = responses[3];
    const search = responses[4];
    const graph = responses[5];

    document.getElementById("kpi-spend").textContent = formatCurrency(dashboard.total_invoice_spend || 0);
    document.getElementById("kpi-invoices").textContent = formatNumber(dashboard.total_invoices);
    document.getElementById("kpi-pos").textContent = formatNumber(dashboard.total_purchase_orders);
    document.getElementById("kpi-violations").textContent = formatNumber(dashboard.open_violations_count);
    document.getElementById("kpi-duplicates").textContent = formatNumber(dashboard.open_duplicates_count);
    document.getElementById("kpi-anomalies").textContent = formatNumber(dashboard.open_anomalies_count);
    document.getElementById("violationCountBadge").textContent = formatNumber(dashboard.open_violations_count) + " open";
    document.getElementById("anomalyCountBadge").textContent = formatNumber((dashboard.open_anomalies_count || 0) + (dashboard.open_duplicates_count || 0)) + " flagged";
    document.getElementById("storageChunkCount").textContent = formatNumber(search.total_chunks) + " chunks";
    document.getElementById("storageDocumentCount").textContent = formatNumber(search.total_indexed_documents) + " documents";
    document.getElementById("storageGraphNodes").textContent = formatNumber(graph.total_nodes) + " nodes";
    document.getElementById("storageGraphEdges").textContent = formatNumber(graph.total_edges) + " relationships";
    document.getElementById("topbarRecordCount").textContent = formatNumber((dashboard.total_invoices || 0) + (dashboard.total_purchase_orders || 0)) + " records";

    renderRecentInvoices(invoicesPayload.invoices || []);
    renderViolations(violations);
    renderAnomalies(anomalies);
    refreshIcons();
  } catch (error) {
    showToast("Dashboard could not load: " + error.message, "error");
  }
}

function renderRecentInvoices(invoices) {
  const body = document.getElementById("recentInvoicesBody");
  if (!invoices.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty-cell">No invoices stored for this organization.</td></tr>';
    return;
  }
  body.innerHTML = invoices.map(function (invoice) {
    return "<tr><td><b>" + escapeHtml(invoice.invoice_number || "No number") + '</b><br><span class="mono">' + escapeHtml(invoice.id) +
      "</span></td><td>" + escapeHtml(invoice.vendor_name || "Unknown vendor") + "</td><td>" + escapeHtml(invoice.invoice_date || "-") +
      '</td><td><span class="status-label ' + statusClass(invoice.payment_status) + '">' + escapeHtml(invoice.payment_status || "unknown") +
      '</span></td><td class="align-right amount">' + formatCurrency(invoice.total_amount, invoice.currency) + "</td></tr>";
  }).join("");
}

function renderViolations(items) {
  const container = document.getElementById("violationsList");
  if (!items.length) {
    container.innerHTML = emptyState("shield-check", "No open rule violations.");
    return;
  }
  container.innerHTML = items.map(function (item) {
    return '<div class="exception-item"><span class="exception-symbol"><i data-lucide="shield-alert"></i></span><div><strong>' +
      escapeHtml(item.rule_name || item.rule_id || "Rule violation") + "</strong><small>" +
      escapeHtml((item.entity_type || "Entity") + " / " + (item.entity_id || "unknown")) +
      '</small></div><span class="count-badge warning">' + escapeHtml(item.severity || "OPEN") + "</span></div>";
  }).join("");
}

function renderAnomalies(items) {
  const container = document.getElementById("anomaliesList");
  if (!items.length) {
    container.innerHTML = emptyState("badge-check", "No active anomalies.");
    return;
  }
  container.innerHTML = items.map(function (item) {
    return '<div class="exception-item"><span class="exception-symbol danger"><i data-lucide="activity"></i></span><div><strong>' +
      escapeHtml(item.anomaly_type || "Anomaly") + "</strong><small>Observed " + formatCurrency(item.observed_value) +
      (item.z_score != null ? " / Z " + escapeHtml(item.z_score) : "") +
      '</small></div><span class="count-badge danger">' + escapeHtml(item.status || "OPEN") + "</span></div>";
  }).join("");
}

function initIngestion() {
  const invoiceButton = document.getElementById("docTypeInvoice");
  const poButton = document.getElementById("docTypePO");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");

  invoiceButton.addEventListener("click", function () {
    state.documentType = "invoice";
    invoiceButton.classList.add("active");
    poButton.classList.remove("active");
  });
  poButton.addEventListener("click", function () {
    state.documentType = "po";
    poButton.classList.add("active");
    invoiceButton.classList.remove("active");
  });
  dropzone.addEventListener("click", function () { fileInput.click(); });
  dropzone.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") fileInput.click();
  });
  dropzone.addEventListener("dragover", function (event) {
    event.preventDefault();
    dropzone.classList.add("dragover");
  });
  dropzone.addEventListener("dragleave", function () { dropzone.classList.remove("dragover"); });
  dropzone.addEventListener("drop", function (event) {
    event.preventDefault();
    dropzone.classList.remove("dragover");
    if (event.dataTransfer.files.length) selectFile(event.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", function (event) {
    if (event.target.files.length) selectFile(event.target.files[0]);
  });
  document.getElementById("uploadBtn").addEventListener("click", processSelectedDocument);
  document.getElementById("toggleJsonBtn").addEventListener("click", function () {
    document.getElementById("rawJsonView").classList.toggle("hidden");
  });
}

function selectFile(file) {
  state.selectedFile = file;
  const label = document.getElementById("selectedFileName");
  label.textContent = file.name + " / " + Math.max(1, Math.round(file.size / 1024)) + " KB";
  label.classList.remove("hidden");
}

async function processSelectedDocument() {
  if (!state.selectedFile) {
    showToast("Choose a PDF or image before starting extraction.", "error");
    return;
  }
  const button = document.getElementById("uploadBtn");
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span><span>Reading and validating...</span>';
  const form = new FormData();
  form.append("file", state.selectedFile);
  try {
    const data = await fetchJson("/finance/process?organization_id=" + encodeURIComponent(state.organization), {
      method: "POST",
      body: form,
    });
    renderExtractionResult(data);
    state.vaultData = {};
    showToast("Document extracted and persisted successfully.");
    loadSystemStatus();
  } catch (error) {
    showToast("Extraction failed: " + error.message, "error");
  } finally {
    button.disabled = false;
    button.innerHTML = original;
    refreshIcons();
  }
}

function fieldValue(field, fallback) {
  if (field && typeof field === "object" && "value" in field) return field.value;
  return field == null ? fallback : field;
}

function renderExtractionResult(data) {
  document.getElementById("ingestionEmptyState").classList.add("hidden");
  document.getElementById("ingestionResultContent").classList.remove("hidden");
  document.getElementById("toggleJsonBtn").classList.remove("hidden");
  document.getElementById("extractionStatusBadge").classList.remove("hidden");
  document.getElementById("rawJsonView").textContent = JSON.stringify(data, null, 2);

  const record = data.invoice || data.purchase_order || data;
  const vendor = fieldValue(record.vendor_name_normalized, null) || fieldValue(record.vendor_name_raw, "Unknown vendor");
  const number = fieldValue(record.invoice_number, null) || fieldValue(record.po_number, "N/A");
  const total = fieldValue(record.total_amount, 0);
  const date = fieldValue(record.invoice_date, null) || fieldValue(record.po_date, "N/A");
  document.getElementById("resVendor").textContent = vendor;
  document.getElementById("resNumber").textContent = number;
  document.getElementById("resTotal").textContent = formatCurrency(total, fieldValue(record.currency, "INR"));
  document.getElementById("resDate").textContent = date;

  const items = record.line_items || [];
  document.getElementById("lineItemsCount").textContent = items.length;
  document.getElementById("lineItemsBody").innerHTML = items.length ? items.map(function (item) {
    return "<tr><td><b>" + escapeHtml(fieldValue(item.description, "Item")) + "</b></td><td class=\"mono\">" +
      escapeHtml(fieldValue(item.product_code, "-")) + '</td><td class="align-right">' +
      escapeHtml(fieldValue(item.quantity, "1")) + '</td><td class="align-right">' +
      formatCurrency(fieldValue(item.unit_price, 0)) + '</td><td class="align-right amount">' +
      formatCurrency(fieldValue(item.total, 0)) + "</td></tr>";
  }).join("") : '<tr><td colspan="5" class="empty-cell">No line items were parsed.</td></tr>';
}

function initDataVault() {
  document.getElementById("refreshDataVaultBtn").addEventListener("click", function () {
    state.vaultData = {};
    loadDataVault();
  });
  document.querySelectorAll(".vault-tab").forEach(function (button) {
    button.addEventListener("click", function () {
      state.vaultType = button.dataset.vault;
      document.querySelectorAll(".vault-tab").forEach(function (item) {
        item.classList.toggle("active", item === button);
      });
      renderVaultTable();
    });
  });
  document.getElementById("vaultSearchInput").addEventListener("input", renderVaultTable);
}

async function loadDataVault() {
  const org = encodeURIComponent(state.organization);
  const body = document.getElementById("dataVaultBody");
  body.innerHTML = '<tr><td class="empty-cell">Loading persistent records...</td></tr>';
  try {
    const responses = await Promise.all([
      fetchJson("/invoices?organization_id=" + org + "&limit=100"),
      fetchJson("/vendors?organization_id=" + org + "&limit=100"),
      fetchJson("/purchase-orders?organization_id=" + org + "&limit=100"),
      fetchJson("/payments?organization_id=" + org + "&limit=100"),
    ]);
    state.vaultData = {
      invoices: responses[0].invoices || [],
      vendors: responses[1].vendors || [],
      "purchase-orders": responses[2].purchase_orders || [],
      payments: responses[3].payments || [],
    };
    document.getElementById("vaultInvoiceCount").textContent = responses[0].total_count || 0;
    document.getElementById("vaultVendorCount").textContent = responses[1].total_count || 0;
    document.getElementById("vaultPoCount").textContent = responses[2].total_count || 0;
    document.getElementById("vaultPaymentCount").textContent = responses[3].total_count || 0;
    document.getElementById("topbarRecordCount").textContent =
      formatNumber((responses[0].total_count || 0) + (responses[2].total_count || 0) + (responses[3].total_count || 0)) + " records";
    renderVaultTable();
  } catch (error) {
    body.innerHTML = '<tr><td class="empty-cell">Could not load stored data: ' + escapeHtml(error.message) + "</td></tr>";
    showToast("Data vault could not load: " + error.message, "error");
  }
}

const vaultColumns = {
  invoices: [
    ["invoice_number", "Invoice"], ["vendor_name", "Vendor"], ["invoice_date", "Date"],
    ["payment_status", "Status"], ["line_items_count", "Lines"], ["total_amount", "Amount"],
  ],
  vendors: [
    ["canonical_name", "Vendor"], ["tax_id", "Tax ID"], ["aliases_count", "Aliases"],
    ["invoices_count", "Invoices"], ["purchase_orders_count", "Purchase orders"], ["id", "Canonical ID"],
  ],
  "purchase-orders": [
    ["po_number", "PO number"], ["vendor_name", "Vendor"], ["po_date", "Date"],
    ["status", "Status"], ["line_items_count", "Lines"], ["total_amount", "Amount"],
  ],
  payments: [
    ["payment_reference", "Reference"], ["payee_name", "Payee"], ["payment_date", "Date"],
    ["payment_method", "Method"], ["status", "Status"], ["amount", "Amount"],
  ],
};

function renderVaultTable() {
  const records = state.vaultData[state.vaultType] || [];
  const query = document.getElementById("vaultSearchInput").value.trim().toLowerCase();
  const visible = records.filter(function (record) {
    return !query || JSON.stringify(record).toLowerCase().includes(query);
  });
  const columns = vaultColumns[state.vaultType];
  document.getElementById("dataVaultHead").innerHTML = "<tr>" + columns.map(function (column, index) {
    return "<th" + (index === columns.length - 1 ? ' class="align-right"' : "") + ">" + escapeHtml(column[1]) + "</th>";
  }).join("") + "</tr>";
  const body = document.getElementById("dataVaultBody");
  if (!visible.length) {
    body.innerHTML = '<tr><td colspan="' + columns.length + '" class="empty-cell">No matching stored records.</td></tr>';
  } else {
    body.innerHTML = visible.map(function (record) {
      return "<tr>" + columns.map(function (column, index) {
        const key = column[0];
        let value = record[key];
        let className = index === columns.length - 1 ? "align-right" : "";
        if (key === "total_amount" || key === "amount") {
          value = formatCurrency(value, record.currency);
          className += " amount";
        } else if (key === "payment_status" || key === "status") {
          value = '<span class="status-label ' + statusClass(value) + '">' + escapeHtml(value || "unknown") + "</span>";
        } else if (key === "id" || key === "tax_id") {
          value = '<span class="mono">' + escapeHtml(value || "-") + "</span>";
        } else {
          value = escapeHtml(value == null || value === "" ? "-" : value);
        }
        return '<td class="' + className.trim() + '">' + value + "</td>";
      }).join("") + "</tr>";
    }).join("");
  }
  document.getElementById("vaultTableMeta").textContent = visible.length + " of " + records.length + " records";
}

function initCopilot() {
  const form = document.getElementById("copilotForm");
  const input = document.getElementById("copilotQuestion");
  document.querySelectorAll(".copilot-chip").forEach(function (button) {
    button.addEventListener("click", function () {
      input.value = button.textContent.trim();
      input.focus();
    });
  });
  document.getElementById("clearContextBtn").addEventListener("click", function () {
    state.copilotContext = null;
    updateContextDisplay();
    showToast("Copilot context has been reset.");
  });
  document.getElementById("evidenceToggleBtn").addEventListener("click", function () {
    document.getElementById("evidenceDrawer").classList.toggle("hidden");
  });
  form.addEventListener("submit", askCopilot);
}

async function askCopilot(event) {
  event.preventDefault();
  const question = document.getElementById("copilotQuestion").value.trim();
  if (!question) return;
  const button = document.getElementById("copilotSubmitBtn");
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span><span>Checking tools...</span>';
  try {
    const data = await fetchJson("/copilot/ask?organization_id=" + encodeURIComponent(state.organization), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: question,
        organization_id: state.organization,
        context: state.copilotContext,
        include_query_plan: document.getElementById("includePlanCheck").checked,
      }),
    });
    state.copilotContext = data.context || state.copilotContext;
    renderCopilotAnswer(data);
    updateContextDisplay();
  } catch (error) {
    showToast("Copilot could not answer: " + error.message, "error");
  } finally {
    button.disabled = false;
    button.innerHTML = original;
    refreshIcons();
  }
}

function renderCopilotAnswer(data) {
  document.getElementById("copilotWelcome").classList.add("hidden");
  document.getElementById("copilotResponseCard").classList.remove("hidden");
  document.getElementById("resIntentBadge").textContent = data.intent || "QUERY";
  document.getElementById("resConfidenceBadge").textContent = "Confidence " + Number(data.confidence == null ? 1 : data.confidence).toFixed(2);
  document.getElementById("resQueryId").textContent = data.query_id || "";
  document.getElementById("copilotAnswerText").textContent = data.answer || "No answer was generated.";

  const metrics = data.metrics || [];
  const strip = document.getElementById("copilotMetricsStrip");
  strip.classList.toggle("hidden", !metrics.length);
  strip.innerHTML = metrics.map(function (metric) {
    const label = metric.name || metric.metric || Object.keys(metric)[0] || "metric";
    const rawValue = metric.value != null ? metric.value : metric.total_spend != null ? metric.total_spend : metric[label];
    return '<span class="metric-pill">' + escapeHtml(label) + ": " + escapeHtml(rawValue == null ? JSON.stringify(metric) : rawValue) + "</span>";
  }).join("");

  const evidence = data.evidence || [];
  document.getElementById("evidenceCount").textContent = evidence.length;
  document.getElementById("evidenceDrawer").innerHTML = evidence.length ? evidence.map(function (item) {
    const detail = item.source_text || (item.metric ? JSON.stringify(item.metric) : item.source_operation || "Structured record");
    return '<div class="evidence-item"><strong>' + escapeHtml(item.source_type || "EVIDENCE") +
      " / confidence " + escapeHtml(item.confidence == null ? "1.0" : item.confidence) +
      "</strong><p>" + escapeHtml(detail) + "</p></div>";
  }).join("") : emptyState("file-question", "No direct evidence records were attached.");

  const plan = document.getElementById("queryPlanDrawer");
  plan.classList.toggle("hidden", !data.query_plan);
  document.getElementById("queryPlanJson").textContent = data.query_plan ? JSON.stringify(data.query_plan, null, 2) : "";
  refreshIcons();
}

function updateContextDisplay() {
  const context = state.copilotContext;
  document.getElementById("ctxLastVendor").textContent = context && (context.last_vendor_name || context.last_vendor_id) || "-";
  document.getElementById("ctxLastDates").textContent = context && context.last_date_range ?
    context.last_date_range.start_date + " to " + context.last_date_range.end_date : "-";
  document.getElementById("ctxLastIntent").textContent = context && context.last_intent || "-";
}

function initInvestigation() {
  const input = document.getElementById("investigationQuestion");
  document.querySelectorAll(".investigate-chip").forEach(function (button) {
    button.addEventListener("click", function () {
      input.value = button.textContent.trim();
      input.focus();
    });
  });
  document.getElementById("investigationForm").addEventListener("submit", runInvestigation);
}

async function runInvestigation(event) {
  event.preventDefault();
  const question = document.getElementById("investigationQuestion").value.trim();
  if (!question) return;
  const button = document.getElementById("investigateSubmitBtn");
  const loading = document.getElementById("investigationLoading");
  button.disabled = true;
  loading.classList.remove("hidden");
  document.getElementById("investigationReportCard").classList.add("hidden");
  try {
    const report = await fetchJson("/investigate?organization_id=" + encodeURIComponent(state.organization), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, organization_id: state.organization, include_trace: true }),
    });
    renderInvestigationReport(report);
  } catch (error) {
    showToast("Investigation failed: " + error.message, "error");
  } finally {
    button.disabled = false;
    loading.classList.add("hidden");
  }
}

function renderInvestigationReport(report) {
  document.getElementById("investigationReportCard").classList.remove("hidden");
  document.getElementById("repType").textContent = report.investigation_type || "INVESTIGATION";
  document.getElementById("repTitle").textContent = report.title || "Investigation report";
  document.getElementById("repId").textContent = report.investigation_id || "";
  document.getElementById("repConfidence").textContent = Number(report.confidence || 0).toFixed(2);
  document.getElementById("repBaselineDates").textContent = report.baseline && report.baseline.period || "-";
  document.getElementById("repBaselineSpend").textContent = formatCurrency(report.baseline && report.baseline.spend);
  document.getElementById("repTargetDates").textContent = report.target && report.target.period || "-";
  document.getElementById("repTargetSpend").textContent = formatCurrency(report.target && report.target.spend);
  const direction = report.change && report.change.direction;
  const prefix = direction === "INCREASE" ? "+" : direction === "DECREASE" ? "-" : "";
  document.getElementById("repDeltaPct").textContent = prefix + (report.change && report.change.percentage || "0%");
  document.getElementById("repDeltaAmount").textContent = prefix + formatCurrency(report.change && report.change.absolute);
  document.getElementById("repSummary").textContent = report.summary || "-";
  document.getElementById("repConclusion").textContent = report.conclusion || "-";

  const drivers = report.drivers || [];
  document.getElementById("repDriversList").innerHTML = drivers.length ? drivers.map(function (driver) {
    return '<article class="driver-item"><div><span class="count-badge neutral">' +
      escapeHtml(driver.type || "DRIVER") + "</span><strong>" + formatCurrency(driver.impact_amount) +
      "</strong></div><p>" + escapeHtml(driver.description || "") + "</p></article>";
  }).join("") : emptyState("equal-approximately", "No specific line-item driver was isolated.");

  const anomalies = report.anomalies || [];
  const anomalyContainer = document.getElementById("repAnomaliesContainer");
  anomalyContainer.classList.toggle("hidden", !anomalies.length);
  document.getElementById("repAnomaliesList").innerHTML = anomalies.map(function (item) {
    return '<div class="exception-item"><span class="exception-symbol danger"><i data-lucide="activity"></i></span><div><strong>' +
      escapeHtml(item.anomaly_type || "Anomaly") + "</strong><small>Observed " + formatCurrency(item.observed_value) +
      "</small></div><span class=\"count-badge danger\">Z " + escapeHtml(item.z_score || "N/A") + "</span></div>";
  }).join("");
  refreshIcons();
}

function initSearchAndGraph() {
  document.getElementById("refreshGraphBtn").addEventListener("click", loadGraphWorkspace);
  document.getElementById("traceGraphBtn").addEventListener("click", traceSelectedVendor);
  document.getElementById("graphVendorInput").addEventListener("change", function () {
    if (this.value) traceSelectedVendor();
  });
  document.getElementById("searchForm").addEventListener("submit", runSemanticSearch);
}

async function loadGraphWorkspace() {
  try {
    const org = encodeURIComponent(state.organization);
    const responses = await Promise.all([
      fetchJson("/graph/stats?organization_id=" + org),
      fetchJson("/vendors?organization_id=" + org + "&limit=100"),
    ]);
    renderGraphStats(responses[0]);
    const select = document.getElementById("graphVendorInput");
    const previous = select.value;
    const vendors = responses[1].vendors || [];
    select.innerHTML = '<option value="">Select a stored vendor</option>' + vendors.map(function (vendor) {
      return '<option value="' + escapeHtml(vendor.id) + '">' + escapeHtml(vendor.canonical_name) + "</option>";
    }).join("");
    if (vendors.length) {
      select.value = vendors.some(function (vendor) { return vendor.id === previous; }) ? previous : vendors[0].id;
      traceSelectedVendor();
    } else {
      renderGraph({ nodes: [], edges: [] });
    }
  } catch (error) {
    showToast("Graph workspace could not load: " + error.message, "error");
  }
}

function renderGraphStats(stats) {
  document.getElementById("graphNodesCount").textContent = formatNumber(stats.total_nodes);
  document.getElementById("graphEdgesCount").textContent = formatNumber(stats.total_edges);
  document.getElementById("graphNodeBreakdown").innerHTML = Object.entries(stats.nodes_by_label || {}).map(function (entry) {
    return '<span class="type-chip">' + escapeHtml(entry[0]) + " " + escapeHtml(entry[1]) + "</span>";
  }).join("") || '<span class="type-chip">No nodes</span>';
  document.getElementById("graphEdgeBreakdown").innerHTML = Object.entries(stats.edges_by_type || {}).map(function (entry) {
    return '<span class="type-chip">' + escapeHtml(entry[0]) + " " + escapeHtml(entry[1]) + "</span>";
  }).join("") || '<span class="type-chip">No edges</span>';
  document.getElementById("storageGraphNodes").textContent = formatNumber(stats.total_nodes) + " nodes";
  document.getElementById("storageGraphEdges").textContent = formatNumber(stats.total_edges) + " relationships";
}

async function traceSelectedVendor() {
  const vendorId = document.getElementById("graphVendorInput").value;
  if (!vendorId) {
    renderGraph({ nodes: [], edges: [] });
    return;
  }
  const button = document.getElementById("traceGraphBtn");
  button.disabled = true;
  try {
    const graph = await fetchJson("/graph/vendor/" + encodeURIComponent(vendorId) + "/network?organization_id=" + encodeURIComponent(state.organization));
    state.graphData = graph;
    document.getElementById("graphTraceResult").textContent = JSON.stringify(graph, null, 2);
    renderGraph(graph);
  } catch (error) {
    renderGraph({ nodes: [], edges: [] });
    showToast("Vendor graph could not be traced: " + error.message, "error");
  } finally {
    button.disabled = false;
  }
}

const graphColors = {
  Vendor: "#087a62",
  VendorAlias: "#67a98e",
  Invoice: "#32718a",
  PurchaseOrder: "#b87312",
  Payment: "#6657a8",
  BankAccount: "#d65f4a",
  TaxIdentifier: "#d65f4a",
};

function graphNodeName(node) {
  const props = node.properties || {};
  return props.canonical_name || props.alias_name || props.invoice_number || props.po_number ||
    props.payment_reference || props.account_number || props.tax_id || node.id;
}

function makeSvgElement(name, attributes) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes || {}).forEach(function (entry) { element.setAttribute(entry[0], entry[1]); });
  return element;
}

function renderGraph(graph) {
  const svg = document.getElementById("graphSvg");
  const empty = document.getElementById("graphEmptyState");
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  svg.innerHTML = "";
  empty.classList.toggle("hidden", nodes.length > 0);
  if (!nodes.length) return;

  const width = Math.max(620, document.getElementById("graphStage").clientWidth || 720);
  const height = 430;
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  const center = { x: width / 2, y: height / 2 };
  const root = nodes.find(function (node) { return node.label === "Vendor"; }) || nodes[0];
  const positions = {};
  positions[root.id] = center;
  const others = nodes.filter(function (node) { return node.id !== root.id; });
  others.forEach(function (node, index) {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index / Math.max(others.length, 1));
    const ring = others.length > 8 && index % 2 ? 132 : 168;
    positions[node.id] = {
      x: center.x + Math.cos(angle) * Math.min(ring, width * .31),
      y: center.y + Math.sin(angle) * Math.min(ring, height * .34),
    };
  });

  const edgeLayer = makeSvgElement("g", { class: "edge-layer" });
  const labelLayer = makeSvgElement("g", { class: "edge-label-layer" });
  const nodeLayer = makeSvgElement("g", { class: "node-layer" });
  svg.appendChild(edgeLayer);
  svg.appendChild(labelLayer);
  svg.appendChild(nodeLayer);

  edges.forEach(function (edge) {
    const source = positions[edge.source_id];
    const target = positions[edge.target_id];
    if (!source || !target) return;
    const line = makeSvgElement("line", {
      x1: source.x, y1: source.y, x2: target.x, y2: target.y,
      class: "graph-edge",
      "data-source": edge.source_id,
      "data-target": edge.target_id,
    });
    edgeLayer.appendChild(line);
    const label = makeSvgElement("text", {
      x: (source.x + target.x) / 2,
      y: (source.y + target.y) / 2 - 5,
      class: "graph-edge-label",
      "text-anchor": "middle",
    });
    label.textContent = edge.relation_type;
    labelLayer.appendChild(label);
  });

  nodes.forEach(function (node) {
    const position = positions[node.id];
    const group = makeSvgElement("g", {
      class: "graph-node",
      transform: "translate(" + position.x + " " + position.y + ")",
      "data-id": node.id,
    });
    const radius = node.id === root.id ? 24 : 18;
    group.appendChild(makeSvgElement("circle", {
      r: radius,
      fill: graphColors[node.label] || "#84938c",
    }));
    const label = makeSvgElement("text", { y: radius + 15, "text-anchor": "middle" });
    const displayName = graphNodeName(node);
    label.textContent = displayName.length > 22 ? displayName.slice(0, 20) + "…" : displayName;
    group.appendChild(label);
    group.addEventListener("mouseenter", function (event) { showGraphTooltip(event, node); });
    group.addEventListener("mouseleave", hideGraphTooltip);
    group.addEventListener("click", function () { selectGraphNode(node, edges, svg); });
    nodeLayer.appendChild(group);
  });
}

function showGraphTooltip(event, node) {
  const tooltip = document.getElementById("graphTooltip");
  const stageRect = document.getElementById("graphStage").getBoundingClientRect();
  tooltip.innerHTML = "<strong>" + escapeHtml(graphNodeName(node)) + "</strong><span>" +
    escapeHtml(node.label + " / " + node.id) + "</span>";
  tooltip.style.left = Math.min(event.clientX - stageRect.left + 12, stageRect.width - 205) + "px";
  tooltip.style.top = Math.max(8, event.clientY - stageRect.top - 12) + "px";
  tooltip.classList.remove("hidden");
}

function hideGraphTooltip() {
  document.getElementById("graphTooltip").classList.add("hidden");
}

function selectGraphNode(node, edges, svg) {
  const connected = new Set([node.id]);
  edges.forEach(function (edge) {
    if (edge.source_id === node.id) connected.add(edge.target_id);
    if (edge.target_id === node.id) connected.add(edge.source_id);
  });
  svg.querySelectorAll(".graph-node").forEach(function (element) {
    element.classList.toggle("selected", element.dataset.id === node.id);
    element.classList.toggle("dimmed", !connected.has(element.dataset.id));
  });
  svg.querySelectorAll(".graph-edge").forEach(function (element) {
    const touches = element.dataset.source === node.id || element.dataset.target === node.id;
    element.classList.toggle("dimmed", !touches);
  });
  const props = node.properties || {};
  document.getElementById("selectedGraphNode").textContent = graphNodeName(node);
  document.getElementById("selectedGraphNodeMeta").textContent =
    node.label + " / " + Object.entries(props).filter(function (entry) { return entry[0] !== "organization_id" && entry[1] != null; })
      .slice(0, 3).map(function (entry) { return entry[0] + ": " + entry[1]; }).join(" / ");
}

async function runSemanticSearch(event) {
  event.preventDefault();
  const query = document.getElementById("searchInput").value.trim();
  if (!query) return;
  const container = document.getElementById("searchResults");
  container.innerHTML = emptyState("loader-circle", "Searching stored evidence...");
  refreshIcons();
  try {
    const data = await fetchJson("/search/semantic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query, organization_id: state.organization, top_k: 6 }),
    });
    const results = data.results || [];
    container.innerHTML = results.length ? results.map(function (result) {
      return '<article class="search-result"><div class="search-result-head"><span>DOC ' +
        escapeHtml(result.document_id || "-") + "</span><span>SCORE <b>" +
        Number(result.similarity_score || 0).toFixed(3) + "</b></span></div><p>" +
        escapeHtml(result.text || "") + "</p></article>";
    }).join("") : emptyState("file-question", "No matching evidence was found.");
    refreshIcons();
  } catch (error) {
    container.innerHTML = emptyState("circle-alert", "Search failed: " + error.message);
    refreshIcons();
  }
}

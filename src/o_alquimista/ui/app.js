"use strict";

const ui = {
  loading: document.querySelector("#loading"),
  empty: document.querySelector("#empty-state"),
  dashboard: document.querySelector("#dashboard"),
  campaignSelect: document.querySelector("#campaign-select"),
  archiveInput: document.querySelector("#archive-input"),
  importButton: document.querySelector("#import-button"),
  importButtonLabel: document.querySelector("#import-button-label"),
  toast: document.querySelector("#toast"),
};

const categoryLabels = {
  cultivation: "Cultivo",
  mixing: "Mistura",
  packaging: "Embalagem",
  storage: "Armazenamento",
  utility: "Utilidades",
  waste: "Resíduos",
  fixture: "Estrutura",
  unknown: "Desconhecido",
};

const confidenceLabels = {
  high: "alta",
  medium: "média",
  low: "baixa",
  unavailable: "indisponível",
};

const priorityLabels = {
  critical: "crítica",
  high: "alta",
  medium: "média",
  low: "baixa",
  informational: "informativa",
};

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function shortId(value) {
  if (!value) return "sem identificação";
  const text = String(value);
  return text.length > 20 ? `${text.slice(0, 12)}…${text.slice(-5)}` : text;
}

function money(value) {
  if (value === null || value === undefined || value === "") return "indisponível";
  const negative = String(value).startsWith("-");
  const unsigned = negative ? String(value).slice(1) : String(value);
  const [wholeRaw, decimalRaw = ""] = unsigned.split(".");
  const whole = wholeRaw.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const decimals = `${decimalRaw}00`.slice(0, 2);
  return `${negative ? "-" : ""}$${whole},${decimals}`;
}

function quantity(value, singular, plural) {
  if (value === null || value === undefined) return `— ${plural}`;
  return `${value} ${Number(value) === 1 ? singular : plural}`;
}

function showToast(message, isError = false) {
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", isError);
  ui.toast.classList.remove("hidden");
  window.setTimeout(() => ui.toast.classList.add("hidden"), 4800);
}

function setView(name) {
  ui.loading.classList.toggle("hidden", name !== "loading");
  ui.empty.classList.toggle("hidden", name !== "empty");
  ui.dashboard.classList.toggle("hidden", name !== "dashboard");
}

function renderCampaigns(data) {
  clear(ui.campaignSelect);
  for (const campaign of data.campaigns || []) {
    const option = document.createElement("option");
    option.value = campaign.campaign_id;
    const confidence = campaign.confidence || "unknown";
    option.textContent =
      `${campaign.display_name || shortId(campaign.campaign_id)} · ` +
      `${confidenceLabels[confidence] || confidence}`;
    option.selected = campaign.campaign_id === data.selected_campaign_id;
    ui.campaignSelect.appendChild(option);
  }
  ui.campaignSelect.disabled = (data.campaigns || []).length < 2;
}

function renderMetrics(data) {
  document.querySelector("#metric-liquidity").textContent = money(
    data.finance.liquid_cash_estimate,
  );
  document.querySelector("#metric-networth").textContent = money(data.finance.networth);
  document.querySelector("#metric-operations").textContent =
    `${data.operations.equipment_count}`;
  document.querySelector("#metric-operations-detail").textContent =
    `${data.operations.active_count} ativos · ${data.operations.idle_count} ociosos · ` +
    `${data.operations.unknown_state_count} sem estado`;
  document.querySelector("#metric-occupancy").textContent =
    data.operations.occupancy_percent === null
      ? "—"
      : `${data.operations.occupancy_percent}%`;
  document.querySelector("#metric-occupancy-detail").textContent =
    `${data.operations.occupied_slots} de ${data.operations.observed_slots} slots`;
}

function renderMessage(data) {
  document.querySelector("#message-eyebrow").textContent = data.message.eyebrow;
  document.querySelector("#message-title").textContent = data.message.title;
  document.querySelector("#message-body").textContent = data.message.body;
  document.querySelector("#snapshot-day").textContent =
    data.snapshot.elapsed_days === null
      ? "dia indisponível"
      : `dia ${data.snapshot.elapsed_days}`;
  document.querySelector("#game-version").textContent =
    `jogo ${data.snapshot.game_version || "versão desconhecida"}`;
  document.querySelector("#confidence-chip").textContent =
    `confiança ${
      confidenceLabels[data.campaign?.confidence] ||
      data.campaign?.confidence ||
      "indisponível"
    }`;
}

function renderRecommendations(data) {
  const container = document.querySelector("#recommendations");
  clear(container);
  const recommendations = data.recommendations || [];
  document.querySelector("#recommendation-count").textContent = recommendations.length;
  if (!recommendations.length) {
    const empty = element("article", "recommendation");
    empty.appendChild(element("h3", "", "Nenhum alerta prioritário"));
    empty.appendChild(
      element(
        "p",
        "",
        "A operação não acionou nenhuma regra local. Continue coletando snapshots.",
      ),
    );
    container.appendChild(empty);
    return;
  }
  for (const item of recommendations) {
    const card = element(
      "article",
      `recommendation priority-${item.priority || "low"}`,
    );
    const head = element("div", "recommendation-head");
    head.appendChild(element("h3", "", item.title));
    head.appendChild(
      element(
        "span",
        "priority-badge",
        priorityLabels[item.priority] || item.priority,
      ),
    );
    card.appendChild(head);
    card.appendChild(element("p", "", item.explanation));
    container.appendChild(card);
  }
}

function renderCategories(data) {
  const container = document.querySelector("#category-bars");
  clear(container);
  const categories = Object.entries(data.operations.categories || {});
  const maximum = Math.max(...categories.map(([, count]) => count), 1);
  for (const [category, count] of categories) {
    const row = element("div", "category-row");
    row.appendChild(element("span", "", categoryLabels[category] || category));
    const track = element("div", "bar-track");
    const fill = element("div", "bar-fill");
    fill.style.width = `${Math.max(5, (count / maximum) * 100)}%`;
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(element("strong", "", count));
    container.appendChild(row);
  }
}

function renderProperties(data) {
  const container = document.querySelector("#property-grid");
  clear(container);
  document.querySelector("#property-count").textContent = data.properties.length;
  for (const property of data.properties) {
    const card = element("article", "property-card");
    card.appendChild(element("h3", "", property.name));
    const meta = element("div", "property-meta");
    meta.appendChild(
      element("span", "", quantity(property.object_count, "objeto", "objetos")),
    );
    meta.appendChild(
      element(
        "span",
        "",
        quantity(property.employee_count, "funcionário", "funcionários"),
      ),
    );
    card.appendChild(meta);
    const occupancy = element("div", "occupancy");
    occupancy.appendChild(element("span", "", "Ocupação observada"));
    occupancy.appendChild(
      element(
        "strong",
        "",
        property.occupancy_percent === null ? "—" : `${property.occupancy_percent}%`,
      ),
    );
    card.appendChild(occupancy);
    const track = element("div", "bar-track");
    const fill = element("div", "bar-fill");
    fill.style.width = `${property.occupancy_percent || 0}%`;
    track.appendChild(fill);
    card.appendChild(track);
    const tags = element("div", "category-tags");
    for (const [category, count] of Object.entries(property.categories || {})) {
      tags.appendChild(
        element(
          "span",
          "category-tag",
          `${categoryLabels[category] || category} ${count}`,
        ),
      );
    }
    card.appendChild(tags);
    container.appendChild(card);
  }
}

function renderTimeline(data) {
  const container = document.querySelector("#timeline");
  clear(container);
  const entries = [...(data.timeline || [])].reverse().slice(0, 6);
  for (const entry of entries) {
    const row = element("article", "timeline-entry");
    row.appendChild(element("span", "timeline-dot"));
    const copy = element("div", "");
    copy.appendChild(
      element(
        "strong",
        "",
        `Dia ${entry.observable_game_moment?.elapsed_days ?? "—"}`,
      ),
    );
    copy.appendChild(
      element(
        "small",
        "",
        `${entry.operational_summary?.equipment ?? "—"} objetos observados · ` +
        `${entry.milestones?.length ?? 0} marcos`,
      ),
    );
    row.appendChild(copy);
    row.appendChild(
      element("small", "", money(entry.financial_summary?.networth)),
    );
    container.appendChild(row);
  }
}

function render(data) {
  renderCampaigns(data);
  if (data.status !== "ready") {
    setView("empty");
    return;
  }
  renderMessage(data);
  renderMetrics(data);
  renderRecommendations(data);
  renderCategories(data);
  renderProperties(data);
  renderTimeline(data);
  setView("dashboard");
}

async function loadDashboard(campaignId = null) {
  setView("loading");
  const query = campaignId
    ? `?campaign_id=${encodeURIComponent(campaignId)}`
    : "";
  try {
    const response = await fetch(`/api/dashboard${query}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "Falha na análise.");
    render(data);
  } catch (error) {
    setView("empty");
    showToast(error.message || "Não foi possível carregar a Câmara.", true);
  }
}

async function importArchive(file) {
  if (!file) return;
  ui.importButton.disabled = true;
  ui.importButtonLabel.textContent = "Analisando…";
  const form = new FormData();
  form.append("archive", file, file.name);
  try {
    const response = await fetch("/api/import", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "Falha na importação.");
    render(data.dashboard);
    showToast(
      data.import.deduplicated
        ? "Este export já estava no grimório."
        : "Save analisado. O Conselho foi atualizado.",
    );
  } catch (error) {
    showToast(error.message || "Não foi possível importar o save.", true);
  } finally {
    ui.importButton.disabled = false;
    ui.importButtonLabel.textContent = "Importar save";
    ui.archiveInput.value = "";
  }
}

ui.importButton.addEventListener("click", () => ui.archiveInput.click());
for (const trigger of document.querySelectorAll(".import-trigger")) {
  trigger.addEventListener("click", () => ui.archiveInput.click());
}
ui.archiveInput.addEventListener("change", () => importArchive(ui.archiveInput.files[0]));
ui.campaignSelect.addEventListener("change", () =>
  loadDashboard(ui.campaignSelect.value),
);

loadDashboard();

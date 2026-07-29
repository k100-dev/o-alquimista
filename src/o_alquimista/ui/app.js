"use strict";

const ui = {
  loading: document.querySelector("#loading"),
  empty: document.querySelector("#empty-state"),
  dashboard: document.querySelector("#dashboard"),
  campaignSelect: document.querySelector("#campaign-select"),
  baselineSelect: document.querySelector("#baseline-select"),
  archiveInput: document.querySelector("#archive-input"),
  importButton: document.querySelector("#import-button"),
  importButtonLabel: document.querySelector("#import-button-label"),
  compareButton: document.querySelector("#compare-button"),
  toast: document.querySelector("#toast"),
  helpDialog: document.querySelector("#help-dialog"),
};

const categoryLabels = {
  cultivation: "Cultivo",
  mixing: "Mistura",
  processing: "Processamento",
  packaging: "Embalagem",
  storage: "Armazenamento",
  utility: "Utilidades",
  waste: "Resíduos",
  fixture: "Móveis e apoio",
  unknown: "Ainda não classificado",
};

const roleLabels = {
  botanist: "Botânico",
  chemist: "Químico",
  packager: "Empacotador",
  handler: "Transportador",
  cleaner: "Limpeza",
};

const availabilityLabels = {
  finance: "Finanças",
  products: "Produtos",
  inventory: "Estoque",
  properties: "Propriedades",
  employees: "Equipe",
  vehicles: "Veículos",
  businesses: "Negócios",
  npcs: "Rede de contatos",
  progression: "Progressão",
  game: "Tempo de jogo",
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

const helpContent = {
  overview: {
    title: "Como ler a Câmara",
    body: "Esta tela transforma um export do save em decisões práticas. Ela não acompanha o jogo em tempo real.",
    details: [
      "Fato observado: está diretamente no save.",
      "Cálculo: combina valores observados sem adivinhar.",
      "Inferência: hipótese sinalizada com confiança e limitações.",
      "Ausente: o Alquimista prefere dizer “não sei” a inventar zero.",
    ],
  },
  liquidity: {
    title: "Liquidez observada",
    body: "Dinheiro que o save permite tratar como disponível agora, combinando saldo online e dinheiro físico detectado.",
    details: ["Não é lucro.", "Não inclui automaticamente o valor do estoque.", "Serve para avaliar folga antes de comprar."],
  },
  networth: {
    title: "Patrimônio",
    body: "Valor agregado informado pelo próprio jogo para o estado atual da campanha.",
    details: ["Pode subir após expansão.", "Uma queda pode ser compra ou consumo, não necessariamente prejuízo.", "Compare exports para entender a direção."],
  },
  productive: {
    title: "Base produtiva",
    body: "Quantidade de equipamentos reconhecidos que participam de cultivo, mistura, processamento ou embalagem.",
    details: ["Não inclui prateleiras e móveis.", "Não mede unidades por hora.", "Ativo/ocioso só aparece quando o save expõe esse estado."],
  },
  storage: {
    title: "Folga de armazenamento",
    body: "Percentual de compartimentos observados que ainda estão livres.",
    details: ["É uma amostra do armazenamento legível.", "Não representa o espaço físico do cômodo.", "Folga baixa pode bloquear o fluxo."],
  },
};

let currentDashboard = null;

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
  if (!value) return "export sem identificação forte";
  const text = String(value);
  return text.length > 18 ? `${text.slice(0, 10)}…${text.slice(-4)}` : text;
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

function signedMoney(value) {
  if (value === null || value === undefined) return "—";
  const text = money(value);
  return String(value).startsWith("-") ? text : `+${text}`;
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

function openHelp(key = "overview") {
  const help = helpContent[key] || helpContent.overview;
  document.querySelector("#help-title").textContent = help.title;
  document.querySelector("#help-body").textContent = help.body;
  const details = document.querySelector("#help-details");
  clear(details);
  for (const text of help.details) details.appendChild(element("p", "", text));
  ui.helpDialog.showModal();
}

function renderCampaigns(data) {
  clear(ui.campaignSelect);
  for (const campaign of data.campaigns || []) {
    const option = document.createElement("option");
    option.value = campaign.campaign_id;
    option.textContent =
      `${campaign.display_name || shortId(campaign.campaign_id)} · ` +
      `${confidenceLabels[campaign.confidence] || campaign.confidence}`;
    option.selected = campaign.campaign_id === data.selected_campaign_id;
    ui.campaignSelect.appendChild(option);
  }
  ui.campaignSelect.disabled = (data.campaigns || []).length < 2;

  clear(ui.baselineSelect);
  const related = data.related_exports || [];
  for (const item of related) {
    const option = document.createElement("option");
    option.value = item.campaign_id;
    const moment = item.moment || {};
    option.textContent =
      `Dia ${moment.elapsed_days ?? "—"} ${moment.time_label || ""} · ` +
      `${item.shared_signal_count} sinais em comum`;
    ui.baselineSelect.appendChild(option);
  }
  ui.baselineSelect.disabled = related.length === 0;
  ui.compareButton.disabled = related.length === 0;
  document.querySelector("#comparison-empty").textContent = related.length
    ? `${related.length} export(s) relacionado(s) disponível(is) para comparação exploratória.`
    : "Importe outro momento da campanha para liberar a comparação.";
}

function renderMessage(data) {
  document.querySelector("#message-eyebrow").textContent = data.message.eyebrow;
  document.querySelector("#message-title").textContent = data.message.title;
  document.querySelector("#message-body").textContent = data.message.body;
  document.querySelector("#snapshot-explanation").textContent = data.snapshot.explanation;
  document.querySelector("#snapshot-day").textContent =
    data.snapshot.elapsed_days === null ? "dia indisponível" : `dia ${data.snapshot.elapsed_days}`;
  document.querySelector("#snapshot-time").textContent =
    data.snapshot.moment?.time_label || "hora indisponível";
  document.querySelector("#game-version").textContent =
    `jogo ${data.snapshot.game_version || "versão desconhecida"}`;
  document.querySelector("#confidence-chip").textContent =
    `identidade ${confidenceLabels[data.campaign?.confidence] || "indisponível"}`;
}

function renderMetrics(data) {
  document.querySelector("#metric-liquidity").textContent = money(data.finance.liquid_cash_estimate);
  document.querySelector("#metric-networth").textContent = money(data.finance.networth);
  document.querySelector("#metric-operations").textContent = data.operations.productive_count;
  document.querySelector("#metric-operations-detail").textContent =
    `${data.operations.storage_count} armazenamento · ${data.operations.support_count} apoio`;
  const occupancy = data.operations.occupancy_percent;
  document.querySelector("#metric-occupancy").textContent =
    occupancy === null ? "indisponível" : `${100 - occupancy}%`;
  document.querySelector("#metric-occupancy-detail").textContent =
    occupancy === null
      ? "sem compartimentos suficientes para medir"
      : `${data.operations.observed_slots - data.operations.occupied_slots} de ${data.operations.observed_slots} livres`;
}

function renderDiagnostic(data) {
  const diagnostic = data.diagnostic;
  const ring = document.querySelector("#decision-score");
  ring.style.setProperty("--score", diagnostic.decision_readiness_score);
  ring.querySelector("strong").textContent = diagnostic.decision_readiness_score;
  document.querySelector("#diagnostic-title").textContent = diagnostic.title;
  document.querySelector("#diagnostic-explanation").textContent = diagnostic.explanation;
  const container = document.querySelector("#diagnostic-pillars");
  clear(container);
  for (const pillar of diagnostic.pillars) {
    const card = element("article", `pillar tone-${pillar.tone}`);
    const header = element("div", "pillar-head");
    header.appendChild(element("strong", "", pillar.label));
    header.appendChild(element("span", "", pillar.score === null ? "—" : `${pillar.score}%`));
    card.appendChild(header);
    const track = element("div", "bar-track");
    const fill = element("div", "bar-fill");
    fill.style.width = `${pillar.score || 0}%`;
    track.appendChild(fill);
    card.appendChild(track);
    card.appendChild(element("p", "", pillar.summary));
    const details = element("details", "micro-details");
    details.appendChild(element("summary", "", "O que isso quer dizer?"));
    details.appendChild(element("p", "", pillar.meaning));
    card.appendChild(details);
    container.appendChild(card);
  }
}

function renderActionPlan(data) {
  const container = document.querySelector("#action-plan");
  clear(container);
  const actions = data.action_plan || [];
  document.querySelector("#action-count").textContent = actions.length;
  for (const item of actions) {
    const card = element("article", "action-card");
    card.appendChild(element("span", "action-rank", item.rank));
    card.appendChild(element("p", "action-kicker", `Confiança ${confidenceLabels[item.confidence] || item.confidence}`));
    card.appendChild(element("h3", "", item.title));
    card.appendChild(element("p", "action-command", item.action));
    const why = element("div", "action-explain");
    why.appendChild(element("strong", "", "Por quê"));
    why.appendChild(element("p", "", item.why));
    card.appendChild(why);
    const success = element("div", "success-box");
    success.appendChild(element("span", "", "✓ Sinal de conclusão"));
    success.appendChild(element("p", "", item.success));
    card.appendChild(success);
    card.appendChild(element("small", "", item.impact));
    container.appendChild(card);
  }
}

function renderRecommendations(data) {
  const container = document.querySelector("#recommendations");
  clear(container);
  const recommendations = data.recommendations || [];
  document.querySelector("#recommendation-count").textContent = recommendations.length;
  if (!recommendations.length) {
    const empty = element("article", "recommendation");
    empty.appendChild(element("h3", "", "Nenhum alerta prioritário"));
    empty.appendChild(element("p", "", "O save não acionou nenhuma regra crítica."));
    container.appendChild(empty);
    return;
  }
  for (const item of recommendations) {
    const card = element("article", `recommendation priority-${item.priority || "low"}`);
    const head = element("div", "recommendation-head");
    head.appendChild(element("h3", "", item.title));
    head.appendChild(element("span", "priority-badge", priorityLabels[item.priority] || item.priority));
    card.appendChild(head);
    card.appendChild(element("p", "", item.explanation));
    if ((item.limitations || []).length || (item.missing_information || []).length) {
      const details = element("details", "recommendation-details");
      details.appendChild(element("summary", "", "Limites desta recomendação"));
      for (const text of [...(item.limitations || []), ...(item.missing_information || [])]) {
        details.appendChild(element("p", "", text));
      }
      card.appendChild(details);
    }
    container.appendChild(card);
  }
}

function renderAvailability(data) {
  const summary = data.availability;
  document.querySelector("#coverage-badge").textContent =
    summary.coverage_percent === null ? "—" : `${summary.coverage_percent}%`;
  const container = document.querySelector("#availability-list");
  clear(container);
  for (const item of summary.sections) {
    const row = element("div", `availability-row state-${item.state}`);
    row.appendChild(element("span", "availability-dot"));
    const copy = element("div", "");
    copy.appendChild(element("strong", "", availabilityLabels[item.section] || item.section));
    copy.appendChild(
      element(
        "small",
        "",
        item.state === "observed" ? "Dados observados no export" : item.explanation || "Informação indisponível",
      ),
    );
    row.appendChild(copy);
    row.appendChild(element("span", "availability-state", item.state === "observed" ? "observado" : item.state));
    container.appendChild(row);
  }
}

function renderOperations(data) {
  const operations = data.operations;
  const summary = document.querySelector("#operation-summary");
  clear(summary);
  const cards = [
    ["Produtivos", operations.productive_count, "cultivam, misturam, processam ou embalam"],
    ["Armazenamento", operations.storage_count, "prateleiras e recipientes reconhecidos"],
    ["Apoio", operations.support_count, "móveis, utilidades e resíduos"],
    ["Ainda não classificados", operations.unclassified_count, "itens preservados sem significado inventado"],
  ];
  for (const [label, value, explanation] of cards) {
    const card = element("article", "summary-card");
    card.appendChild(element("strong", "", value));
    card.appendChild(element("span", "", label));
    card.appendChild(element("small", "", explanation));
    summary.appendChild(card);
  }

  const container = document.querySelector("#category-bars");
  clear(container);
  const categories = Object.entries(operations.categories || {});
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
    card.appendChild(element("p", "property-profile", property.profile));
    card.appendChild(element("h3", "", property.name));
    const functions = element("div", "property-functions");
    for (const [label, value] of [
      ["Produtivos", property.productive_count],
      ["Armazenamento", property.storage_count],
      ["Apoio", property.support_count],
    ]) {
      const item = element("div", "");
      item.appendChild(element("strong", "", value));
      item.appendChild(element("span", "", label));
      functions.appendChild(item);
    }
    card.appendChild(functions);
    const meta = element("div", "property-meta");
    meta.appendChild(element("span", "", quantity(property.object_count, "objeto total", "objetos totais")));
    meta.appendChild(element("span", "", quantity(property.employee_count, "funcionário", "funcionários")));
    card.appendChild(meta);
    if (property.occupancy_percent !== null) {
      const occupancy = element("div", "occupancy");
      occupancy.appendChild(element("span", "", "Compartimentos ocupados"));
      occupancy.appendChild(element("strong", "", `${property.occupancy_percent}%`));
      card.appendChild(occupancy);
      const track = element("div", "bar-track");
      const fill = element("div", "bar-fill");
      fill.style.width = `${property.occupancy_percent}%`;
      track.appendChild(fill);
      card.appendChild(track);
    }
    const roles = element("div", "category-tags");
    for (const [role, count] of Object.entries(property.employee_roles || {})) {
      roles.appendChild(element("span", "category-tag role-tag", `${roleLabels[role] || role} ${count}`));
    }
    if (property.trackable_state_count) {
      roles.appendChild(element("span", "category-tag", `${property.active_count} ativos · ${property.idle_count} ociosos`));
    }
    card.appendChild(roles);
    container.appendChild(card);
  }
}

function renderPortfolio(data) {
  const portfolio = data.portfolio;
  const summary = document.querySelector("#portfolio-summary");
  clear(summary);
  const entries = [
    [portfolio.discovered_count, "produtos descobertos"],
    [portfolio.recipe_count, "receitas conhecidas"],
    [portfolio.sellable_product_count, "produtos em estoque com preço conhecido"],
    [money(portfolio.inventory_reference_value), "valor de referência do estoque"],
  ];
  for (const [value, label] of entries) {
    const card = element("article", "portfolio-stat");
    card.appendChild(element("strong", "", value));
    card.appendChild(element("span", "", label));
    summary.appendChild(card);
  }
  const list = document.querySelector("#product-list");
  clear(list);
  for (const item of portfolio.top_inventory || []) {
    const row = element("article", "product-row");
    const copy = element("div", "");
    copy.appendChild(element("strong", "", item.label));
    copy.appendChild(element("small", "", `${item.quantity} unidades · referência ${money(item.reference_price)}`));
    row.appendChild(copy);
    row.appendChild(element("strong", "", money(item.reference_value)));
    list.appendChild(row);
  }
  list.appendChild(element("p", "data-note", portfolio.note));
}

function renderWorkforce(data) {
  const workforce = data.workforce;
  const container = document.querySelector("#workforce-content");
  clear(container);
  const overview = element("article", "workforce-overview");
  overview.appendChild(element("strong", "large-number", workforce.employee_count));
  overview.appendChild(element("h3", "", "funcionários observados"));
  overview.appendChild(
    element(
      "p",
      "muted",
      `${workforce.staffed_productive_property_count} de ${workforce.productive_property_count} bases produtivas têm equipe.`,
    ),
  );
  overview.appendChild(element("small", "", workforce.note));
  container.appendChild(overview);
  const roles = element("article", "role-panel");
  roles.appendChild(element("h3", "", "Funções detectadas"));
  for (const [role, count] of Object.entries(workforce.roles || {})) {
    const row = element("div", "role-row");
    row.appendChild(element("span", "", roleLabels[role] || role));
    row.appendChild(element("strong", "", count));
    roles.appendChild(row);
  }
  if (workforce.unstaffed_productive_properties.length) {
    roles.appendChild(
      element(
        "p",
        "warning-note",
        `Sem equipe observada: ${workforce.unstaffed_productive_properties.join(", ")}.`,
      ),
    );
  }
  container.appendChild(roles);
}

function renderTimeline(data) {
  const container = document.querySelector("#timeline");
  clear(container);
  const entries = [...(data.timeline || [])].reverse().slice(0, 6);
  for (const entry of entries) {
    const row = element("article", "timeline-entry");
    row.appendChild(element("span", "timeline-dot"));
    const copy = element("div", "");
    copy.appendChild(element("strong", "", `Dia ${entry.observable_game_moment?.elapsed_days ?? "—"}`));
    copy.appendChild(
      element(
        "small",
        "",
        `${entry.operational_summary?.equipment ?? "—"} objetos observados · ${entry.milestones?.length ?? 0} marcos`,
      ),
    );
    row.appendChild(copy);
    row.appendChild(element("small", "", money(entry.financial_summary?.networth)));
    container.appendChild(row);
  }
}

function renderComparison(data) {
  const result = document.querySelector("#comparison-result");
  clear(result);
  document.querySelector("#comparison-empty").classList.add("hidden");
  result.classList.remove("hidden");
  const hero = element("article", `comparison-verdict tone-${data.verdict.tone}`);
  hero.appendChild(element("p", "eyebrow", "Leitura comparativa"));
  hero.appendChild(element("h3", "", data.verdict.title));
  hero.appendChild(element("p", "", data.verdict.body));
  hero.appendChild(element("small", "", data.caution));
  result.appendChild(hero);

  const financial = element("div", "comparison-grid");
  for (const item of data.financial_changes.filter((row) => row.status === "changed")) {
    const card = element("article", "delta-card");
    card.appendChild(element("span", "", item.label));
    card.appendChild(element("strong", "", signedMoney(item.absolute_change)));
    card.appendChild(
      element(
        "small",
        "",
        item.percentage_change === null ? "percentual indisponível" : `${item.percentage_change}%`,
      ),
    );
    financial.appendChild(card);
  }
  for (const item of data.operational_sections.slice(0, 4)) {
    const card = element("article", "delta-card operational");
    card.appendChild(element("span", "", item.label));
    card.appendChild(
      element(
        "strong",
        "",
        `${item.changed_count} ${item.changed_count === 1 ? "mudança" : "mudanças"}`,
      ),
    );
    card.appendChild(
      element("small", "", `+${item.added_count} · −${item.removed_count} · ${item.updated_count} alteradas`),
    );
    financial.appendChild(card);
  }
  result.appendChild(financial);
}

function render(data) {
  currentDashboard = data;
  renderCampaigns(data);
  if (data.status !== "ready") {
    setView("empty");
    return;
  }
  renderMessage(data);
  renderMetrics(data);
  renderDiagnostic(data);
  renderActionPlan(data);
  renderRecommendations(data);
  renderAvailability(data);
  renderOperations(data);
  renderProperties(data);
  renderPortfolio(data);
  renderWorkforce(data);
  renderTimeline(data);
  document.querySelector("#comparison-result").classList.add("hidden");
  document.querySelector("#comparison-empty").classList.remove("hidden");
  setView("dashboard");
}

async function loadDashboard(campaignId = null) {
  setView("loading");
  const query = campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : "";
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

async function compareCampaigns() {
  if (!currentDashboard || !ui.baselineSelect.value) return;
  ui.compareButton.disabled = true;
  ui.compareButton.textContent = "Comparando…";
  const query = new URLSearchParams({
    current_campaign_id: currentDashboard.selected_campaign_id,
    baseline_campaign_id: ui.baselineSelect.value,
  });
  try {
    const response = await fetch(`/api/comparison?${query}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "Falha na comparação.");
    renderComparison(data);
  } catch (error) {
    showToast(error.message || "Não foi possível comparar os exports.", true);
  } finally {
    ui.compareButton.disabled = false;
    ui.compareButton.textContent = "Comparar momentos";
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
    showToast(data.import.deduplicated ? "Este export já estava no grimório." : "Save analisado. O Conselho foi atualizado.");
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
document.querySelector("#glossary-button").addEventListener("click", () => openHelp("overview"));
document.querySelector("#help-close").addEventListener("click", () => ui.helpDialog.close());
ui.helpDialog.addEventListener("click", (event) => {
  if (event.target === ui.helpDialog) ui.helpDialog.close();
});
for (const button of document.querySelectorAll(".help-button")) {
  button.addEventListener("click", () => openHelp(button.dataset.help));
}
ui.archiveInput.addEventListener("change", () => importArchive(ui.archiveInput.files[0]));
ui.campaignSelect.addEventListener("change", () => loadDashboard(ui.campaignSelect.value));
ui.compareButton.addEventListener("click", compareCampaigns);

loadDashboard();

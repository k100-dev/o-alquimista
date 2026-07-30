"use strict";

const ui = {
  loading: document.querySelector("#loading"),
  empty: document.querySelector("#empty-state"),
  dashboard: document.querySelector("#dashboard"),
  campaignSelect: document.querySelector("#campaign-select"),
  baselineSelect: document.querySelector("#baseline-select"),
  continuitySelect: document.querySelector("#continuity-select"),
  continuityConfirm: document.querySelector("#continuity-confirm-button"),
  continuityCompare: document.querySelector("#continuity-compare-button"),
  continuityRevert: document.querySelector("#continuity-revert-button"),
  archiveInput: document.querySelector("#archive-input"),
  importButton: document.querySelector("#import-button"),
  importButtonLabel: document.querySelector("#import-button-label"),
  compareButton: document.querySelector("#compare-button"),
  toast: document.querySelector("#toast"),
  helpDialog: document.querySelector("#help-dialog"),
  onboardingDialog: document.querySelector("#onboarding-dialog"),
  mentorForm: document.querySelector("#mentor-form"),
  mentorInput: document.querySelector("#mentor-input"),
  mentorSend: document.querySelector("#mentor-send"),
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
    title: "O ritual da campanha",
    body: "O Alquimista transforma cada export em um capítulo e oferece missões que você pode executar no jogo.",
    details: [
      "Escute a leitura do capítulo atual.",
      "Assuma uma missão no quadro de objetivos.",
      "Jogue e execute a ação sem preencher formulários.",
      "Importe um novo save para verificar o resultado.",
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
const MENTOR_HISTORY_KEY = "o-alquimista.mentor.v1";
const LAST_REVIEW_KEY = "o-alquimista.return-review.v1";

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
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

function timeLabel(value) {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  const integer = Math.trunc(numeric);
  const hours = Math.trunc(integer / 100);
  const minutes = integer % 100;
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function campaignLabel(campaign) {
  const day = campaign.latest_elapsed_days;
  const time = timeLabel(campaign.latest_time_of_day);
  const moment = day === null || day === undefined
    ? "Momento importado"
    : `Dia ${day}${time ? ` · ${time}` : ""}`;
  const relation = Number(campaign.confirmed_association_count || 0) > 0
    ? "memória confirmada"
    : `identidade ${confidenceLabels[campaign.confidence] || "indisponível"}`;
  return `${moment} · ${relation}`;
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

function questStorageKey(campaignId) {
  return `o-alquimista.quest.v1.${campaignId || "unknown"}`;
}

function loadQuestState(campaignId) {
  try {
    return JSON.parse(localStorage.getItem(questStorageKey(campaignId)) || "null");
  } catch {
    return null;
  }
}

function saveQuestState(campaignId, state) {
  if (state) {
    localStorage.setItem(questStorageKey(campaignId), JSON.stringify(state));
  } else {
    localStorage.removeItem(questStorageKey(campaignId));
  }
}

function readLocalJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null") ?? fallback;
  } catch {
    return fallback;
  }
}

function writeLocalJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function loadMentorHistory() {
  const history = readLocalJson(MENTOR_HISTORY_KEY, []);
  return Array.isArray(history) ? history.slice(-24) : [];
}

function saveMentorHistory(history) {
  writeLocalJson(MENTOR_HISTORY_KEY, history.slice(-24));
}

function addMentorMessage(message) {
  const history = loadMentorHistory();
  history.push(message);
  saveMentorHistory(history);
}

function loadLastReview() {
  return readLocalJson(LAST_REVIEW_KEY, null);
}

function saveLastReview(review) {
  if (review) writeLocalJson(LAST_REVIEW_KEY, review);
  else localStorage.removeItem(LAST_REVIEW_KEY);
}

function showOnboarding() {
  if (!ui.onboardingDialog.open) ui.onboardingDialog.showModal();
}

function renderCampaigns(data) {
  clear(ui.campaignSelect);
  for (const campaign of data.campaigns || []) {
    const option = document.createElement("option");
    option.value = campaign.campaign_id;
    option.textContent = campaignLabel(campaign);
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
    const relation = item.relation === "confirmed" ? "confirmado" : "sugerido";
    option.textContent =
      `Dia ${moment.elapsed_days ?? "—"} ${moment.time_label || ""} · ` +
      `${relation} · ${item.shared_signal_count} sinais em comum`;
    ui.baselineSelect.appendChild(option);
  }
  ui.baselineSelect.disabled = related.length === 0;
  ui.compareButton.disabled = related.length === 0;
  document.querySelector("#comparison-empty").textContent = related.length
    ? `${related.length} export(s) relacionado(s) disponível(is) para comparação exploratória.`
    : "Importe outro momento da campanha para liberar a comparação.";
}

function continuitySelection(data = currentDashboard) {
  if (!data || !ui.continuitySelect.value) return null;
  return (data.related_exports || []).find(
    (item) => item.campaign_id === ui.continuitySelect.value,
  ) || null;
}

function renderContinuityReview(review) {
  const container = document.querySelector("#continuity-review");
  const deltas = document.querySelector("#continuity-review-deltas");
  clear(deltas);
  if (!review) {
    container.classList.add("hidden");
    return;
  }
  document.querySelector("#continuity-review-title").textContent =
    review.verdict?.title || "Comparação disponível";
  document.querySelector("#continuity-review-body").textContent =
    review.verdict?.body || review.caution || "";
  const financial = (review.financial_changes || [])
    .filter((item) => item.status === "changed")
    .slice(0, 2);
  for (const item of financial) {
    const card = element("article", "continuity-delta");
    card.appendChild(element("span", "", item.label));
    card.appendChild(element("strong", "", signedMoney(item.absolute_change)));
    deltas.appendChild(card);
  }
  for (const item of (review.operational_sections || []).slice(0, 2)) {
    const card = element("article", "continuity-delta");
    card.appendChild(element("span", "", item.label));
    card.appendChild(
      element(
        "strong",
        "",
        quantity(item.changed_count, "mudança", "mudanças"),
      ),
    );
    deltas.appendChild(card);
  }
  container.classList.remove("hidden");
}

function updateContinuityControls(data = currentDashboard) {
  const selected = continuitySelection(data);
  const hasSelection = Boolean(selected);
  const confirmed = selected?.relation === "confirmed";
  ui.continuitySelect.disabled = !hasSelection;
  ui.continuityCompare.disabled = !hasSelection;
  ui.continuityConfirm.classList.toggle("hidden", !hasSelection || confirmed);
  ui.continuityRevert.classList.toggle("hidden", !hasSelection || !confirmed);
}

function renderContinuity(data) {
  const continuity = data.continuity || {};
  const related = data.related_exports || [];
  const status = continuity.status || "isolated";
  document.querySelector("#continuity-title").textContent =
    continuity.title || "Conecte os capítulos da sua campanha";
  document.querySelector("#continuity-body").textContent =
    continuity.body || "Importe outro momento para construir sua memória.";
  const badge = document.querySelector("#continuity-status");
  badge.textContent = {
    confirmed: `${continuity.moment_count || 1} momentos conectados`,
    suggested: `${continuity.suggested_count || related.length} sugestão(ões)`,
    isolated: "aguardando outro export",
  }[status] || status;
  badge.dataset.status = status;

  clear(ui.continuitySelect);
  for (const item of related) {
    const option = document.createElement("option");
    option.value = item.campaign_id;
    const moment = item.moment || {};
    const relation = item.relation === "confirmed" ? "confirmado" : "sugerido";
    option.textContent =
      `Dia ${moment.elapsed_days ?? "—"}${moment.time_label ? ` · ${moment.time_label}` : ""}` +
      ` · ${relation}`;
    option.selected =
      item.campaign_id === continuity.selected_related_campaign_id;
    ui.continuitySelect.appendChild(option);
  }
  if (!related.length) {
    const option = document.createElement("option");
    option.textContent = "Nenhum capítulo relacionado encontrado";
    option.value = "";
    ui.continuitySelect.appendChild(option);
  }
  renderContinuityReview(continuity.review);
  updateContinuityControls(data);
}

function renderMessage(data) {
  document.querySelector("#chapter-number").textContent = data.story.chapter_number;
  document.querySelector("#chapter-title").textContent = data.story.chapter_title;
  document.querySelector("#story-headline").textContent =
    `${data.story.chapter_title}: seu próximo movimento.`;
  document.querySelector("#story-narrative").textContent = data.story.narrative;
  document.querySelector("#message-title").textContent = data.message.title;
  document.querySelector("#message-body").textContent = data.message.body;
  document.querySelector("#snapshot-explanation").textContent = data.snapshot.explanation;
  document.querySelector("#snapshot-day").textContent =
    data.snapshot.elapsed_days === null ? "dia indisponível" : `dia ${data.snapshot.elapsed_days}`;
  document.querySelector("#snapshot-time").textContent =
    data.snapshot.moment?.time_label || "hora indisponível";
  document.querySelector("#game-rank").textContent =
    data.story.game_rank === null || data.story.game_rank === undefined
      ? "rank indisponível"
      : `rank ${data.story.game_rank} · tier ${data.story.game_tier ?? "—"}`;
  document.querySelector("#confidence-chip").textContent =
    `identidade ${confidenceLabels[data.campaign?.confidence] || "indisponível"}`;
}

function renderStory(data) {
  document.querySelector("#story-note").textContent = data.story.companion_note;
  document.querySelector("#next-unlock").textContent = data.story.next_unlock;
  const path = document.querySelector("#story-path");
  clear(path);
  for (const stage of data.story.path) {
    const card = element(
      "article",
      `story-stage${stage.current ? " current" : ""}${stage.completed ? " completed" : ""}`,
    );
    card.appendChild(element("span", "story-stage-number", stage.roman));
    const copy = element("div", "");
    copy.appendChild(element("strong", "", stage.title));
    copy.appendChild(element("small", "", stage.description));
    card.appendChild(copy);
    card.appendChild(
      element(
        "span",
        "story-stage-state",
        stage.current ? "agora" : stage.completed ? "concluído" : "bloqueado",
      ),
    );
    path.appendChild(card);
  }

  const achievements = document.querySelector("#achievement-strip");
  clear(achievements);
  achievements.appendChild(element("span", "achievement-title", "Selos da jornada"));
  for (const achievement of data.achievements || []) {
    const badge = element("article", "achievement");
    badge.appendChild(element("span", "achievement-icon", achievement.icon));
    const copy = element("div", "");
    copy.appendChild(element("strong", "", achievement.title));
    copy.appendChild(element("small", "", achievement.description));
    badge.appendChild(copy);
    achievements.appendChild(badge);
  }
}

function mentorEvidenceValue(item) {
  if (item.value === null || item.value === undefined || item.value === "") {
    return "indisponível";
  }
  if (item.format === "money") return money(item.value);
  if (item.format === "percent") return `${item.value}%`;
  if (item.format === "score") return `${item.value}/100`;
  return String(item.value);
}

function mentorGreeting(data) {
  return {
    role: "mentor",
    title: `Eu li o capítulo ${data.story.chapter_number}: ${data.story.chapter_title}`,
    answer: (
      `${data.message.body} Você pode me perguntar sobre uma compra, um gargalo, ` +
      "sua equipe, o estoque ou o que devemos provar no próximo export."
    ),
    evidence: [
      {
        label: "Qualidade do diagnóstico",
        value: data.diagnostic.decision_readiness_score,
        format: "score",
      },
      {
        label: "Missões disponíveis",
        value: (data.quests || []).length,
        format: "number",
      },
    ],
    action: (data.quests || [])[0]?.objective || "Traga outro momento da campanha.",
    confidence: "medium",
    follow_up: [
      "O que devo fazer agora?",
      "Posso expandir com segurança?",
      "O que o próximo export vai provar?",
    ],
    snapshot_id: data.snapshot.snapshot_id,
  };
}

function renderMentor(data) {
  const container = document.querySelector("#mentor-messages");
  let history = loadMentorHistory();
  if (!history.length) {
    history = [mentorGreeting(data)];
    saveMentorHistory(history);
  }
  clear(container);
  for (const message of history.slice(-10)) {
    const article = element("article", `mentor-message ${message.role || "mentor"}`);
    const avatar = element("span", "mentor-avatar", message.role === "user" ? "Você" : "△");
    article.appendChild(avatar);
    const copy = element("div", "mentor-message-copy");
    if (message.role === "user") {
      copy.appendChild(element("p", "", message.question));
    } else {
      copy.appendChild(element("small", "", "O Alquimista responde"));
      copy.appendChild(element("h3", "", message.title));
      copy.appendChild(element("p", "", message.answer));
      if ((message.evidence || []).length) {
        const evidence = element("div", "mentor-evidence");
        for (const item of message.evidence) {
          const row = element("div", "");
          row.appendChild(element("span", "", item.label));
          row.appendChild(element("strong", "", mentorEvidenceValue(item)));
          evidence.appendChild(row);
        }
        copy.appendChild(evidence);
      }
      if (message.action) {
        const action = element("div", "mentor-action");
        action.appendChild(element("span", "", "Próximo movimento"));
        action.appendChild(element("strong", "", message.action));
        copy.appendChild(action);
      }
      if (message.caution) {
        const details = element("details", "mentor-caution");
        details.appendChild(element("summary", "", "Até onde esta resposta é segura?"));
        details.appendChild(element("p", "", message.caution));
        copy.appendChild(details);
      }
      if ((message.follow_up || []).length) {
        const followups = element("div", "mentor-followups");
        for (const question of message.follow_up.slice(0, 3)) {
          const button = element("button", "", question);
          button.type = "button";
          button.addEventListener("click", () => askMentor(question));
          followups.appendChild(button);
        }
        copy.appendChild(followups);
      }
    }
    article.appendChild(copy);
    container.appendChild(article);
  }
  window.requestAnimationFrame(() => {
    container.scrollTop = container.scrollHeight;
  });
}

async function askMentor(rawQuestion) {
  if (!currentDashboard || currentDashboard.status !== "ready") return;
  const question = String(rawQuestion || "").trim();
  if (!question) {
    ui.mentorInput.focus();
    return;
  }
  addMentorMessage({
    role: "user",
    question,
    snapshot_id: currentDashboard.snapshot.snapshot_id,
  });
  renderMentor(currentDashboard);
  ui.mentorInput.value = "";
  ui.mentorInput.disabled = true;
  ui.mentorSend.disabled = true;
  ui.mentorSend.textContent = "Consultando…";
  try {
    const response = await fetch("/api/mentor", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        campaign_id: currentDashboard.selected_campaign_id,
        question,
      }),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "Falha na consulta.");
    addMentorMessage({role: "mentor", ...data});
    renderMentor(currentDashboard);
  } catch (error) {
    addMentorMessage({
      role: "mentor",
      title: "A leitura foi interrompida",
      answer: error.message || "Não consegui responder agora.",
      evidence: [],
      action: "Tente novamente sem importar outro save.",
      confidence: "unavailable",
      follow_up: [],
    });
    renderMentor(currentDashboard);
  } finally {
    ui.mentorInput.disabled = false;
    ui.mentorSend.disabled = false;
    ui.mentorSend.textContent = "Perguntar";
    ui.mentorInput.focus();
  }
}

function renderSessionReview(review = loadLastReview()) {
  const container = document.querySelector("#session-review");
  if (
    !review ||
    !currentDashboard ||
    review.current_campaign_id !== currentDashboard.selected_campaign_id
  ) {
    container.classList.add("hidden");
    return;
  }
  container.classList.remove("hidden");
  document.querySelector("#review-title").textContent = review.title;
  document.querySelector("#review-body").textContent = review.body;
  const verdict = document.querySelector("#review-verdict");
  verdict.textContent = review.verdict;
  verdict.dataset.tone = review.tone || "neutral";
  const deltas = document.querySelector("#review-deltas");
  clear(deltas);
  for (const item of review.deltas || []) {
    const card = element("article", `review-delta ${item.tone || "neutral"}`);
    card.appendChild(element("span", "", item.label));
    card.appendChild(element("strong", "", item.value));
    card.appendChild(element("small", "", item.note));
    deltas.appendChild(card);
  }
  document.querySelector("#review-quest-title").textContent = review.quest_title;
  document.querySelector("#review-quest-body").textContent = review.quest_body;
}

function comparisonReview(comparison, previousDashboard, nextDashboard, questState) {
  const deltas = [];
  for (const item of (comparison.financial_changes || []).filter((row) => row.status === "changed").slice(0, 3)) {
    const numeric = Number(item.absolute_change || 0);
    deltas.push({
      label: item.label,
      value: signedMoney(item.absolute_change),
      note: "mudança observada entre os exports",
      tone: numeric > 0 ? "good" : numeric < 0 ? "attention" : "neutral",
    });
  }
  for (const item of (comparison.operational_sections || []).slice(0, Math.max(0, 3 - deltas.length))) {
    deltas.push({
      label: item.label,
      value: `${item.changed_count} ${item.changed_count === 1 ? "mudança" : "mudanças"}`,
      note: `+${item.added_count} · −${item.removed_count} · ${item.updated_count} alteradas`,
      tone: "neutral",
    });
  }
  if (!deltas.length) {
    deltas.push({
      label: "Estado observado",
      value: "sem mudança relevante",
      note: "o novo export ainda é útil como evidência",
      tone: "neutral",
    });
  }
  const completed = Array.isArray(questState?.completed)
    ? [...questState.completed, false, false, false].slice(0, 3)
    : [false, false, true];
  completed[2] = true;
  const executed = Boolean(completed[1]);
  const changed = deltas.some((item) => item.value !== "sem mudança relevante");
  const quest = questState?.quest;
  const questTitle = quest?.title || "Sessão registrada";
  const questBody = quest
    ? executed && changed
      ? (
        "Você marcou a ação como executada e o novo export registrou mudanças. " +
        "Isso fortalece a hipótese, mas ainda não prova causalidade."
      )
      : executed
        ? (
          "A ação foi marcada como executada, porém o efeito não ficou claro neste " +
          "export. Mantenha a operação estável e observe mais um ciclo."
        )
        : (
          "O retorno foi registrado, mas a etapa de execução não foi confirmada. " +
          "Marque o que realmente fez antes de interpretar o resultado."
        )
    : "Nenhuma missão estava ativa; o novo momento foi guardado como referência.";
  return {
    title: comparison.verdict.title,
    body: comparison.verdict.body,
    verdict: executed && changed ? "hipótese fortalecida" : "evidência recebida",
    tone: executed && changed ? "good" : comparison.verdict.tone || "neutral",
    deltas,
    quest_title: questTitle,
    quest_body: questBody,
    current_campaign_id: nextDashboard.selected_campaign_id,
    baseline_campaign_id: previousDashboard.selected_campaign_id,
    created_at: new Date().toISOString(),
  };
}

async function evaluateReturn(previousDashboard, nextDashboard, questState, deduplicated) {
  if (!previousDashboard || !nextDashboard || deduplicated) return;
  if (previousDashboard.snapshot.snapshot_id === nextDashboard.snapshot.snapshot_id) return;
  const query = new URLSearchParams({
    current_campaign_id: nextDashboard.selected_campaign_id,
    baseline_campaign_id: previousDashboard.selected_campaign_id,
    current_snapshot_id: nextDashboard.snapshot.snapshot_id,
    baseline_snapshot_id: previousDashboard.snapshot.snapshot_id,
  });
  try {
    const response = await fetch(`/api/comparison?${query}`);
    const comparison = await response.json();
    if (!response.ok || comparison.error) {
      throw new Error(comparison.error || "Não foi possível avaliar o retorno.");
    }
    const review = comparisonReview(
      comparison,
      previousDashboard,
      nextDashboard,
      questState,
    );
    saveLastReview(review);
    if (questState) {
      const completed = Array.isArray(questState.completed)
        ? [...questState.completed, false, false, false].slice(0, 3)
        : [true, false, false];
      completed[2] = true;
      saveQuestState(nextDashboard.selected_campaign_id, {
        ...questState,
        completed,
        reviewed_snapshot_id: nextDashboard.snapshot.snapshot_id,
        review,
      });
      if (
        previousDashboard.selected_campaign_id !== nextDashboard.selected_campaign_id
      ) {
        saveQuestState(previousDashboard.selected_campaign_id, null);
      }
      renderActionPlan(nextDashboard);
      renderActiveQuest(nextDashboard);
    }
    addMentorMessage({
      role: "mentor",
      title: "O novo export foi comparado com o capítulo anterior",
      answer: `${review.body} ${review.quest_body}`,
      evidence: review.deltas.map((item) => ({
        label: item.label,
        value: item.value,
        format: "text",
      })),
      action: "Converse comigo sobre o resultado antes de escolher a próxima missão.",
      confidence: "medium",
      follow_up: [
        "O que este resultado significa?",
        "Qual deve ser minha próxima missão?",
        "Posso expandir agora?",
      ],
      snapshot_id: nextDashboard.snapshot.snapshot_id,
    });
    renderMentor(nextDashboard);
    renderSessionReview(review);
    containerScrollIntoView("#session-review");
  } catch (error) {
    showToast(error.message || "O save foi importado, mas a comparação falhou.", true);
  }
}

function containerScrollIntoView(selector) {
  document.querySelector(selector)?.scrollIntoView({behavior: "smooth", block: "start"});
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
  const quests = data.quests || [];
  const activeState = loadQuestState(data.selected_campaign_id);
  document.querySelector("#action-count").textContent = quests.length;
  for (const item of quests) {
    const isActive = activeState?.quest_id === item.quest_id;
    const card = element("article", "action-card");
    card.classList.toggle("active", isActive);
    card.appendChild(element("span", "action-rank", item.rank));
    card.appendChild(element("p", "action-kicker", `Confiança ${confidenceLabels[item.confidence] || item.confidence}`));
    card.appendChild(element("h3", "", item.title));
    card.appendChild(element("p", "action-command", item.objective));
    const why = element("div", "action-explain");
    why.appendChild(element("strong", "", "Por quê"));
    why.appendChild(element("p", "", item.briefing));
    card.appendChild(why);
    const success = element("div", "success-box");
    success.appendChild(element("span", "", "✓ Sinal de conclusão"));
    success.appendChild(element("p", "", item.success));
    card.appendChild(success);
    card.appendChild(element("small", "", item.impact));
    const reward = element("div", "quest-reward");
    reward.appendChild(element("span", "", item.reward.icon));
    reward.appendChild(element("strong", "", `Recompensa: ${item.reward.label}`));
    card.appendChild(reward);
    const accept = element(
      "button",
      isActive ? "secondary-button quest-accept active" : "secondary-button quest-accept",
      isActive ? "Missão ativa" : "Assumir missão",
    );
    accept.type = "button";
    accept.dataset.questId = item.quest_id;
    accept.disabled = isActive;
    accept.addEventListener("click", () => acceptQuest(data, item.quest_id));
    card.appendChild(accept);
    container.appendChild(card);
  }
}

function acceptQuest(data, questId) {
  const quest = (data.quests || []).find((item) => item.quest_id === questId);
  const state = {
    quest_id: questId,
    quest,
    completed: [true, false, false],
    started_snapshot_id: data.snapshot.snapshot_id,
    baseline_campaign_id: data.selected_campaign_id,
  };
  saveQuestState(data.selected_campaign_id, state);
  renderActionPlan(data);
  renderActiveQuest(data);
  document.querySelector("#active-quest").scrollIntoView({behavior: "smooth", block: "center"});
  showToast("Missão assumida. O primeiro passo já foi concluído.");
}

function renderActiveQuest(data) {
  const container = document.querySelector("#active-quest");
  const state = loadQuestState(data.selected_campaign_id);
  const quest = (
    (data.quests || []).find((item) => item.quest_id === state?.quest_id) ||
    state?.quest
  );
  if (!state || !quest) {
    container.classList.add("hidden");
    return;
  }
  container.classList.remove("hidden");
  document.querySelector("#active-quest-title").textContent = quest.title;
  document.querySelector("#active-quest-objective").textContent = quest.objective;
  const checklist = document.querySelector("#quest-checklist");
  clear(checklist);
  const completed = Array.isArray(state.completed)
    ? [...state.completed, false, false, false].slice(0, 3)
    : [true, false, false];
  quest.ritual.forEach((label, index) => {
    const row = element("label", "quest-check");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(completed[index]);
    input.disabled = index === 2;
    if (index === 2) {
      input.title = "Esta etapa é concluída automaticamente ao importar outro export.";
    }
    input.addEventListener("change", () => {
      completed[index] = input.checked;
      saveQuestState(data.selected_campaign_id, {
        quest_id: quest.quest_id,
        completed,
      });
      renderActiveQuest(data);
      if (completed.every(Boolean)) {
        showToast("Missão concluída. O próximo export revelará o impacto.");
      }
    });
    row.appendChild(input);
    row.appendChild(element("span", "", label));
    checklist.appendChild(row);
  });
  const done = completed.filter(Boolean).length;
  document.querySelector("#quest-progress-label").textContent = `${done}/3`;
  document.querySelector("#quest-progress-bar").style.width = `${(done / 3) * 100}%`;
  document.querySelector("#quest-import-button").textContent =
    completed[2] ? "Novo export já avaliado" : "Trazer novo export para avaliação";
  document.querySelector("#quest-import-button").disabled = Boolean(completed[2]);
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
  renderStory(data);
  renderMentor(data);
  renderContinuity(data);
  renderMetrics(data);
  renderDiagnostic(data);
  renderActionPlan(data);
  renderActiveQuest(data);
  renderRecommendations(data);
  renderAvailability(data);
  renderOperations(data);
  renderProperties(data);
  renderPortfolio(data);
  renderWorkforce(data);
  renderTimeline(data);
  renderSessionReview();
  document.querySelector("#comparison-result").classList.add("hidden");
  document.querySelector("#comparison-empty").classList.remove("hidden");
  ui.importButtonLabel.textContent = "Trazer novo export";
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

async function compareContinuity() {
  const related = continuitySelection();
  if (!currentDashboard || !related) return;
  ui.continuityCompare.disabled = true;
  ui.continuityCompare.textContent = "Comparando…";
  const query = new URLSearchParams({
    current_campaign_id: currentDashboard.selected_campaign_id,
    baseline_campaign_id: related.campaign_id,
  });
  try {
    const response = await fetch(`/api/comparison?${query}`);
    const data = await response.json();
    if (!response.ok || data.error) {
      throw new Error(data.error || "Falha na comparação.");
    }
    renderContinuityReview(data);
    showToast(
      data.relation === "confirmed_continuity"
        ? "Memória confirmada comparada."
        : "Comparação exploratória pronta. Confirme somente se reconhecer a campanha.",
    );
  } catch (error) {
    showToast(error.message || "Não foi possível comparar os capítulos.", true);
  } finally {
    ui.continuityCompare.textContent = "Comparar antes";
    updateContinuityControls();
  }
}

async function setCampaignAssociation(action) {
  const related = continuitySelection();
  if (!currentDashboard || !related) return;
  ui.continuityConfirm.disabled = true;
  ui.continuityRevert.disabled = true;
  try {
    const response = await fetch("/api/campaign-association", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        campaign_id: currentDashboard.selected_campaign_id,
        related_campaign_id: related.campaign_id,
        action,
      }),
    });
    const data = await response.json();
    if (!response.ok || data.error) {
      throw new Error(data.error || "Falha ao atualizar a memória.");
    }
    render(data.dashboard);
    showToast(
      action === "confirm"
        ? "Capítulos conectados. O mentor já pode usar este antes e depois."
        : "Confirmação desfeita. Os capítulos voltaram ao modo sugerido.",
    );
    containerScrollIntoView("#continuity");
  } catch (error) {
    showToast(error.message || "Não foi possível atualizar a memória.", true);
  } finally {
    ui.continuityConfirm.disabled = false;
    ui.continuityRevert.disabled = false;
    updateContinuityControls();
  }
}

async function importArchive(file) {
  if (!file) return;
  const previousDashboard = currentDashboard?.status === "ready"
    ? currentDashboard
    : null;
  const activeQuest = previousDashboard
    ? loadQuestState(previousDashboard.selected_campaign_id)
    : null;
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
        : "Novo capítulo analisado. O Alquimista está avaliando a sessão.",
    );
    await evaluateReturn(
      previousDashboard,
      data.dashboard,
      activeQuest,
      data.import.deduplicated,
    );
  } catch (error) {
    showToast(error.message || "Não foi possível importar o save.", true);
  } finally {
    ui.importButton.disabled = false;
    ui.importButtonLabel.textContent =
      currentDashboard?.status === "ready" ? "Trazer novo export" : "Importar save";
    ui.archiveInput.value = "";
  }
}

ui.importButton.addEventListener("click", () => ui.archiveInput.click());
for (const trigger of document.querySelectorAll(".import-trigger")) {
  trigger.addEventListener("click", () => ui.archiveInput.click());
}
document.querySelector("#glossary-button").addEventListener("click", () => openHelp("overview"));
document.querySelector("#story-help-button").addEventListener("click", showOnboarding);
document.querySelector("#mentor-hero-button").addEventListener("click", () => {
  containerScrollIntoView("#mentor");
  window.setTimeout(() => ui.mentorInput.focus(), 450);
});
document.querySelector("#primary-quest-button").addEventListener("click", () => {
  document.querySelector("#plan").scrollIntoView({behavior: "smooth", block: "start"});
});
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
ui.continuitySelect.addEventListener("change", () => {
  updateContinuityControls();
  renderContinuityReview(null);
});
ui.continuityCompare.addEventListener("click", compareContinuity);
ui.continuityConfirm.addEventListener(
  "click",
  () => setCampaignAssociation("confirm"),
);
ui.continuityRevert.addEventListener(
  "click",
  () => setCampaignAssociation("revert"),
);
ui.mentorForm.addEventListener("submit", (event) => {
  event.preventDefault();
  askMentor(ui.mentorInput.value);
});
for (const button of document.querySelectorAll("[data-question]")) {
  button.addEventListener("click", () => askMentor(button.dataset.question));
}
document.querySelector("#quest-import-button").addEventListener("click", () => {
  ui.archiveInput.click();
});
document.querySelector("#review-mentor-button").addEventListener("click", () => {
  containerScrollIntoView("#mentor");
  ui.mentorInput.value = "O que este resultado significa para minha próxima decisão?";
  window.setTimeout(() => ui.mentorInput.focus(), 450);
});
document.querySelector("#review-dismiss-button").addEventListener("click", () => {
  saveLastReview(null);
  renderSessionReview(null);
  showToast("O retorno foi guardado. A conversa continua na Sala de Conselho.");
});
document.querySelector("#abandon-quest-button").addEventListener("click", () => {
  if (!currentDashboard) return;
  saveQuestState(currentDashboard.selected_campaign_id, null);
  renderActionPlan(currentDashboard);
  renderActiveQuest(currentDashboard);
  document.querySelector("#plan").scrollIntoView({behavior: "smooth", block: "start"});
  showToast("Missão liberada. Escolha um novo objetivo.");
});
document.querySelector("#details-toggle").addEventListener("click", (event) => {
  const open = document.body.classList.toggle("details-open");
  event.currentTarget.textContent = open ? "Fechar painel completo" : "Abrir painel completo";
  if (open) document.querySelector("#diagnostic").scrollIntoView({behavior: "smooth", block: "start"});
});
document.querySelector("#onboarding-close").addEventListener("click", () => {
  localStorage.setItem("o-alquimista.onboarding.v1", "seen");
  ui.onboardingDialog.close();
});
document.querySelector("#onboarding-start").addEventListener("click", () => {
  localStorage.setItem("o-alquimista.onboarding.v1", "seen");
  ui.onboardingDialog.close();
  document.querySelector("#overview").scrollIntoView({behavior: "smooth", block: "start"});
});
for (const link of document.querySelectorAll(".nav-item")) {
  link.addEventListener("click", () => {
    const target = document.querySelector(link.getAttribute("href"));
    if (target?.hasAttribute("data-advanced")) {
      document.body.classList.add("details-open");
      document.querySelector("#details-toggle").textContent = "Fechar painel completo";
    }
  });
}

loadDashboard();
if (!localStorage.getItem("o-alquimista.onboarding.v1")) {
  window.setTimeout(showOnboarding, 450);
}

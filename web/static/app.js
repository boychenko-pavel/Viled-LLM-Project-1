const messagesEl = document.querySelector("#messages");
const loginScreen = document.querySelector("#loginScreen");
const loginForm = document.querySelector("#loginForm");
const appShell = document.querySelector("#appShell");
const formEl = document.querySelector("#chatForm");
const inputEl = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendButton");
const copyInputButton = document.querySelector("#copyInputButton");
const resetButton = document.querySelector("#resetButton");
const modelNameEl = document.querySelector("#modelName");
const workspaceTitleEl = document.querySelector("#workspaceTitle");
const workspaceEyebrowEl = document.querySelector("#workspaceEyebrow");
const workspaceButtons = document.querySelectorAll("[data-workspace]");
const hrUploadPanel = document.querySelector("#hrUploadPanel");
const hrUploadForm = document.querySelector("#hrUploadForm");
const hrPdfInput = document.querySelector("#hrPdfInput");
const hrUploadButton = document.querySelector("#hrUploadButton");
const hrUploadStatus = document.querySelector("#hrUploadStatus");
const hrMemoryPanel = document.querySelector("#hrMemoryPanel");
const hrMemorySummary = document.querySelector("#hrMemorySummary");
const hrMemoryRefreshButton = document.querySelector("#hrMemoryRefreshButton");
const hrDocumentSelect = document.querySelector("#hrDocumentSelect");
const hrSearchForm = document.querySelector("#hrSearchForm");
const hrSearchInput = document.querySelector("#hrSearchInput");
const hrSearchButton = document.querySelector("#hrSearchButton");
const hrChunkList = document.querySelector("#hrChunkList");

let messages = [];
let activeWorkspace = "bi_analytics";
let hrDocuments = [];
let currencyView = "menu";
let isCurrencySnapshotLoading = false;
let isCurrencyCurrentLoading = false;
let isCurrencyCurrentSaving = false;
let currencyCurrentRows = [];
let currencyCurrentStatus = "";
const toolWorkspaces = new Set(["forecast_sales", "currency"]);

const pricingCurrencyRows = [
  { date: "2026-02-02", currency: "USD", rate: "520" },
  { date: "2026-02-02", currency: "EUR", rate: "620" },
  { date: "2026-02-02", currency: "RUB", rate: "6.85" },
  { date: "2026-02-02", currency: "CHF", rate: "689" },
];

function enterApplication() {
  loginScreen?.classList.add("hidden");
  appShell?.classList.remove("is-hidden");
  inputEl.focus();
}

const workspaceConfig = {
  bi_analytics: {
    title: "SQL Analytic",
    eyebrow: "Agent Team / SQL Analytic",
    emptyTitle: "Задайте вопрос по базе данных",
    emptyText: "Агент умеет отвечать про DWH.LLM.price, LLM.sales и DWH.LLM.cost.",
    placeholder: "Спросите про цены, продажи, валюты или схему...",
    avatar: "SQL",
  },
  office_manager: {
    title: "Office Manager",
    eyebrow: "Agent Team / Office Manager",
    emptyTitle: "Напишите Office Manager",
    emptyText: "Обычный чат с локальной LLM без доступа к SQL.",
    placeholder: "Попросите написать письмо, резюме, план или ответить на вопрос...",
    avatar: "OM",
  },
  forecast_sales: {
    title: "Forecast Sales",
    eyebrow: "Tools / Forecast Sales",
    emptyTitle: "Построить прогноз продаж",
    emptyText: "Агент агрегирует LLM.sales по месяцам и строит прогноз на 12 месяцев.",
    placeholder: "Напишите: сделай прогноз продаж на 1 год по месяцам",
    avatar: "FC",
  },
  currency: {
    title: "Currency",
    eyebrow: "Tools / Currency",
    emptyTitle: "Загрузите таблицу валют",
    emptyText: "Агент читает div.informer-additional с mig.kz, создает pandas.DataFrame и выводит результат.",
    placeholder: "Загрузи таблицу валют с mig.kz...",
    avatar: "FX",
  },
  hr: {
    title: "HR",
    eyebrow: "Agent Team / HR",
    emptyTitle: "Загрузите PDF с положением о премировании",
    emptyText: "HR отвечает по отдельной Chroma-памяти, сформированной из PDF документов.",
    placeholder: "Спросите про правила премирования, условия, сроки или исключения...",
    avatar: "HR",
  },
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function encodeCopyValue(value) {
  return escapeHtml(encodeURIComponent(value || ""));
}

function copyButton(value, className = "copy-value-button") {
  return `
    <button
      class="${className}"
      type="button"
      title="Copy"
      aria-label="Copy"
      data-copy-value="${encodeCopyValue(value)}"
    >Copy</button>
  `;
}

function splitResultRow(row) {
  return row.split(",").map((item) => item.trim());
}

function renderResultTable(resultText) {
  const lines = resultText
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (lines.length < 2 || lines[0] === "No rows found.") {
    return `<pre class="answer-pre">${escapeHtml(resultText)}</pre>`;
  }

  const headers = splitResultRow(lines[0]);
  const rows = lines.slice(1).map(splitResultRow);
  const renderCell = (value, header) => {
    let safeValue = value || "";
    const normalizedHeader = (header || "").trim().toLowerCase();
    const numericValue = Number(safeValue.replace(",", "."));
    const isDifCell = normalizedHeader === "dif" && safeValue !== "";
    const isNumericDif = isDifCell && Number.isFinite(numericValue);
    if (isNumericDif && numericValue === 0) {
      safeValue = "-";
    }
    const difClass = isNumericDif && numericValue > 0
      ? " dif-positive"
      : isNumericDif && numericValue < 0
        ? " dif-negative"
        : "";
    const difStyle = isNumericDif && numericValue > 0
      ? ' style="color: #21d07a;"'
      : isNumericDif && numericValue < 0
        ? ' style="color: #ff6b6b;"'
        : "";
    return `
      <td class="${difClass.trim()}"${difStyle}>
        <span class="cell-value">${escapeHtml(safeValue)}</span>
        ${copyButton(safeValue, "copy-cell-button")}
      </td>
    `;
  };

  return `
    <div class="result-table-wrap">
      <table class="result-table">
        <thead>
          <tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (row) => `
                <tr>
                  ${headers
                    .map((header, index) => renderCell(row[index] || "", header))
                    .join("")}
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderCurrencyMenu() {
  messagesEl.innerHTML = `
    <div class="currency-menu-screen">
      <div class="currency-menu">
        <button class="currency-choice-card" type="button" data-currency-view="viled">
          <span class="currency-choice-mark" aria-hidden="true"></span>
          <strong>Курс ViledInform</strong>
        </button>
        <button class="currency-choice-card" type="button" data-currency-view="pricing">
          <span class="currency-choice-mark" aria-hidden="true"></span>
          <strong>Курс Ценообразования</strong>
        </button>
      </div>
    </div>
  `;
}

function renderPricingCurrencyTable() {
  messagesEl.innerHTML = `
    <div class="currency-pricing-screen">
      <div class="currency-pricing-panel">
        <div class="currency-pricing-header">
          <div>
            <div class="answer-label">Currency</div>
            <h2>Курс Ценообразования</h2>
          </div>
          <button class="currency-back-button" type="button" data-currency-view="menu">Назад</button>
        </div>
        <div class="result-table-wrap">
          <table class="result-table currency-pricing-table">
            <thead>
              <tr>
                <th>Дата</th>
                <th>Валюта</th>
                <th>Курс</th>
              </tr>
            </thead>
            <tbody>
              ${pricingCurrencyRows
                .map(
                  (row) => `
                    <tr>
                      <td>${escapeHtml(row.date)}</td>
                      <td>${escapeHtml(row.currency)}</td>
                      <td>${escapeHtml(row.rate)}</td>
                    </tr>
                  `,
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

function renderMessageList() {
  return messages
    .map((message) => {
      const role = message.role === "user" ? "user" : "assistant";
      const avatar = role === "user" ? "YOU" : workspaceConfig[activeWorkspace].avatar;
      const errorClass = message.error ? " error" : "";
      return `
        <article class="message ${role}">
          <div class="avatar">${avatar}</div>
          <div class="bubble${errorClass}">${renderMessageContent(message, role)}</div>
        </article>
      `;
    })
    .join("");
}

function renderCurrencyViledInform() {
  messagesEl.innerHTML = `
    <div class="currency-viled-screen">
      <div class="currency-viled-panel">
        <div class="currency-pricing-header">
          <div>
            <div class="answer-label">Currency</div>
            <h2>Курс ViledInform</h2>
          </div>
          <button class="currency-back-button" type="button" data-currency-view="menu">Назад</button>
        </div>
        <button
          id="currencySnapshotButton"
          class="currency-run-button"
          type="button"
          ${isCurrencySnapshotLoading ? "disabled" : ""}
        >
          ${isCurrencySnapshotLoading ? "Выполняется..." : "Запустить скрипт"}
        </button>
        <button
          id="currencyCurrentEditButton"
          class="currency-secondary-button"
          type="button"
          ${isCurrencyCurrentLoading ? "disabled" : ""}
        >
          ${isCurrencyCurrentLoading ? "Загрузка..." : "Обновить данные Viled Inform"}
        </button>
        <div class="currency-viled-result">
          ${
            messages.length
              ? renderMessageList()
              : `<div class="currency-viled-empty">Нажмите кнопку, чтобы сделать снимок курса и сохранить его в SQLite.</div>`
          }
        </div>
      </div>
    </div>
  `;
}

function renderCurrencyCurrentForm() {
  const rowsMarkup = currencyCurrentRows.length
    ? currencyCurrentRows
        .map(
          (row) => `
            <label class="currency-current-row">
              <span>${escapeHtml(row.currency)}</span>
              <input
                type="text"
                inputmode="decimal"
                autocomplete="off"
                name="${escapeHtml(row.currency)}"
                value="${escapeHtml(row.viled_inform ?? "")}"
              />
            </label>
          `,
        )
        .join("")
    : `<div class="currency-viled-empty">${isCurrencyCurrentLoading ? "Загрузка..." : "Валюты не найдены."}</div>`;

  messagesEl.innerHTML = `
    <div class="currency-viled-screen">
      <div class="currency-viled-panel">
        <div class="currency-pricing-header">
          <div>
            <div class="answer-label">Currency</div>
            <h2>Обновить Viled Inform</h2>
          </div>
          <button class="currency-back-button" type="button" data-currency-view="viled">Назад</button>
        </div>
        <form id="currencyCurrentForm" class="currency-current-form">
          <div class="currency-current-grid">
            ${rowsMarkup}
          </div>
          <div class="currency-current-footer">
            <button
              class="currency-run-button"
              type="submit"
              ${isCurrencyCurrentSaving || !currencyCurrentRows.length ? "disabled" : ""}
            >
              ${isCurrencyCurrentSaving ? "Сохранение..." : "Сохранить"}
            </button>
            <div class="currency-current-status">${escapeHtml(currencyCurrentStatus)}</div>
          </div>
        </form>
      </div>
    </div>
  `;
}

function renderCurrencyView() {
  if (activeWorkspace !== "currency") {
    return false;
  }
  if (currencyView === "menu") {
    renderCurrencyMenu();
    return true;
  }
  if (currencyView === "pricing") {
    renderPricingCurrencyTable();
    return true;
  }
  if (currencyView === "viled") {
    renderCurrencyViledInform();
    return true;
  }
  if (currencyView === "viled-current") {
    renderCurrencyCurrentForm();
    return true;
  }
  return false;
}

function renderForecastSalesStart() {
  messagesEl.innerHTML = `
    <div class="forecast-start-screen">
      <div class="forecast-start-visual" aria-hidden="true">
        <svg class="forecast-start-sketch" viewBox="0 0 720 260" role="img">
          <defs>
            <linearGradient id="forecastStartFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stop-color="currentColor" stop-opacity="0.28" />
              <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
            </linearGradient>
          </defs>
          <path class="forecast-start-grid" d="M64 42 H668 M64 94 H668 M64 146 H668 M64 198 H668 M142 28 V224 M252 28 V224 M362 28 V224 M472 28 V224 M582 28 V224" />
          <path class="forecast-start-area" d="M64 190 C118 162 132 126 190 136 C246 146 258 82 316 94 C378 106 392 62 454 70 C520 78 538 42 668 52 L668 224 L64 224 Z" />
          <path class="forecast-start-line" d="M64 190 C118 162 132 126 190 136 C246 146 258 82 316 94 C378 106 392 62 454 70 C520 78 538 42 668 52" />
          <path class="forecast-start-dash" d="M454 70 C520 78 538 42 668 52" />
          <circle cx="454" cy="70" r="5" />
          <circle cx="668" cy="52" r="5" />
        </svg>
      </div>
      <div class="forecast-start-copy">
        <div class="answer-label">Forecast Sales</div>
        <h2>Прогноз продаж</h2>
        <p>Агент агрегирует продажи по месяцам, строит прогноз на 12 месяцев и показывает таблицу вместе с графиком.</p>
        <button id="forecastRunButton" class="forecast-run-button" type="button">
          Построить прогноз продаж
        </button>
      </div>
    </div>
  `;
}

function renderAssistantContent(content) {
  const pandasMatch = content.match(/^Source: ([\s\S]*?)\nPandas object: ([\s\S]*?)\n\nResult:\n([\s\S]*)$/);
  if (pandasMatch) {
    const [, sourceText, objectText, resultText] = pandasMatch;
    return `
      <div class="answer-section">
        <div class="answer-label-row">
          <div class="answer-label">${escapeHtml(objectText)}</div>
          ${copyButton(resultText)}
        </div>
        <div class="answer-text">Source: ${escapeHtml(sourceText)}</div>
        ${renderResultTable(resultText)}
      </div>
    `;
  }

  const match = content.match(/^SQL:\n([\s\S]*?)\n\nResult:\n([\s\S]*?)(?:\n\nExplanation:\n([\s\S]*?))?(?:\n\nChart:\n([\s\S]*))?$/);
  if (!match) {
    return escapeHtml(content);
  }

  const [, sqlText, resultText, explanationText, chartText] = match;
  const chartMarkup = chartText && chartText.trim().startsWith("<svg") ? chartText.trim() : "";
  return `
    <div class="answer-section">
      <div class="answer-label-row">
        <div class="answer-label">SQL</div>
        ${copyButton(sqlText)}
      </div>
      <pre class="answer-pre">${escapeHtml(sqlText)}</pre>
    </div>
    <div class="answer-section">
      <div class="answer-label-row">
        <div class="answer-label">Result</div>
        ${copyButton(resultText)}
      </div>
      ${renderResultTable(resultText)}
    </div>
    ${
      explanationText
        ? `
          <div class="answer-section">
            <div class="answer-label-row">
              <div class="answer-label">Explanation</div>
              ${copyButton(explanationText)}
            </div>
            <div class="answer-text">${escapeHtml(explanationText)}</div>
          </div>
        `
        : ""
    }
    ${
      chartMarkup
        ? `
          <div class="answer-section">
            <div class="answer-label-row">
              <div class="answer-label">Chart</div>
              <button class="expand-forecast-chart-button" type="button">Matplotlib detail</button>
            </div>
            <div class="forecast-chart-wrap">${chartMarkup}</div>
            <div class="forecast-detail-chart" aria-live="polite"></div>
          </div>
        `
        : ""
    }
  `;
}

function renderMessageContent(message, role) {
  if (message.error || role === "user") {
    return `
      <div class="message-copy-row">
        ${copyButton(message.content)}
      </div>
      <div>${escapeHtml(message.content)}</div>
    `;
  }
  const rendered = renderAssistantContent(message.content);
  if (rendered === escapeHtml(message.content)) {
    return `
      <div class="message-copy-row">
        ${copyButton(message.content)}
      </div>
      <div>${rendered}</div>
    `;
  }
  return rendered;
}

function renderMessages() {
  if (renderCurrencyView()) {
    return;
  }

  if (activeWorkspace === "forecast_sales" && !messages.length) {
    renderForecastSalesStart();
    return;
  }

  if (!messages.length) {
    const config = workspaceConfig[activeWorkspace];
    messagesEl.innerHTML = `
      <div class="empty-state">
        <div>
          <strong>${escapeHtml(config.emptyTitle)}</strong>
          <span>${escapeHtml(config.emptyText)}</span>
        </div>
      </div>
    `;
    return;
  }

  messagesEl.innerHTML = renderMessageList();

  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setLoading(isLoading) {
  sendButton.disabled = isLoading;
  inputEl.disabled = isLoading;
}

function autosizeInput() {
  inputEl.style.height = "auto";
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 160)}px`;
}

async function copyText(value) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

async function loadDetailedForecastChart(button) {
  const detailEl = button.closest(".answer-section")?.querySelector(".forecast-detail-chart");
  if (!detailEl) {
    return;
  }
  if (detailEl.querySelector("img")) {
    detailEl.classList.toggle("collapsed");
    button.textContent = detailEl.classList.contains("collapsed") ? "Show detail" : "Hide detail";
    return;
  }

  button.disabled = true;
  button.textContent = "Loading...";
  detailEl.classList.remove("collapsed");
  detailEl.innerHTML = `<div class="chart-loading">Building Matplotlib chart...</div>`;

  try {
    const response = await fetch("/api/forecast-sales/chart");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to build chart.");
    }
    detailEl.innerHTML = `
      <img
        class="forecast-detail-image"
        src="${escapeHtml(payload.image_data)}"
        alt="Detailed Matplotlib sales forecast"
      />
    `;
    button.textContent = "Hide detail";
  } catch (error) {
    detailEl.innerHTML = `<div class="chart-error">${escapeHtml(error.message)}</div>`;
    button.textContent = "Try again";
  } finally {
    button.disabled = false;
  }
}

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    const status = await response.json();
    modelNameEl.textContent = status.model;
  } catch {
    modelNameEl.textContent = "Unknown";
  }
}

async function loadMemory() {
  if (toolWorkspaces.has(activeWorkspace)) {
    messages = [];
    renderMessages();
    return;
  }

  try {
    const response = await fetch(`/api/memory?workspace=${encodeURIComponent(activeWorkspace)}`);
    const payload = await response.json();
    messages = payload.conversation || [];
  } catch {
    messages = [];
  }
  renderMessages();
}

async function loadHrDocuments() {
  if (!hrMemoryPanel || activeWorkspace !== "hr") {
    return;
  }

  hrMemorySummary.textContent = "Loading...";
  try {
    const response = await fetch("/api/hr/documents");
    const documents = await response.json();
    if (!response.ok) {
      throw new Error(documents.detail || "Failed to load HR documents.");
    }
    hrDocuments = documents;
    renderHrDocuments();
    const selectedSource = hrDocumentSelect.value || "";
    await loadHrChunks(selectedSource);
  } catch (error) {
    hrMemorySummary.textContent = error.message;
    hrChunkList.innerHTML = "";
  }
}

function renderHrDocuments() {
  const totalChunks = hrDocuments.reduce((sum, item) => sum + Number(item.chunk_count || 0), 0);
  hrMemorySummary.textContent = `${hrDocuments.length} docs / ${totalChunks} chunks`;
  hrDocumentSelect.innerHTML = `
    <option value="">All documents</option>
    ${hrDocuments
      .map(
        (item) => `
          <option value="${escapeHtml(item.source)}">
            ${escapeHtml(item.source)} (${item.chunk_count})
          </option>
        `,
      )
      .join("")}
  `;
}

async function loadHrChunks(source = "") {
  hrChunkList.innerHTML = `<div class="hr-memory-empty">Loading chunks...</div>`;
  const params = new URLSearchParams({ limit: "100" });
  if (source) {
    params.set("source", source);
  }

  try {
    const response = await fetch(`/api/hr/chunks?${params.toString()}`);
    const chunks = await response.json();
    if (!response.ok) {
      throw new Error(chunks.detail || "Failed to load HR chunks.");
    }
    renderHrChunks(chunks);
  } catch (error) {
    hrChunkList.innerHTML = `<div class="hr-memory-empty">${escapeHtml(error.message)}</div>`;
  }
}

async function searchHrMemory(query) {
  hrChunkList.innerHTML = `<div class="hr-memory-empty">Searching...</div>`;
  hrSearchButton.disabled = true;
  try {
    const params = new URLSearchParams({ q: query, limit: "10" });
    const response = await fetch(`/api/hr/search?${params.toString()}`);
    const chunks = await response.json();
    if (!response.ok) {
      throw new Error(chunks.detail || "Failed to search HR memory.");
    }
    renderHrChunks(chunks);
  } catch (error) {
    hrChunkList.innerHTML = `<div class="hr-memory-empty">${escapeHtml(error.message)}</div>`;
  } finally {
    hrSearchButton.disabled = false;
  }
}

function renderHrChunks(chunks) {
  if (!chunks.length) {
    hrChunkList.innerHTML = `<div class="hr-memory-empty">No chunks found.</div>`;
    return;
  }

  hrChunkList.innerHTML = chunks
    .map((chunk) => {
      const distance = chunk.distance == null ? "" : ` · distance ${Number(chunk.distance).toFixed(4)}`;
      return `
        <article class="hr-chunk">
          <div class="hr-chunk-meta">
            <strong>${escapeHtml(chunk.source || "unknown")}</strong>
            <span>page ${escapeHtml(String(chunk.page || "?"))} · chunk ${escapeHtml(String(chunk.chunk_index || "?"))}${escapeHtml(distance)}</span>
          </div>
          <p>${escapeHtml(chunk.text || "")}</p>
        </article>
      `;
    })
    .join("");
}

async function sendMessage(message) {
  messages.push({ role: "user", content: message });
  renderMessages();
  setLoading(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, workspace: activeWorkspace }),
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.detail || "Agent request failed.");
    }

    messages.push({ role: "assistant", content: payload.answer });
  } catch (error) {
    messages.push({
      role: "assistant",
      content: error.message,
      error: true,
    });
  } finally {
    setLoading(false);
    inputEl.focus();
    renderMessages();
  }
}

async function runCurrencySnapshot() {
  isCurrencySnapshotLoading = true;
  messages = [];
  renderMessages();

  try {
    const response = await fetch("/api/currency/viled-inform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.detail || "Agent request failed.");
    }

    messages = [{ role: "assistant", content: payload.answer }];
  } catch (error) {
    messages = [{
      role: "assistant",
      content: error.message,
      error: true,
    }];
  } finally {
    isCurrencySnapshotLoading = false;
    renderMessages();
  }
}

async function loadCurrencyCurrentForm() {
  isCurrencyCurrentLoading = true;
  currencyCurrentStatus = "";
  currencyView = "viled-current";
  renderMessages();

  try {
    const response = await fetch("/api/currency/viled-inform/current");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to load Viled Inform form.");
    }
    currencyCurrentRows = payload;
  } catch (error) {
    currencyCurrentRows = [];
    currencyCurrentStatus = error.message;
  } finally {
    isCurrencyCurrentLoading = false;
    renderMessages();
  }
}

async function saveCurrencyCurrentForm(form) {
  const formData = new FormData(form);
  const values = {};
  currencyCurrentRows.forEach((row) => {
    values[row.currency] = String(formData.get(row.currency) || "").trim();
  });
  currencyCurrentRows = currencyCurrentRows.map((row) => ({
    ...row,
    viled_inform: values[row.currency],
  }));

  isCurrencyCurrentSaving = true;
  currencyCurrentStatus = "";
  renderMessages();

  try {
    const response = await fetch("/api/currency/viled-inform/current", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to save Viled Inform values.");
    }
    currencyCurrentStatus = payload.message || "Saved.";
  } catch (error) {
    currencyCurrentStatus = error.message;
  } finally {
    isCurrencyCurrentSaving = false;
    renderMessages();
  }
}

function applyWorkspace(workspace) {
  activeWorkspace = workspace;
  if (workspace === "currency") {
    currencyView = "menu";
  }
  const config = workspaceConfig[workspace];
  workspaceTitleEl.textContent = config.title;
  workspaceEyebrowEl.textContent = config.eyebrow;
  inputEl.placeholder = config.placeholder;
  formEl.classList.toggle("hidden", workspace === "currency");
  resetButton.classList.toggle("hidden", toolWorkspaces.has(workspace));
  hrUploadPanel?.classList.toggle("hidden", workspace !== "hr");
  hrMemoryPanel?.classList.toggle("hidden", workspace !== "hr");
  if (workspace !== "hr" && hrUploadStatus) {
    hrUploadStatus.textContent = "";
  }
  workspaceButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.workspace === workspace);
  });
  if (workspace === "hr") {
    loadHrDocuments();
  }
}

function setCurrencyView(view) {
  currencyView = view;
  formEl.classList.toggle("hidden", activeWorkspace === "currency");
  messages = [];
  currencyCurrentStatus = "";
  renderMessages();
}

formEl.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = inputEl.value.trim();
  if (!message) {
    return;
  }

  inputEl.value = "";
  autosizeInput();
  sendMessage(message);
});

inputEl.addEventListener("input", autosizeInput);
inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    formEl.requestSubmit();
  }
});

messagesEl.addEventListener("click", async (event) => {
  const forecastRunButton = event.target.closest("#forecastRunButton");
  if (forecastRunButton && activeWorkspace === "forecast_sales") {
    await sendMessage("Построить прогноз продаж");
    return;
  }

  const currencySnapshotButton = event.target.closest("#currencySnapshotButton");
  if (currencySnapshotButton && activeWorkspace === "currency" && currencyView === "viled") {
    await runCurrencySnapshot();
    return;
  }

  const currencyCurrentEditButton = event.target.closest("#currencyCurrentEditButton");
  if (currencyCurrentEditButton && activeWorkspace === "currency" && currencyView === "viled") {
    await loadCurrencyCurrentForm();
    return;
  }

  const currencyButton = event.target.closest("[data-currency-view]");
  if (currencyButton && activeWorkspace === "currency") {
    setCurrencyView(currencyButton.dataset.currencyView);
    return;
  }

  const chartButton = event.target.closest(".expand-forecast-chart-button");
  if (chartButton) {
    await loadDetailedForecastChart(chartButton);
    return;
  }

  const button = event.target.closest(".copy-cell-button, .copy-value-button");
  if (!button) {
    return;
  }

  const value = decodeURIComponent(button.dataset.copyValue || "");
  try {
    await copyText(value);
    button.classList.add("copied");
    button.textContent = "OK";
    window.setTimeout(() => {
      button.classList.remove("copied");
      button.textContent = "Copy";
    }, 1200);
  } catch {
    button.textContent = "!";
    window.setTimeout(() => {
      button.textContent = "Copy";
    }, 1200);
  }
});

messagesEl.addEventListener("submit", async (event) => {
  const currencyCurrentForm = event.target.closest("#currencyCurrentForm");
  if (!currencyCurrentForm || activeWorkspace !== "currency" || currencyView !== "viled-current") {
    return;
  }
  event.preventDefault();
  await saveCurrencyCurrentForm(currencyCurrentForm);
});

copyInputButton.addEventListener("click", async () => {
  try {
    await copyText(inputEl.value);
    copyInputButton.classList.add("copied");
    copyInputButton.textContent = "OK";
    window.setTimeout(() => {
      copyInputButton.classList.remove("copied");
      copyInputButton.textContent = "Copy";
    }, 1200);
  } catch {
    copyInputButton.textContent = "!";
    window.setTimeout(() => {
      copyInputButton.textContent = "Copy";
    }, 1200);
  }
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    inputEl.value = button.dataset.prompt;
    autosizeInput();
    inputEl.focus();
  });
});

workspaceButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const workspace = button.dataset.workspace;
    if (!workspace || workspace === activeWorkspace) {
      return;
    }
    applyWorkspace(workspace);
    messages = [];
    renderMessages();
    loadMemory();
  });
});

resetButton.addEventListener("click", async () => {
  resetButton.disabled = true;
  try {
    await fetch(`/api/memory/reset?workspace=${encodeURIComponent(activeWorkspace)}`, { method: "POST" });
    messages = [];
    renderMessages();
  } finally {
    resetButton.disabled = false;
  }
});

hrUploadForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = hrPdfInput.files?.[0];
  if (!file) {
    hrUploadStatus.textContent = "Choose a PDF file first.";
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  hrUploadButton.disabled = true;
  hrUploadStatus.textContent = "Embedding PDF...";

  try {
    const response = await fetch("/api/hr/documents", {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to embed PDF.");
    }
    hrUploadStatus.textContent = payload.message;
    hrPdfInput.value = "";
    await loadHrDocuments();
  } catch (error) {
    hrUploadStatus.textContent = error.message;
  } finally {
    hrUploadButton.disabled = false;
  }
});

hrMemoryRefreshButton?.addEventListener("click", loadHrDocuments);

hrDocumentSelect?.addEventListener("change", () => {
  hrSearchInput.value = "";
  loadHrChunks(hrDocumentSelect.value);
});

hrSearchForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = hrSearchInput.value.trim();
  if (query) {
    searchHrMemory(query);
    return;
  }
  loadHrChunks(hrDocumentSelect.value);
});

loginForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  enterApplication();
});

loadStatus();
applyWorkspace(activeWorkspace);
loadMemory();


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
const confirmDialog = document.querySelector("#confirmDialog");

let messages = [];
let activeWorkspace = "bi_analytics";
let hrDocuments = [];
let currencyView = "dashboard";
let isCurrencySnapshotLoading = false;
let isCurrencyCurrentLoading = false;
let isCurrencyCurrentSaving = false;
let isCurrencyCurrentVisible = false;
let currencyCurrentRows = [];
let currencyCurrentStatus = "";
const toolWorkspaces = new Set(["forecast_sales", "currency"]);

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
    emptyText: "Агент умеет работать с таблицами:",
    supportedTables: [
      "[DWH].[LLM].[price]",
      "[DWH].[LLM].[sales]",
      "[DWH].[LLM].[cost]",
      "[DWH].[LLM].[stock]",
      "[DWH].[LLM].[v_purchases]",
      "[DWH].[LLM].[dimension_product]",
      "[DWH].[LLM].[division]",
    ],
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

function parseResultCsv(value) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (inQuotes) {
      if (character === '"' && value[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        inQuotes = false;
      } else {
        field += character;
      }
    } else if (character === '"' && field === "") {
      inQuotes = true;
    } else if (character === ",") {
      row.push(field.trim());
      field = "";
    } else if (character === "\n" || character === "\r") {
      if (character === "\r" && value[index + 1] === "\n") {
        index += 1;
      }
      row.push(field.trim());
      if (row.some((item) => item !== "")) {
        rows.push(row);
      }
      row = [];
      field = "";
    } else {
      field += character;
    }
  }

  row.push(field.trim());
  if (row.some((item) => item !== "")) {
    rows.push(row);
  }
  return rows;
}

function isIdentifierColumn(header) {
  const normalizedHeader = String(header || "")
    .trim()
    .toLowerCase()
    .replaceAll("[", "")
    .replaceAll("]", "");
  const headerParts = normalizedHeader.split(/[^a-zа-яё0-9]+/u).filter(Boolean);
  const identifierParts = new Set(["id", "guid", "код", "code"]);
  const identifierColumns = new Set([
    "article",
    "артикул",
    "barcode",
    "штрихкод",
    "document_number",
    "document_id",
    "doc_num",
    "individual_number",
    "recorder_number",
    "movement_index",
  ]);

  return identifierColumns.has(normalizedHeader)
    || headerParts.some((part) => identifierParts.has(part));
}

function formatNumericValue(value, header) {
  const rawValue = String(value ?? "").trim();
  if (rawValue === "" || isIdentifierColumn(header)) {
    return rawValue;
  }

  const numericMatch = rawValue.match(/^([+-]?)(\d+)([.,]\d+)?$/);
  if (!numericMatch) {
    return rawValue;
  }

  const [, sign, integerPart, decimalPart = ""] = numericMatch;
  return `${sign}${integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, " ")}${decimalPart}`;
}

function renderNumericValue(value, header) {
  const displayValue = formatNumericValue(value, header);
  if (isIdentifierColumn(header)) {
    return escapeHtml(displayValue);
  }

  const decimalMatch = displayValue.match(/^([+-]?[\d ]+)([.,]\d+)$/);
  if (!decimalMatch) {
    return escapeHtml(displayValue);
  }

  const decimalSeparator = decimalMatch[2].slice(0, 1);
  const fractionDigits = decimalMatch[2].slice(1);
  return `${escapeHtml(decimalMatch[1])}<span class="numeric-decimal"><span class="numeric-separator">${escapeHtml(decimalSeparator)}</span><span class="numeric-fraction">${escapeHtml(fractionDigits)}</span></span>`;
}

function renderResultTable(resultText) {
  const parsedRows = parseResultCsv(resultText);

  if (parsedRows.length < 2 || resultText.trim() === "No rows found.") {
    return `<pre class="answer-pre">${escapeHtml(resultText)}</pre>`;
  }

  const headers = parsedRows[0];
  const rows = parsedRows.slice(1);
  const renderCell = (value, header) => {
    let safeValue = value || "";
    const normalizedHeader = (header || "").trim().toLowerCase();
    const numericValue = Number(safeValue.replace(",", "."));
    const isNumericCell = /^[-+]?\d+(?:[.,]\d+)?$/.test(safeValue);
    const isDifCell = normalizedHeader === "dif" && safeValue !== "";
    const isNumericDif = isDifCell && Number.isFinite(numericValue);
    if (isNumericDif && numericValue === 0) {
      safeValue = "-";
    }
    const displayValue = renderNumericValue(safeValue, header);
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
      <td class="${[isNumericCell ? "numeric-cell" : "", difClass.trim()].filter(Boolean).join(" ")}"${difStyle}>
        <span class="cell-value">${displayValue}</span>
        ${copyButton(safeValue, "copy-cell-button")}
      </td>
    `;
  };

  return `
    <div class="result-table-shell">
      <div class="result-table-toolbar">
        <div class="result-table-meta">
          <strong>${rows.length}</strong>
          <span>${rows.length === 1 ? "строка" : "строк"} · ${headers.length} колонок</span>
        </div>
        <label class="result-table-search">
          <span aria-hidden="true">⌕</span>
          <input type="search" placeholder="Фильтр по таблице" aria-label="Фильтр по таблице" />
        </label>
      </div>
      <div class="result-table-wrap" tabindex="0" aria-label="Таблица результатов, доступна горизонтальная прокрутка">
        <table class="result-table">
          <thead>
            <tr>${headers.map((header) => `<th scope="col">${escapeHtml(header)}</th>`).join("")}</tr>
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
        <div class="result-table-empty" hidden>Совпадений не найдено</div>
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
      const wideClass = role === "assistant" && message.content.startsWith("SQL:\n") ? " message-wide" : "";
      return `
        <article class="message ${role}${wideClass}">
          <div class="avatar">${avatar}</div>
          <div class="bubble${errorClass}">${renderMessageContent(message, role)}</div>
        </article>
      `;
    })
    .join("");
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
            <h2>Обновить Viled Inform Fact</h2>
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

function renderCurrencyCurrentPanel() {
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

  return `
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
  `;
}

function renderCurrencySnapshotContent() {
  if (!messages.length) {
    return `<div class="currency-viled-empty">${isCurrencySnapshotLoading ? "Загрузка отчета..." : "Отчет будет загружен автоматически."}</div>`;
  }

  const latestMessage = messages[messages.length - 1];
  if (latestMessage.error) {
    return `<div class="currency-viled-empty">${escapeHtml(latestMessage.content)}</div>`;
  }

  const pandasMatch = latestMessage.content.match(/^Source: ([\s\S]*?)\nPandas object: ([\s\S]*?)\n\nResult:\n([\s\S]*)$/);
  if (pandasMatch) {
    return renderResultTable(pandasMatch[3]);
  }

  return renderAssistantContent(latestMessage.content);
}

function renderCurrencyDashboard() {
  messagesEl.innerHTML = `
    <div class="currency-viled-screen">
      <div class="currency-viled-panel">
        <section class="currency-section">
          <div class="currency-pricing-header">
            <div>
              <div class="answer-label">pandas.DataFrame</div>
              <h2>Информационный курс валют</h2>
            </div>
            <button
              id="currencySnapshotButton"
              class="currency-run-button"
              type="button"
              ${isCurrencySnapshotLoading ? "disabled" : ""}
            >
              ${isCurrencySnapshotLoading ? "Обновляется..." : "Обновить"}
            </button>
          </div>
          <div class="currency-viled-result">
            ${renderCurrencySnapshotContent()}
          </div>
        </section>
        <section class="currency-section">
          <div class="currency-pricing-header">
            <div>
              <div class="answer-label">Viled Inform Fact</div>
              <h2>Обновить Viled Inform Fact</h2>
            </div>
            <button
              id="currencyCurrentEditButton"
              class="currency-secondary-button"
              type="button"
              ${isCurrencyCurrentLoading ? "disabled" : ""}
            >
              ${isCurrencyCurrentLoading ? "Загрузка..." : "Обновить Viled Inform Fact"}
            </button>
          </div>
          ${isCurrencyCurrentVisible ? renderCurrencyCurrentPanel() : ""}
        </section>
      </div>
    </div>
  `;
}

function renderCurrencyView() {
  if (activeWorkspace !== "currency") {
    return false;
  }
  currencyView = "dashboard";
  renderCurrencyDashboard();
  return true;
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

  const [, sqlText, resultText, , chartText] = match;
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
    const supportedTables = config.supportedTables
      ? `<ul class="empty-state-list">${config.supportedTables
          .map((tableName) => `<li>${escapeHtml(tableName)}</li>`)
          .join("")}</ul>`
      : "";
    messagesEl.innerHTML = `
      <div class="empty-state">
        <div>
          <strong>${escapeHtml(config.emptyTitle)}</strong>
          <span>${escapeHtml(config.emptyText)}</span>
          ${supportedTables}
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

function buildPendingSqlAnswer(sqlText) {
  return `SQL:\n${sqlText}\n\nResult:\nExecuting query...`;
}

function updateAssistantMessage(index, patch) {
  if (!messages[index]) {
    return;
  }
  messages[index] = {
    ...messages[index],
    ...patch,
  };
  renderMessages();
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
    if (activeWorkspace === "currency" && !isCurrencySnapshotLoading) {
      await runCurrencySnapshot();
    }
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
    if (activeWorkspace === "bi_analytics") {
      await sendStreamingSqlMessage(message);
      return;
    }

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

async function sendStreamingSqlMessage(message) {
  let assistantIndex = -1;
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, workspace: activeWorkspace }),
  });

  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Agent request failed.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }
      const event = JSON.parse(line);
      if (event.event === "sql") {
        if (assistantIndex === -1) {
          assistantIndex = messages.push({
            role: "assistant",
            content: buildPendingSqlAnswer(event.sql || ""),
          }) - 1;
        } else {
          updateAssistantMessage(assistantIndex, {
            content: buildPendingSqlAnswer(event.sql || ""),
          });
        }
        renderMessages();
      } else if (event.event === "answer") {
        if (assistantIndex === -1) {
          messages.push({ role: "assistant", content: event.answer || "" });
        } else {
          updateAssistantMessage(assistantIndex, {
            content: event.answer || "",
            error: false,
          });
        }
      } else if (event.event === "error") {
        const detail = event.detail || "Agent request failed.";
        if (assistantIndex === -1) {
          throw new Error(detail);
        }
        updateAssistantMessage(assistantIndex, {
          content: detail,
          error: true,
        });
        return;
      }
    }

    if (done) {
      break;
    }
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
  isCurrencyCurrentVisible = true;
  renderMessages();

  try {
    const response = await fetch("/api/currency/viled-inform/current");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to load Viled Inform Fact form.");
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
      throw new Error(payload.detail || "Failed to save Viled Inform Fact values.");
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
    currencyView = "dashboard";
    isCurrencyCurrentVisible = false;
    currencyCurrentRows = [];
    currencyCurrentStatus = "";
  }
  const config = workspaceConfig[workspace];
  workspaceTitleEl.textContent = config.title;
  workspaceEyebrowEl.textContent = config.eyebrow;
  inputEl.placeholder = config.placeholder;
  formEl.classList.toggle("hidden", toolWorkspaces.has(workspace));
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
  formEl.classList.toggle("hidden", toolWorkspaces.has(activeWorkspace));
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
  if (currencySnapshotButton && activeWorkspace === "currency") {
    await runCurrencySnapshot();
    return;
  }

  const currencyCurrentEditButton = event.target.closest("#currencyCurrentEditButton");
  if (currencyCurrentEditButton && activeWorkspace === "currency") {
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

messagesEl.addEventListener("input", (event) => {
  const searchInput = event.target.closest(".result-table-search input");
  if (!searchInput) {
    return;
  }
  const shell = searchInput.closest(".result-table-shell");
  const query = searchInput.value.trim().toLocaleLowerCase("ru");
  let visibleRows = 0;
  shell?.querySelectorAll("tbody tr").forEach((row) => {
    const isVisible = !query || row.textContent.toLocaleLowerCase("ru").includes(query);
    row.hidden = !isVisible;
    if (isVisible) {
      visibleRows += 1;
    }
  });
  const emptyState = shell?.querySelector(".result-table-empty");
  if (emptyState) {
    emptyState.hidden = visibleRows > 0;
  }
  const count = shell?.querySelector(".result-table-meta strong");
  if (count) {
    count.textContent = String(visibleRows);
  }
});

messagesEl.addEventListener("submit", async (event) => {
  const currencyCurrentForm = event.target.closest("#currencyCurrentForm");
  if (!currencyCurrentForm || activeWorkspace !== "currency") {
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

resetButton.addEventListener("click", () => {
  if (!confirmDialog?.showModal) {
    clearActiveMemory();
    return;
  }
  confirmDialog.showModal();
});

async function clearActiveMemory() {
  resetButton.disabled = true;
  try {
    await fetch(`/api/memory/reset?workspace=${encodeURIComponent(activeWorkspace)}`, { method: "POST" });
    messages = [];
    renderMessages();
  } finally {
    resetButton.disabled = false;
  }
}

confirmDialog?.addEventListener("click", (event) => {
  if (event.target === confirmDialog) {
    confirmDialog.close("cancel");
  }
});

confirmDialog?.addEventListener("close", () => {
  if (confirmDialog.returnValue === "confirm") {
    clearActiveMemory();
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

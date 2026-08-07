const messagesEl = document.querySelector("#messages");
const loginScreen = document.querySelector("#loginScreen");
const loginForm = document.querySelector("#loginForm");
const appShell = document.querySelector("#appShell");
const formEl = document.querySelector("#chatForm");
const inputEl = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendButton");
const cancelRequestButton = document.querySelector("#cancelRequestButton");
const voiceInputButton = document.querySelector("#voiceInputButton");
const copyInputButton = document.querySelector("#copyInputButton");
const requestLoadingOverlay = document.querySelector("#requestLoadingOverlay");
const resetButton = document.querySelector("#resetButton");
const modelNameEl = document.querySelector("#modelName");
const openAiModelSelect = document.querySelector("#openAiModelSelect");
const reasoningEffortSelect = document.querySelector("#reasoningEffortSelect");
const sqlCalculationToggle = document.querySelector("#sqlCalculationToggle");
const sqlCheckModeToggle = document.querySelector("#sqlCheckModeToggle");
const workspaceTitleEl = document.querySelector("#workspaceTitle");
const workspaceEyebrowEl = document.querySelector("#workspaceEyebrow");
const chatAreaEl = document.querySelector(".chat-area");
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
const hrModeSwitcher = document.querySelector("#hrModeSwitcher");
const hrModeButtons = document.querySelectorAll("[data-hr-mode]");
const confirmDialog = document.querySelector("#confirmDialog");
const confirmDialogEyebrow = document.querySelector("#confirmDialogEyebrow");
const confirmDialogTitle = document.querySelector("#confirmDialogTitle");
const confirmDialogText = document.querySelector("#confirmDialogText");
const confirmDialogCancel = document.querySelector("#confirmDialogCancel");
const confirmDialogAccept = document.querySelector("#confirmDialogAccept");

let messages = [];
let activeWorkspace = "bi_analytics";
let hrDocuments = [];
let hrMode = "documents";
let hhAreas = [{ id: "40", name: "Весь Казахстан" }];
let hhAreasLoaded = false;
let hhVacancyResult = null;
let hhVacancyError = "";
let hhVacancyLoading = false;
let hhVacancyCriteria = null;
let currencyView = "dashboard";
let isCurrencySnapshotLoading = false;
let isCurrencyCurrentLoading = false;
let isCurrencyCurrentSaving = false;
let isCurrencyCurrentVisible = false;
let currencyCurrentRows = [];
let currencyCurrentStatus = "";
let isCurrencyPricingLoading = false;
let currencyPricingRows = [];
let currencyPricingError = "";
let voiceMediaRecorder = null;
let voiceAudioChunks = [];
let voiceRecordingTimeout = null;
let activeRequestController = null;
const toolWorkspaces = new Set(["forecast_sales", "currency", "sql_agent_docs"]);
const statusToggleStorageKeys = {
  sqlCalculationToggle: "status.sqlCalculationEnabled",
  sqlCheckModeToggle: "status.sqlCheckModeEnabled",
};
const apiSettingStorageKeys = {
  openAiModelSelect: "status.openAiModel",
  reasoningEffortSelect: "status.reasoningEffort",
};

function restoreStatusToggle(toggle) {
  if (!toggle) {
    return;
  }
  const savedValue = localStorage.getItem(statusToggleStorageKeys[toggle.id]);
  if (savedValue !== null) {
    toggle.checked = savedValue === "true";
  }
  toggle.addEventListener("change", () => {
    localStorage.setItem(statusToggleStorageKeys[toggle.id], String(toggle.checked));
  });
}

restoreStatusToggle(sqlCalculationToggle);
restoreStatusToggle(sqlCheckModeToggle);

function restoreApiSetting(select) {
  if (!select) {
    return;
  }
  const storageKey = apiSettingStorageKeys[select.id];
  const savedValue = localStorage.getItem(storageKey);
  if (savedValue && [...select.options].some((option) => option.value === savedValue)) {
    select.value = savedValue;
  }
  select.addEventListener("change", () => {
    localStorage.setItem(storageKey, select.value);
  });
}

restoreApiSetting(openAiModelSelect);
restoreApiSetting(reasoningEffortSelect);

function syncOpenAiSettingsState() {
  const calculationEnabled = sqlCalculationToggle?.checked ?? true;
  const checkEnabled = sqlCheckModeToggle?.checked ?? true;
  const openAiEnabled = calculationEnabled || checkEnabled;
  for (const select of [openAiModelSelect, reasoningEffortSelect]) {
    if (select) {
      select.disabled = !openAiEnabled;
    }
  }
}

sqlCalculationToggle?.addEventListener("change", syncOpenAiSettingsState);
sqlCheckModeToggle?.addEventListener("change", syncOpenAiSettingsState);
syncOpenAiSettingsState();

function sqlApiModeLabel(mode) {
  if (mode === "calculation") {
    return "Chat GPT API · формирование SQL";
  }
  if (mode === "disabled") {
    return "Chat GPT API · отключено";
  }
  return "Chat GPT API · проверка SQL";
}

function buildChatRequest(message) {
  return {
    message,
    workspace: activeWorkspace,
    sql_calculation_enabled: sqlCalculationToggle?.checked ?? true,
    sql_check_mode_enabled: sqlCheckModeToggle?.checked ?? true,
    openai_model: openAiModelSelect?.value || "gpt-5.6",
    reasoning_effort: reasoningEffortSelect?.value || "medium",
  };
}

function showConfirmation({
  eyebrow = "Подтверждение действия",
  title,
  text = "",
  acceptLabel = "Продолжить",
  danger = false,
}) {
  if (!confirmDialog?.showModal) {
    return Promise.resolve(window.confirm([title, text].filter(Boolean).join("\n\n")));
  }

  confirmDialogEyebrow.textContent = eyebrow;
  confirmDialogTitle.textContent = title;
  confirmDialogText.textContent = text;
  confirmDialogText.hidden = !text;
  confirmDialogCancel.textContent = "Отмена";
  confirmDialogAccept.textContent = acceptLabel;
  confirmDialogAccept.classList.toggle("dialog-button-primary", !danger);
  confirmDialogAccept.classList.toggle("dialog-button-danger", danger);

  return new Promise((resolve) => {
    confirmDialog.addEventListener(
      "close",
      () => resolve(confirmDialog.returnValue === "confirm"),
      { once: true },
    );
    confirmDialog.showModal();
  });
}

function paidSqlConfirmationRequired() {
  return (
    activeWorkspace === "bi_analytics"
    && ((sqlCalculationToggle?.checked ?? true) || (sqlCheckModeToggle?.checked ?? true))
  );
}

async function confirmPaidSqlRequest() {
  if (!paidSqlConfirmationRequired()) {
    return true;
  }
  return showConfirmation({
    eyebrow: "Подтверждение запроса",
    title: "Платный запрос с использованием внешнего API",
    acceptLabel: "Продолжить",
  });
}

function enterApplication() {
  loginScreen?.classList.add("hidden");
  appShell?.classList.remove("is-hidden");
  inputEl.focus();
}

const workspaceConfig = {
  bi_analytics: {
    title: "SQL Analytic",
    eyebrow: "Agent Team / SQL Analytic",
    emptyTitle: "Спросите бизнес — получите данные",
    emptyText: "Опишите задачу обычным языком или вставьте готовый SELECT. Агент подберёт данные, построит безопасный SQL-запрос и покажет результат.",
    capabilities: [
      ["Продажи", "Сумма, количество, скидки, способы оплаты, каналы, рейтинги и динамика."],
      ["Цены", "Актуальные цены и история изменений в KZT, USD и EUR."],
      ["Товары", "Карточки, артикулы, бренды, категории, сезоны, размеры и другие атрибуты."],
      ["Остатки", "Остаток на дату или период, движения и разрез по складам."],
      ["Себестоимость и закупки", "Операции, стоимость единицы, балансы, закупочные суммы и НДС."],
      ["Сложная аналитика", "GM, цена без НДС, текущая себестоимость и фильтры из нескольких таблиц."],
    ],
    questionExamples: [
      {
        level: "Быстрый вопрос",
        text: "Покажи последние цены товара 1231235 во всех валютах",
      },
      {
        level: "Быстрый вопрос",
        text: "Покажи карточку товара по артикулу G062214",
      },
      {
        level: "Аналитика",
        text: "Топ-10 товаров бренда Cartier по сумме продаж в KZT за март 2026",
      },
      {
        level: "Аналитика",
        text: "Сумма продаж ювелирного направления за апрель 2026 с группировкой по брендам",
      },
      {
        level: "Сложный вопрос",
        text: "Покажи остаток товара 1231230 на начало и конец марта 2025 по складам",
      },
      {
        level: "Сложный вопрос",
        text: "Рассчитай GM по артикулу 2807742, 2814951 с учетом скидки 30%",
      },
    ],
    placeholder: "Спросите про продажи, цены, товары, остатки, закупки или GM...",
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
  sql_agent_docs: {
    title: "SQL Agent Map",
    eyebrow: "Docs / Architecture",
    emptyTitle: "Архитектура SQL-агента",
    emptyText: "Локальная LLM, режимы OpenAI и безопасный доступ к SQL Server.",
    placeholder: "",
    avatar: "DOC",
  },
  hr: {
    title: "HR",
    eyebrow: "Agent Team / HR",
    emptyTitle: "Корпоративные HR-документы",
    emptyText: "Загрузите PDF, задавайте вопросы по внутренним правилам или перейдите в область найма сотрудников.",
    placeholder: "Спросите по загруженным HR-документам...",
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

  const [, sign, rawIntegerPart, decimalPart = ""] = numericMatch;
  let integerPart = rawIntegerPart;
  let formattedDecimalPart = "";

  if (decimalPart) {
    const decimalSeparator = decimalPart.slice(0, 1);
    const fractionDigits = decimalPart.slice(1);
    let roundedFraction = fractionDigits.slice(0, 2).padEnd(2, "0");

    if (fractionDigits.length > 2 && Number(fractionDigits[2]) >= 5) {
      const roundedValue = BigInt(integerPart) * 100n + BigInt(roundedFraction) + 1n;
      integerPart = String(roundedValue / 100n);
      roundedFraction = String(roundedValue % 100n).padStart(2, "0");
    }

    formattedDecimalPart = `${decimalSeparator}${roundedFraction}`;
  }

  return `${sign}${integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, " ")}${formattedDecimalPart}`;
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
  const isTotalsRow = (row) => row.some(
    (value) => String(value || "").trim().toUpperCase() === "ИТОГО",
  );
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
                  <tr${isTotalsRow(row) ? ' class="result-table-total-row"' : ""}>
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
      const avatarMarkup =
        role === "user"
          ? `<div class="user-copy-control">${copyButton(message.content)}</div>`
          : `<div class="avatar">${avatar}</div>`;
      const errorClass = message.error ? " error" : "";
      const wideClass = role === "assistant" && message.content.startsWith("SQL:\n") ? " message-wide" : "";
      return `
        <article class="message ${role}${wideClass}">
          ${avatarMarkup}
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

function renderCurrencyPricingContent() {
  if (currencyPricingError) {
    return `<div class="currency-viled-empty">${escapeHtml(currencyPricingError)}</div>`;
  }
  if (!currencyPricingRows.length) {
    return `<div class="currency-viled-empty">${isCurrencyPricingLoading ? "Загрузка курсов..." : "Курсы ценообразования не найдены."}</div>`;
  }

  const csvRows = [
    ["DATE", "Currency", "rate"],
    ...currencyPricingRows.map((row) => [row.date, row.currency, row.rate]),
  ];
  const csv = csvRows
    .map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(","))
    .join("\n");
  return renderResultTable(csv);
}

function renderCurrencyDashboard() {
  messagesEl.innerHTML = `
    <div class="currency-viled-screen">
      <div class="currency-viled-panel">
        <section class="currency-section">
          <div class="currency-pricing-header">
            <div>
              <div class="answer-label">SQLite · currency_pricing</div>
              <h2>Курс Ценообразования</h2>
            </div>
          </div>
          <div class="currency-viled-result">
            ${renderCurrencyPricingContent()}
          </div>
        </section>
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

function formatHhSalary(vacancy) {
  const formatter = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
  const from = vacancy.salary_from == null ? "" : formatter.format(vacancy.salary_from);
  const to = vacancy.salary_to == null ? "" : formatter.format(vacancy.salary_to);
  if (!from && !to) {
    return "Зарплата не указана";
  }
  const range = from && to ? `${from} — ${to}` : from ? `от ${from}` : `до ${to}`;
  const tax = vacancy.salary_gross == null ? "" : vacancy.salary_gross ? " · до вычета налогов" : " · на руки";
  return `${range} ${vacancy.salary_currency || "KZT"}${tax}`;
}

function plainHhSnippet(value) {
  return String(value || "").replace(/<[^>]+>/g, "").trim();
}

function renderHrRecruitment() {
  const result = hhVacancyResult;
  const selectedArea = hhVacancyCriteria?.area || "40";
  const vacancyCards = result?.items?.length
    ? result.items.map((vacancy) => {
        const requirement = plainHhSnippet(vacancy.snippet_requirement);
        const responsibility = plainHhSnippet(vacancy.snippet_responsibility);
        return `
          <article class="hh-vacancy-card">
            <div class="hh-vacancy-card-header">
              <div>
                <span>${escapeHtml(vacancy.area || "Казахстан")}</span>
                <h3>${escapeHtml(vacancy.name)}</h3>
                <p>${escapeHtml(vacancy.employer || "Работодатель не указан")}</p>
              </div>
              <strong>${escapeHtml(formatHhSalary(vacancy))}</strong>
            </div>
            <div class="hh-vacancy-meta">
              ${vacancy.experience ? `<span>${escapeHtml(vacancy.experience)}</span>` : ""}
              ${vacancy.published_at ? `<span>${escapeHtml(new Date(vacancy.published_at).toLocaleDateString("ru-RU"))}</span>` : ""}
              <span>hh.kz · ID ${escapeHtml(vacancy.id)}</span>
            </div>
            ${responsibility ? `<p><b>Задачи:</b> ${escapeHtml(responsibility)}</p>` : ""}
            ${requirement ? `<p><b>Требования:</b> ${escapeHtml(requirement)}</p>` : ""}
            <a href="${escapeHtml(vacancy.url)}" target="_blank" rel="noopener noreferrer">Открыть вакансию на hh.kz ↗</a>
          </article>
        `;
      }).join("")
    : result
      ? `<div class="hh-vacancy-empty">По заданным фильтрам вакансии не найдены.</div>`
      : `<div class="hh-vacancy-empty">Укажите должность и запустите поиск. По умолчанию поиск выполняется по всему Казахстану.</div>`;

  const page = result?.page || 0;
  const pages = result?.pages || 0;
  messagesEl.innerHTML = `
    <section class="hr-recruitment-screen">
      <header class="hr-recruitment-intro">
        <div>
          <span class="answer-label">HH.KZ API · RECRUITMENT</span>
          <h2>Поиск вакансий</h2>
          <p>Фильтруйте открытые позиции по региону, опыту, зарплате и дате публикации.</p>
        </div>
        <span class="hh-api-badge">Официальный API hh</span>
      </header>
      <form id="hhVacancyForm" class="hh-vacancy-form">
        <label class="hh-field hh-field-wide">
          <span>Должность или ключевые слова</span>
          <input name="text" type="search" maxlength="3000" required placeholder="Например: HR business partner" value="${escapeHtml(hhVacancyCriteria?.text || "")}" />
        </label>
        <label class="hh-field">
          <span>Регион</span>
          <select name="area">
            ${hhAreas.map((area) => `<option value="${escapeHtml(area.id)}" ${area.id === selectedArea ? "selected" : ""}>${escapeHtml(area.name)}</option>`).join("")}
          </select>
        </label>
        <label class="hh-field">
          <span>Опыт</span>
          <select name="experience">
            <option value="">Любой опыт</option>
            <option value="noExperience" ${hhVacancyCriteria?.experience === "noExperience" ? "selected" : ""}>Без опыта</option>
            <option value="between1And3" ${hhVacancyCriteria?.experience === "between1And3" ? "selected" : ""}>От 1 до 3 лет</option>
            <option value="between3And6" ${hhVacancyCriteria?.experience === "between3And6" ? "selected" : ""}>От 3 до 6 лет</option>
            <option value="moreThan6" ${hhVacancyCriteria?.experience === "moreThan6" ? "selected" : ""}>Более 6 лет</option>
          </select>
        </label>
        <label class="hh-field">
          <span>Зарплата от, KZT</span>
          <input name="salary" type="number" min="0" step="5000" placeholder="300 000" value="${escapeHtml(hhVacancyCriteria?.salary ?? "")}" />
        </label>
        <label class="hh-field">
          <span>Опубликовано</span>
          <select name="period">
            <option value="">За всё время</option>
            <option value="1" ${hhVacancyCriteria?.period === 1 ? "selected" : ""}>За сутки</option>
            <option value="3" ${hhVacancyCriteria?.period === 3 ? "selected" : ""}>За 3 дня</option>
            <option value="7" ${hhVacancyCriteria?.period === 7 ? "selected" : ""}>За неделю</option>
            <option value="30" ${hhVacancyCriteria?.period === 30 ? "selected" : ""}>За месяц</option>
          </select>
        </label>
        <label class="hh-field">
          <span>Сортировка</span>
          <select name="order_by">
            <option value="publication_time" ${hhVacancyCriteria?.order_by !== "relevance" ? "selected" : ""}>Сначала новые</option>
            <option value="relevance" ${hhVacancyCriteria?.order_by === "relevance" ? "selected" : ""}>По соответствию</option>
          </select>
        </label>
        <label class="hh-checkbox">
          <input name="only_with_salary" type="checkbox" ${hhVacancyCriteria?.only_with_salary ? "checked" : ""} />
          <span>Только с указанной зарплатой</span>
        </label>
        <button class="hh-search-button" type="submit" ${hhVacancyLoading ? "disabled" : ""}>${hhVacancyLoading ? "Ищем…" : "Найти вакансии"}</button>
      </form>
      ${hhVacancyError ? `<div class="hh-vacancy-error">${escapeHtml(hhVacancyError)}</div>` : ""}
      <div class="hh-results-header">
        <strong>${result ? `Найдено: ${new Intl.NumberFormat("ru-RU").format(result.found)}` : "Результаты поиска"}</strong>
        ${result ? `<span>Страница ${page + 1} из ${Math.max(pages, 1)}</span>` : ""}
      </div>
      <div class="hh-vacancy-list">${vacancyCards}</div>
      ${result && pages > 1 ? `<nav class="hh-pagination"><button type="button" data-hh-page="${page - 1}" ${page <= 0 ? "disabled" : ""}>← Назад</button><button type="button" data-hh-page="${page + 1}" ${page + 1 >= pages ? "disabled" : ""}>Дальше →</button></nav>` : ""}
    </section>
  `;
}

async function loadHhAreas() {
  if (hhAreasLoaded) {
    return;
  }
  try {
    const response = await fetch("/api/hr/hh/areas");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Не удалось загрузить регионы hh.kz.");
    }
    hhAreas = payload;
    hhAreasLoaded = true;
  } catch (error) {
    hhVacancyError = error.message;
  }
  if (activeWorkspace === "hr" && hrMode === "recruitment") {
    renderHrRecruitment();
  }
}

async function searchHhVacancies(criteria) {
  hhVacancyCriteria = criteria;
  hhVacancyLoading = true;
  hhVacancyError = "";
  renderHrRecruitment();
  try {
    const response = await fetch("/api/hr/hh/vacancies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(criteria),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Поиск вакансий завершился ошибкой.");
    }
    hhVacancyResult = payload;
  } catch (error) {
    hhVacancyResult = null;
    hhVacancyError = error.message;
  } finally {
    hhVacancyLoading = false;
    renderHrRecruitment();
  }
}

function renderAssistantContent(message) {
  const content = message.content;
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
  const reviewText = message.sqlReview || "Проверка выполняется...";
  const sqlApiLabel = message.sqlApiLabel || sqlApiModeLabel("check");
  return `
    <div class="answer-section sql-output-section">
      <div class="answer-label-row">
        <div class="answer-label-meta">
          <div class="answer-label">SQL</div>
          ${renderExecutionTimer(message.sqlDuration)}
        </div>
        ${copyButton(sqlText)}
      </div>
      <pre class="answer-pre sql-query-pre">${escapeHtml(sqlText)}</pre>
    </div>
    <div class="answer-section sql-output-section">
      <div class="answer-label-row">
        <div class="answer-label-meta">
          <div class="answer-label">${escapeHtml(sqlApiLabel)}</div>
          ${renderExecutionTimer(message.reviewDuration, message.reviewPending)}
        </div>
        ${copyButton(reviewText)}
      </div>
      <pre class="answer-pre sql-query-pre sql-review-pre">${escapeHtml(reviewText)}</pre>
    </div>
    <div class="answer-section result-output-section">
      <div class="answer-label-row">
        <div class="answer-label-meta">
          <div class="answer-label">Result</div>
          ${renderExecutionTimer(message.resultDuration, message.resultPending)}
        </div>
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

function renderExecutionTimer(durationSeconds, pending = false) {
  const duration = Number(durationSeconds);
  if (Number.isFinite(duration) && duration >= 0) {
    return `<span class="execution-timer">${duration.toFixed(2)} с</span>`;
  }
  if (pending) {
    return `<span class="execution-timer execution-timer-pending">выполняется…</span>`;
  }
  return "";
}

function renderMessageContent(message, role) {
  if (role === "user") {
    return `<div>${escapeHtml(message.content)}</div>`;
  }
  if (message.error) {
    return `<div class="message-copy-row">${copyButton(message.content)}</div><div>${escapeHtml(message.content)}</div>`;
  }
  const rendered = renderAssistantContent(message);
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

function renderSqlAgentDocs() {
  messagesEl.innerHTML = `
    <article class="docs-report" aria-label="Презентация архитектуры SQL-агента">
      <section class="docs-slide docs-slide-architecture">
        <header class="docs-slide-header">
          <div>
            <span class="docs-kicker">VILED ATLAS · ARCHITECTURE BRIEF</span>
            <h2>SQL-агент: локальное выполнение,<br />управляемый OpenAI</h2>
          </div>
          <button id="docsPrintButton" class="docs-print-button" type="button">
            Сохранить в PDF
          </button>
        </header>

        <p class="docs-lead">
          Запрос проходит через один локальный контур выполнения. OpenAI может
          сформировать или проверить SQL, но не подключается к базе и не видит результат.
        </p>

        <div class="architecture-map">
          <section class="architecture-column architecture-entry">
            <span class="architecture-step">01 · Вход</span>
            <div class="architecture-card architecture-card-user">
              <span class="architecture-card-tag">Интерфейс</span>
              <strong>BI Analytics</strong>
              <p>Web UI · FastAPI<br />POST /api/chat</p>
            </div>
          </section>

          <section class="architecture-column architecture-router">
            <span class="architecture-step">02 · Маршрутизация</span>
            <div class="architecture-card architecture-card-neutral">
              <span class="architecture-card-tag">Оркестратор</span>
              <strong>WebSqlAgent</strong>
              <p>Выбирает режим SQL и передаёт запрос в SqlAgentService.</p>
              <div class="architecture-toggle-row">
                <span>SQL CALCULATION</span>
                <span>SQL CHECK MODE</span>
              </div>
            </div>
          </section>

          <section class="architecture-column architecture-engines">
            <span class="architecture-step">03 · Формирование SQL</span>
            <div class="architecture-card architecture-card-local">
              <span class="architecture-card-tag">Локальный контур</span>
              <strong>IntentParser → SqlBuilder</strong>
              <p>Правила сначала. LM Studio используется как fallback для намерения.</p>
              <small>llama-3.2-3b-instruct · 127.0.0.1</small>
            </div>
            <div class="architecture-card architecture-card-openai">
              <span class="architecture-card-tag">OpenAI API</span>
              <strong>SQL Generation</strong>
              <p>Активен только при включённом SQL CALCULATION.</p>
            </div>
          </section>

          <section class="architecture-column architecture-safety">
            <span class="architecture-step">04 · Контроль</span>
            <div class="architecture-card architecture-card-guard">
              <span class="architecture-card-tag">Локальная защита</span>
              <strong>Read-only validator</strong>
              <p>Разрешён один SELECT / CTE. Изменяющие команды блокируются.</p>
            </div>
            <div class="architecture-card architecture-card-openai architecture-card-review">
              <span class="architecture-card-tag">OpenAI API</span>
              <strong>SQL Review</strong>
              <p>Проверяет смысл локального SQL. Рекомендация не исполняется автоматически.</p>
            </div>
          </section>

          <section class="architecture-column architecture-data">
            <span class="architecture-step">05 · Данные</span>
            <div class="architecture-card architecture-card-data">
              <span class="architecture-card-tag">Локальная инфраструктура</span>
              <strong>Microsoft SQL Server</strong>
              <p>DWH.LLM.* · LLM.sales</p>
              <div class="architecture-data-result">
                <span>Результат</span>
                <strong>SQL + строки + пояснение</strong>
              </div>
            </div>
          </section>
        </div>

        <div class="architecture-flowline" aria-label="Основной путь запроса">
          <span>Запрос</span><i>→</i><span>Выбор режима</span><i>→</i>
          <span>SQL</span><i>→</i><span>Валидация</span><i>→</i>
          <span>SQL Server</span><i>→</i><span>Ответ</span>
        </div>

        <footer class="docs-slide-footer">
          <span>Источник: docs/sql_agent_architecture.md</span>
          <span>01 / 02</span>
        </footer>
      </section>

      <section class="docs-slide docs-slide-modes">
        <header class="docs-slide-header docs-slide-header-compact">
          <div>
            <span class="docs-kicker">OPERATING MODES</span>
            <h2>Три режима — одна граница безопасности</h2>
          </div>
        </header>

        <div class="mode-grid">
          <article class="mode-card mode-card-openai">
            <span class="mode-number">01</span>
            <div class="mode-switches">
              <span class="switch-on">CALC · ON</span>
              <span>CHECK · ANY</span>
            </div>
            <h3>OpenAI формирует SQL</h3>
            <p>Повторная проверка пропускается. Локальное приложение валидирует и выполняет запрос.</p>
            <strong class="mode-result">Выполняется SQL от OpenAI</strong>
          </article>

          <article class="mode-card mode-card-hybrid">
            <span class="mode-number">02</span>
            <div class="mode-switches">
              <span>CALC · OFF</span>
              <span class="switch-on">CHECK · ON</span>
            </div>
            <h3>Локальный SQL + проверка</h3>
            <p>OpenAI оценивает смысл и показывает рекомендацию отдельно от исполнения.</p>
            <strong class="mode-result">Выполняется исходный локальный SQL</strong>
          </article>

          <article class="mode-card mode-card-local">
            <span class="mode-number">03</span>
            <div class="mode-switches">
              <span>CALC · OFF</span>
              <span>CHECK · OFF</span>
            </div>
            <h3>Полностью локальный режим</h3>
            <p>IntentParser и SqlBuilder формируют запрос без обращения к OpenAI.</p>
            <strong class="mode-result">Выполняется исходный локальный SQL</strong>
          </article>
        </div>

        <div class="trust-boundary">
          <section class="trust-zone trust-zone-local">
            <span class="trust-zone-label">Локальная зона</span>
            <h3>Данные остаются внутри проекта</h3>
            <ul>
              <li>SQL Server и драйверы подключения</li>
              <li>Строки результата и форматирование</li>
              <li>Память диалогов и схема выполнения</li>
            </ul>
          </section>
          <div class="trust-transfer" aria-label="Разрешённая передача в OpenAI">
            <span>Передаётся</span>
            <strong>запрос · docs · SQL для review</strong>
            <i>→</i>
            <small>Не передаются: инструменты БД и результат</small>
          </div>
          <section class="trust-zone trust-zone-openai">
            <span class="trust-zone-label">Внешняя зона</span>
            <h3>OpenAI API</h3>
            <ul>
              <li>Генерация read-only SQL</li>
              <li>Семантическая проверка SQL</li>
              <li>Нет доступа к SQL Server</li>
            </ul>
          </section>
        </div>

        <div class="docs-callout">
          <span>Ключевой принцип</span>
          <strong>Модель предлагает SQL. Локальное приложение решает, что можно выполнить.</strong>
        </div>

        <footer class="docs-slide-footer">
          <span>Viled ATLAS LLM Project · SQL Agent Architecture</span>
          <span>02 / 02</span>
        </footer>
      </section>
    </article>
  `;
}

function renderMessages() {
  if (activeWorkspace === "sql_agent_docs") {
    renderSqlAgentDocs();
    return;
  }

  if (renderCurrencyView()) {
    return;
  }

  if (activeWorkspace === "hr" && hrMode === "recruitment") {
    renderHrRecruitment();
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
    const capabilities = config.capabilities
      ? `
        <section class="sql-capabilities" aria-labelledby="sqlCapabilitiesTitle">
          <h2 id="sqlCapabilitiesTitle">Что можно анализировать</h2>
          <ul>
            ${config.capabilities
              .map(
                ([title, description]) => `
                  <li>
                    <strong>${escapeHtml(title)}</strong>
                    <span>${escapeHtml(description)}</span>
                  </li>
                `,
              )
              .join("")}
          </ul>
        </section>
      `
      : "";
    const questionExamples = config.questionExamples
      ? `
        <section class="sql-question-panel" aria-labelledby="sqlQuestionsTitle">
          <div class="sql-question-heading">
            <span>Примеры запросов</span>
            <h2 id="sqlQuestionsTitle">От простых<br />до сложных</h2>
            <p>Нажмите на вопрос, чтобы перенести его в поле ввода.</p>
          </div>
          <div class="sql-question-list">
            ${config.questionExamples
              .map(
                ({ level, text: question }) => `
                  <button type="button" class="sql-question-card" data-example-question="${escapeHtml(question)}">
                    <span>${escapeHtml(level)}</span>
                    <strong>${escapeHtml(question)}</strong>
                    <i aria-hidden="true">↗</i>
                  </button>
                `,
              )
              .join("")}
          </div>
        </section>
      `
      : "";
    messagesEl.innerHTML = `
      <div class="empty-state${config.questionExamples ? " sql-empty-state" : ""}">
        <div class="sql-empty-intro">
          <strong>${escapeHtml(config.emptyTitle)}</strong>
          <span>${escapeHtml(config.emptyText)}</span>
          ${supportedTables}
          ${capabilities}
        </div>
        ${questionExamples}
      </div>
    `;
    return;
  }

  messagesEl.innerHTML = renderMessageList();

  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setLoading(isLoading) {
  sendButton.disabled = isLoading;
  sendButton.classList.toggle("hidden", isLoading);
  cancelRequestButton.classList.toggle("hidden", !isLoading);
  cancelRequestButton.disabled = false;
  inputEl.disabled = isLoading;
  voiceInputButton.disabled = isLoading;
  requestLoadingOverlay.classList.toggle("hidden", !isLoading);
}

function markRequestCancelled() {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === "assistant" && messages[index].resultPending) {
      messages[index] = {
        ...messages[index],
        content: messages[index].content.replace(
          "Executing query...",
          "Запрос отменён пользователем.",
        ),
        error: false,
        reviewPending: false,
        resultPending: false,
      };
      return;
    }
  }
  messages.push({
    role: "assistant",
    content: "Запрос отменён пользователем.",
  });
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
  const maxInputHeight = Math.max(160, Math.floor(window.innerHeight * 0.6));
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, maxInputHeight)}px`;
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
    if (!localStorage.getItem(apiSettingStorageKeys.openAiModelSelect)) {
      openAiModelSelect.value = status.openai_model || "gpt-5.6";
    }
    if (!localStorage.getItem(apiSettingStorageKeys.reasoningEffortSelect)) {
      reasoningEffortSelect.value = status.openai_reasoning_effort || "medium";
    }
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
      const distance = chunk.distance == null ? "" : ` · distance ${Number(chunk.distance).toFixed(2)}`;
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
  const requestController = new AbortController();
  activeRequestController = requestController;
  messages.push({ role: "user", content: message });
  renderMessages();
  setLoading(true);

  try {
    if (activeWorkspace === "bi_analytics") {
      await sendStreamingSqlMessage(message, requestController.signal);
      return;
    }

    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildChatRequest(message)),
      signal: requestController.signal,
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.detail || "Agent request failed.");
    }

    messages.push({ role: "assistant", content: payload.answer });
  } catch (error) {
    if (error.name === "AbortError") {
      markRequestCancelled();
    } else {
      messages.push({
        role: "assistant",
        content: error.message,
        error: true,
      });
    }
  } finally {
    if (activeRequestController === requestController) {
      activeRequestController = null;
      setLoading(false);
    }
    inputEl.focus();
    renderMessages();
  }
}

async function sendStreamingSqlMessage(message, signal) {
  let assistantIndex = -1;
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildChatRequest(message)),
    signal,
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
        const calculationEnabled = sqlCalculationToggle?.checked ?? true;
        const checkEnabled = sqlCheckModeToggle?.checked ?? true;
        const pendingMode = calculationEnabled
          ? "calculation"
          : checkEnabled
            ? "check"
            : "disabled";
        const pendingReview = calculationEnabled
          ? "OpenAI API формирует SQL..."
          : checkEnabled
            ? "Проверка выполняется..."
            : "Проверка отключена";
        if (assistantIndex === -1) {
          assistantIndex = messages.push({
            role: "assistant",
            content: buildPendingSqlAnswer(event.sql || ""),
            sqlReview: pendingReview,
            sqlApiLabel: sqlApiModeLabel(pendingMode),
            sqlDuration: event.duration_seconds,
            reviewPending: true,
            resultPending: true,
          }) - 1;
        } else {
          updateAssistantMessage(assistantIndex, {
            content: buildPendingSqlAnswer(event.sql || ""),
            sqlReview: pendingReview,
            sqlApiLabel: sqlApiModeLabel(pendingMode),
            sqlDuration: event.duration_seconds,
            reviewPending: true,
            resultPending: true,
          });
        }
        renderMessages();
      } else if (event.event === "sql_review") {
        if (assistantIndex !== -1) {
          updateAssistantMessage(assistantIndex, {
            sqlReview: event.review || "Проверка отключена",
            sqlApiLabel: sqlApiModeLabel(event.mode),
            reviewDuration: event.duration_seconds,
            reviewPending: false,
          });
        }
      } else if (event.event === "answer") {
        if (assistantIndex === -1) {
          messages.push({ role: "assistant", content: event.answer || "" });
        } else {
          updateAssistantMessage(assistantIndex, {
            content: event.answer || "",
            error: false,
            resultDuration: event.duration_seconds,
            resultPending: false,
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
  isCurrencyPricingLoading = true;
  currencyPricingError = "";
  messages = [];
  renderMessages();

  const pricingRequest = loadCurrencyPricing();
  try {
    const snapshotResponse = await fetch("/api/currency/viled-inform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const payload = await snapshotResponse.json();

    if (!snapshotResponse.ok) {
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
    await pricingRequest;
    isCurrencySnapshotLoading = false;
    isCurrencyPricingLoading = false;
    renderMessages();
  }
}

async function loadCurrencyPricing() {
  try {
    const response = await fetch("/api/currency/pricing/latest");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to load currency pricing.");
    }
    currencyPricingRows = payload;
    currencyPricingError = "";
  } catch (error) {
    currencyPricingRows = [];
    currencyPricingError = error.message;
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
  const recruitmentMode = workspace === "hr" && hrMode === "recruitment";
  chatAreaEl?.classList.toggle("hr-workspace-active", workspace === "hr");
  formEl.classList.toggle("hidden", toolWorkspaces.has(workspace) || recruitmentMode);
  resetButton.classList.toggle("hidden", toolWorkspaces.has(workspace) || recruitmentMode);
  hrModeSwitcher?.classList.toggle("hidden", workspace !== "hr");
  hrUploadPanel?.classList.toggle("hidden", workspace !== "hr" || recruitmentMode);
  hrMemoryPanel?.classList.toggle("hidden", workspace !== "hr" || recruitmentMode);
  if (workspace !== "hr" && hrUploadStatus) {
    hrUploadStatus.textContent = "";
  }
  workspaceButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.workspace === workspace);
  });
  hrModeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.hrMode === hrMode);
  });
  if (workspace === "hr" && hrMode === "documents") {
    loadHrDocuments();
  } else if (workspace === "hr") {
    loadHhAreas();
  }
}

function setHrMode(mode) {
  if (!['documents', 'recruitment'].includes(mode) || mode === hrMode) {
    return;
  }
  hrMode = mode;
  applyWorkspace("hr");
  renderMessages();
}

function setCurrencyView(view) {
  currencyView = view;
  formEl.classList.toggle("hidden", toolWorkspaces.has(activeWorkspace));
  messages = [];
  currencyCurrentStatus = "";
  renderMessages();
}

formEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = inputEl.value.trim();
  if (!message) {
    return;
  }

  if (!(await confirmPaidSqlRequest())) {
    inputEl.focus();
    return;
  }

  inputEl.value = "";
  autosizeInput();
  sendMessage(message);
});

cancelRequestButton.addEventListener("click", async () => {
  if (!activeRequestController) {
    return;
  }
  const confirmed = await showConfirmation({
    eyebrow: "Подтверждение отмены",
    title: "Отменить текущий запрос?",
    text: "Получение ответа будет остановлено. Уже выполненную часть операции восстановить нельзя.",
    acceptLabel: "Отменить запрос",
    danger: true,
  });
  if (confirmed && activeRequestController) {
    cancelRequestButton.disabled = true;
    activeRequestController.abort();
  }
});

inputEl.addEventListener("input", autosizeInput);
inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    formEl.requestSubmit();
  }
});

function setVoiceButtonState(state, message = "") {
  voiceInputButton.classList.toggle("recording", state === "recording");
  voiceInputButton.classList.toggle("processing", state === "processing");
  voiceInputButton.classList.toggle("error", state === "error");
  voiceInputButton.disabled = state === "processing";
  voiceInputButton.setAttribute(
    "aria-label",
    state === "recording" ? "Остановить запись" : "Начать голосовой ввод",
  );
  voiceInputButton.title = message;
  if (state === "error") {
    window.setTimeout(() => setVoiceButtonState("idle", message), 3000);
  }
}

async function transcribeVoiceRecording(audioBlob) {
  setVoiceButtonState("processing", "Распознавание речи...");
  const formData = new FormData();
  const extension = audioBlob.type.includes("ogg") ? "ogg" : "webm";
  formData.append("file", audioBlob, `voice-input.${extension}`);

  try {
    const response = await fetch("/api/voice/transcribe", {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Не удалось распознать речь.");
    }
    if (payload.text) {
      const separator = inputEl.value && !inputEl.value.endsWith(" ") ? " " : "";
      inputEl.value += `${separator}${payload.text}`;
      autosizeInput();
      inputEl.focus();
    }
    setVoiceButtonState("idle", payload.text ? "Речь распознана" : "Речь не обнаружена");
  } catch (error) {
    setVoiceButtonState("error", error.message);
  }
}

async function startVoiceRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setVoiceButtonState("error", "Браузер не поддерживает запись звука.");
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    voiceAudioChunks = [];
    voiceMediaRecorder = new MediaRecorder(stream);
    voiceMediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) {
        voiceAudioChunks.push(event.data);
      }
    });
    voiceMediaRecorder.addEventListener("stop", () => {
      stream.getTracks().forEach((track) => track.stop());
      window.clearTimeout(voiceRecordingTimeout);
      const audioBlob = new Blob(voiceAudioChunks, {
        type: voiceMediaRecorder.mimeType || "audio/webm",
      });
      voiceMediaRecorder = null;
      transcribeVoiceRecording(audioBlob);
    });
    voiceMediaRecorder.start();
    setVoiceButtonState("recording", "Идёт запись. Нажмите ещё раз для остановки.");
    voiceRecordingTimeout = window.setTimeout(() => {
      if (voiceMediaRecorder?.state === "recording") {
        voiceMediaRecorder.stop();
      }
    }, 60000);
  } catch {
    setVoiceButtonState("error", "Нет доступа к микрофону.");
  }
}

voiceInputButton.addEventListener("click", () => {
  if (voiceMediaRecorder?.state === "recording") {
    voiceMediaRecorder.stop();
    return;
  }
  startVoiceRecording();
});

messagesEl.addEventListener("click", async (event) => {
  const hhPageButton = event.target.closest("[data-hh-page]");
  if (hhPageButton && activeWorkspace === "hr" && hrMode === "recruitment" && hhVacancyCriteria) {
    await searchHhVacancies({
      ...hhVacancyCriteria,
      page: Number(hhPageButton.dataset.hhPage || 0),
    });
    return;
  }

  const exampleQuestionButton = event.target.closest("[data-example-question]");
  if (exampleQuestionButton && activeWorkspace === "bi_analytics") {
    inputEl.value = exampleQuestionButton.dataset.exampleQuestion || "";
    autosizeInput();
    inputEl.focus();
    return;
  }

  const docsPrintButton = event.target.closest("#docsPrintButton");
  if (docsPrintButton && activeWorkspace === "sql_agent_docs") {
    window.print();
    return;
  }

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
  const hhVacancyForm = event.target.closest("#hhVacancyForm");
  if (hhVacancyForm && activeWorkspace === "hr" && hrMode === "recruitment") {
    event.preventDefault();
    const formData = new FormData(hhVacancyForm);
    await searchHhVacancies({
      text: String(formData.get("text") || "").trim(),
      area: String(formData.get("area") || "40"),
      experience: String(formData.get("experience") || "") || null,
      salary: formData.get("salary") ? Number(formData.get("salary")) : null,
      only_with_salary: formData.get("only_with_salary") === "on",
      period: formData.get("period") ? Number(formData.get("period")) : null,
      order_by: String(formData.get("order_by") || "publication_time"),
      page: 0,
      per_page: 20,
    });
    return;
  }

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

hrModeButtons.forEach((button) => {
  button.addEventListener("click", () => setHrMode(button.dataset.hrMode || "documents"));
});

resetButton.addEventListener("click", async () => {
  const confirmed = await showConfirmation({
    title: "Очистить память агента?",
    text: "История текущего диалога будет удалена. Это действие нельзя отменить.",
    acceptLabel: "Очистить",
    danger: true,
  });
  if (confirmed) {
    clearActiveMemory();
  }
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

const initialParams = new URLSearchParams(window.location.search);
const initialWorkspace = initialParams.get("view");
if (initialWorkspace && workspaceConfig[initialWorkspace]) {
  activeWorkspace = initialWorkspace;
}
if (initialParams.get("print") === "1" && activeWorkspace === "sql_agent_docs") {
  document.title = "Viled ATLAS — SQL Agent Architecture";
  enterApplication();
}

loadStatus();
applyWorkspace(activeWorkspace);
loadMemory();

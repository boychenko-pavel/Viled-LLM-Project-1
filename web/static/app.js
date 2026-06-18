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
    emptyText: "Агент умеет отвечать про DWH.LLM.price и LLM.sales.",
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
    eyebrow: "Agent Team / Forecast Sales",
    emptyTitle: "Построить прогноз продаж",
    emptyText: "Агент агрегирует LLM.sales по месяцам и строит прогноз на 12 месяцев.",
    placeholder: "Напишите: сделай прогноз продаж на 1 год по месяцам",
    avatar: "FC",
  },
  currency: {
    title: "Currency",
    eyebrow: "Agent Team / Currency",
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
  return value
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
  const renderCell = (value) => {
    const safeValue = value || "";
    return `
      <td>
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
                    .map((_, index) => renderCell(row[index] || ""))
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

  messagesEl.innerHTML = messages
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

function applyWorkspace(workspace) {
  activeWorkspace = workspace;
  const config = workspaceConfig[workspace];
  workspaceTitleEl.textContent = config.title;
  workspaceEyebrowEl.textContent = config.eyebrow;
  inputEl.placeholder = config.placeholder;
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

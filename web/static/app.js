const messagesEl = document.querySelector("#messages");
const formEl = document.querySelector("#chatForm");
const inputEl = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendButton");
const copyInputButton = document.querySelector("#copyInputButton");
const resetButton = document.querySelector("#resetButton");
const modelNameEl = document.querySelector("#modelName");

let messages = [];

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
  const match = content.match(/^SQL:\n([\s\S]*?)\n\nResult:\n([\s\S]*?)(?:\n\nExplanation:\n([\s\S]*))?$/);
  if (!match) {
    return escapeHtml(content);
  }

  const [, sqlText, resultText, explanationText] = match;
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
    messagesEl.innerHTML = `
      <div class="empty-state">
        <div>
          <strong>Задайте вопрос по базе данных</strong>
          <span>Агент умеет отвечать про BI.actual_retail_price и BI.sales_table.</span>
        </div>
      </div>
    `;
    return;
  }

  messagesEl.innerHTML = messages
    .map((message) => {
      const role = message.role === "user" ? "user" : "assistant";
      const avatar = role === "user" ? "YOU" : "SQL";
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
    const response = await fetch("/api/memory");
    const payload = await response.json();
    messages = payload.conversation || [];
  } catch {
    messages = [];
  }
  renderMessages();
}

async function sendMessage(message) {
  messages.push({ role: "user", content: message });
  renderMessages();
  setLoading(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
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

resetButton.addEventListener("click", async () => {
  resetButton.disabled = true;
  try {
    await fetch("/api/memory/reset", { method: "POST" });
    messages = [];
    renderMessages();
  } finally {
    resetButton.disabled = false;
  }
});

loadStatus();
loadMemory();

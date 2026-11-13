/**
 * Efatha's e-Chat Logic
 * The server runs an independent agent, and an API agent when Gemini or Grok is active.
 */

// DOM elements
const msgInput = document.getElementById("message-input");
const sendMsgBtn = document.querySelector(".send-message");
const eChatBody = document.querySelector(".chat-body");
const eFile = document.querySelector("#e-file");
const fileUploadWrapper = document.querySelector(".file-upload-wrapper");
const memoryLinks = document.querySelector("#memory-links");
const memorySearch = document.querySelector("#memory-search-input");
const newConversationButton = document.querySelector("#new-conversation");
const memoryToggle = document.querySelector("#memory-toggle");
const appShell = document.querySelector(".app-shell");
const chatWelcome = document.querySelector("#chat-welcome");
const THREADS_KEY = "eChatConversationThreads";
const OLD_MEMORY_KEY = "eChatConversationMemory";
const ACTIVE_KEY = "eChatActiveConversation";
let activeConversationId = null;

const userData = {
  message: null,
  file: { data: null, mime_type: null }
};

const readThreads = () => {
  try {
    const stored = JSON.parse(localStorage.getItem(THREADS_KEY) || "[]");
    return Array.isArray(stored) ? stored : [];
  } catch (_error) {
    return [];
  }
};

const saveThreads = (threads) => {
  localStorage.setItem(THREADS_KEY, JSON.stringify(threads.slice(0, 100)));
};

const newConversationId = () => typeof crypto.randomUUID === "function"
  ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

const conversationTitle = (message) => {
  const clean = String(message || "").replace(/\s+/g, " ").trim();
  if (!clean) return "New conversation";
  return clean.length > 38 ? `${clean.slice(0, 38).trim()}…` : clean;
};

const currentThread = () => readThreads().find((thread) => thread.id === activeConversationId);

const clearChatPanel = () => {
  eChatBody.querySelectorAll(":scope > .message").forEach((node) => node.remove());
};

const setWelcomeVisible = (visible) => {
  chatWelcome.hidden = !visible;
};

const toggleMemory = () => {
  const isOpen = appShell.classList.toggle("memory-open");
  memoryToggle.setAttribute("aria-expanded", String(isOpen));
  memoryToggle.setAttribute("aria-label", isOpen ? "Close memory" : "Open memory");
};

const renderMemoryLinks = (filter = "") => {
  const query = filter.trim().toLowerCase();
  const threads = readThreads().filter((thread) =>
    !query || String(thread.title || "").toLowerCase().includes(query)
  );
  memoryLinks.innerHTML = "";
  if (!threads.length) {
    memoryLinks.innerHTML = '<p class="memory-empty">No saved conversations yet. Start chatting and the topic will appear here.</p>';
    return;
  }
  threads.forEach((thread) => {
    const row = document.createElement("div");
    row.className = `memory-row${thread.id === activeConversationId ? " active" : ""}`;

    const link = document.createElement("button");
    link.type = "button";
    link.className = "memory-link";
    link.textContent = thread.title || "Conversation";
    link.title = thread.title || "Conversation";
    link.addEventListener("click", () => openConversation(thread.id));

    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "memory-action";
    rename.textContent = "Edit";
    rename.setAttribute("aria-label", `Rename ${thread.title || "conversation"}`);
    rename.addEventListener("click", () => beginRename(row, thread.id));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "memory-action memory-delete";
    remove.textContent = "Delete";
    remove.setAttribute("aria-label", `Delete ${thread.title || "conversation"}`);
    remove.addEventListener("click", () => deleteConversation(thread.id));

    row.append(link, rename, remove);
    memoryLinks.appendChild(row);
  });
};

const updateThreadTitle = (conversationId, title) => {
  const clean = String(title || "").replace(/\s+/g, " ").trim();
  if (!clean) return;
  const threads = readThreads();
  const thread = threads.find((item) => item.id === conversationId);
  if (!thread) return;
  thread.title = clean.length > 80 ? `${clean.slice(0, 80).trim()}…` : clean;
  thread.updatedAt = new Date().toISOString();
  saveThreads(threads);
  renderMemoryLinks(memorySearch.value);
};

const beginRename = (row, conversationId) => {
  const thread = readThreads().find((item) => item.id === conversationId);
  if (!thread) return;
  const link = row.querySelector(".memory-link");
  const input = document.createElement("input");
  input.className = "memory-rename";
  input.type = "text";
  input.value = thread.title || "";
  input.setAttribute("aria-label", "Conversation title");
  input.maxLength = 80;
  let finished = false;
  const finish = (save) => {
    if (finished) return;
    finished = true;
    if (save) updateThreadTitle(conversationId, input.value);
    else renderMemoryLinks(memorySearch.value);
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      finish(true);
    }
    if (event.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
  link.replaceWith(input);
  input.focus();
  input.select();
};

const deleteConversation = (conversationId) => {
  const threads = readThreads().filter((thread) => thread.id !== conversationId);
  saveThreads(threads);
  if (activeConversationId === conversationId) {
    activeConversationId = null;
    localStorage.removeItem(ACTIVE_KEY);
    clearChatPanel();
    setWelcomeVisible(true);
  }
  renderMemoryLinks(memorySearch.value);
};

const weatherIcon = (kind) => {
  const icons = {
    sun: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" fill="#f5c542"/><g stroke="#f5c542" stroke-width="2" stroke-linecap="round"><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/></g></svg>',
    moon: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#8eb6ff" d="M15 3a8 8 0 1 0 6 13 7 7 0 1 1-6-13z"/></svg>',
    cloud: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#c5ccd4" d="M7 18h10a4 4 0 0 0 .4-8 6 6 0 0 0-11.5-1.5A3.5 3.5 0 0 0 7 18z"/></svg>',
    rain: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#c5ccd4" d="M7 14h10a4 4 0 0 0 .4-8 6 6 0 0 0-11.5-1.5A3.5 3.5 0 0 0 7 14z"/><path stroke="#6aa7ff" stroke-width="2" stroke-linecap="round" d="M8 17l-1 3M12 17l-1 3M16 17l-1 3"/></svg>',
    snow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#e8eef5" d="M12 2l1.2 4.2L17 7l-3.8.8L12 12l-1.2-4.2L7 7l3.8-.8zM6 14l.8 2.2L9 17l-2.2.8L6 20l-.8-2.2L3 17l2.2-.8zM18 14l.8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8z"/></svg>',
    storm: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#9aa3ad" d="M7 13h10a4 4 0 0 0 .4-8 6 6 0 0 0-11.5-1.5A3.5 3.5 0 0 0 7 13z"/><path fill="#f5c542" d="M13 12l-4 6h3l-1 4 5-7h-3z"/></svg>',
    fog: '<svg viewBox="0 0 24 24" aria-hidden="true"><path stroke="#c5c8ce" stroke-width="2" stroke-linecap="round" d="M4 9h16M3 13h18M5 17h14"/></svg>'
  };
  return icons[kind] || icons.cloud;
};

const renderWeather = (card) => {
  const root = document.createElement("div");
  root.className = "weather-card";
  if (card.query) root.dataset.place = card.query;
  const degree = (value) => (value == null ? "—" : `${value}°C`);
  const hours = (card.hours || []).map((hour) => `
    <div class="weather-hour">
      <span>${escapeHtml(hour.time || "")}</span>
      ${weatherIcon(hour.icon)}
      <strong>${hour.rain == null ? "" : `${hour.rain}%`}</strong>
      <b>${hour.temperature == null ? "" : `${hour.temperature}°`}</b>
    </div>`).join("");
  root.innerHTML = `
    <div class="weather-top">
      <div>
        <p class="weather-temp">${degree(card.temperature)}</p>
        <p class="weather-condition">${escapeHtml(card.condition || "")}</p>
        <p class="weather-where">${escapeHtml(card.place || "")}${card.clock ? ` · ${escapeHtml(card.reading || "Last reading")} ${escapeHtml(card.clock)}` : ""}</p>
      </div>
      <div class="weather-mark">${weatherIcon(card.icon)}</div>
    </div>
    <div class="weather-facts">
      <p><span>Today's high</span><strong>${degree(card.high)}</strong></p>
      <p><span>Tonight's low</span><strong>${degree(card.low)}</strong></p>
      <p><span>Rain chance at this reading</span><strong>${card.rain == null ? "—" : `${card.rain}%`}</strong></p>
      <p><span>Humidity</span><strong>${escapeHtml(card.humidity || "—")}</strong></p>
    </div>
    <div class="weather-hours">${hours}</div>
    <p class="weather-source">e-chat</p>`;
  return root;
};

const renderCommons = (photo) => {
  const figure = document.createElement("figure");
  figure.className = "commons-photo";
  const image = document.createElement("img");
  image.src = photo.thumbnail;
  image.alt = photo.title || "Wikimedia Commons image";
  figure.appendChild(image);
  const caption = document.createElement("figcaption");
  const credit = document.createElement("a");
  credit.href = photo.page;
  credit.target = "_blank";
  credit.rel = "noopener";
  credit.textContent = photo.creator || "Wikimedia Commons";
  caption.appendChild(credit);
  caption.appendChild(document.createTextNode(" · " + (photo.license || "Commons")));
  figure.appendChild(caption);
  return figure;
};

const renderTranslation = (card) => {
  const root = document.createElement("div");
  root.className = "translate-card";
  const rows = (card.rows || []).map((row) => `
    <tr>
      <td>${escapeHtml(row.pronoun || "")}</td>
      <td class="tr-form">${escapeHtml(row.form || "")}</td>
      <td>${escapeHtml(row.english || "")}</td>
    </tr>`).join("");
  const examples = (card.examples || []).map((item) =>
    `<li><span class="tr-form">${escapeHtml(item.phrase || "")}</span> – ${escapeHtml(item.meaning || "")}</li>`
  ).join("");
  const table = rows ? `
    <p class="tr-note">Present tense</p>
    <table class="tr-table">
      <thead><tr><th>Pronoun</th><th>Conjugation</th><th>English</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>` : "";
    const list = examples
      ? `<p class="tr-note">${card.kind === "sentence" ? "Breakdown" : "Common examples"}</p><ul class="tr-examples">${examples}</ul>`
      : "";
  const others = (card.others || []).map((item) =>
    `<li><span class="tr-form">${escapeHtml(item.phrase || "")}</span> – ${escapeHtml(item.meaning || "")}</li>`
  ).join("");
  const otherList = others ? `<p class="tr-note">Every language</p><ul class="tr-examples">${others}</ul>` : "";
  root.innerHTML = `
    <p class="tr-word">${escapeHtml(card.word || "")}</p>
    ${table}${list}${otherList}`;
  return root;
};

const formMark = (mark) => {
  const kind = mark === "W" ? "win" : mark === "D" ? "draw" : mark === "L" ? "loss" : "none";
  const glyph = mark === "W" ? "✓" : mark === "D" ? "–" : mark === "L" ? "×" : "";
  return `<span class="form-mark ${kind}" aria-label="${kind}">${glyph}</span>`;
};

const renderStanding = (card) => {
  const root = document.createElement("section");
  root.className = "standings";
  const head = document.createElement("header");
  head.innerHTML = `<p class="standings-title">STANDINGS</p><p class="standings-group">${escapeHtml(card.group || "")}</p>`;
  root.appendChild(head);
  const table = document.createElement("table");
  table.className = "standings-table";
  const showForm = (card.rows || []).some((row) => (row.form || []).length);
  table.innerHTML = `
    <thead>
      <tr>
        <th></th><th>Club</th>
        <th>MP</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th>
        ${showForm ? "<th>Last 5</th>" : ""}
      </tr>
    </thead>`;
  const body = document.createElement("tbody");
  (card.rows || []).forEach((row) => {
    const cells = row.cells || [];
    const form = (row.form || []).slice(-5);
    const formCell = !showForm
      ? ""
      : form.length
        ? `<td class="form">${form.concat(Array(Math.max(0, 5 - form.length)).fill("")).map(formMark).join("")}</td>`
        : `<td class="form"></td>`;
    const line = document.createElement("tr");
    if (row.asked) line.className = "asked";
    line.innerHTML = `
      <td class="rank">${escapeHtml(row.rank || "")}</td>
      <td class="club"><span class="club-line"><img src="${escapeHtml(row.logo || "")}" alt="" onerror="this.remove()"><span>${escapeHtml(row.team || "")}</span></span></td>
      ${cells.map((value, index) => `<td${index === 7 ? ' class="pts"' : ""}>${escapeHtml(value || "")}</td>`).join("")}
      ${formCell}</tr>`;
    body.appendChild(line);
  });
  table.appendChild(body);
  root.appendChild(table);
  if (showForm) {
    const legend = document.createElement("div");
    legend.className = "form-legend";
    legend.innerHTML = `
      <p>Last 5 matches</p>
      <p>${formMark("W")} Win</p>
      <p>${formMark("D")} Draw</p>
      <p>${formMark("L")} Loss</p>
      <p>${formMark("")} Not played</p>`;
    root.appendChild(legend);
  }
  return root;
};

const renderSports = (card) => {
  if (card && card.kind === "standing") return renderStanding(card);
  const root = document.createElement("div");
  root.className = "match-board";
  const title = document.createElement("p");
  title.className = "match-board-title";
  title.textContent = card.title || "Matches";
  root.appendChild(title);
  (card.matches || []).forEach((match) => {
    const row = document.createElement("article");
    row.className = "match-row";
    const logo = (src, alt) => src
      ? `<img class="match-logo" src="${escapeHtml(src)}" alt="">`
      : "";
    row.innerHTML = `
      <div class="match-line">
        ${logo(match.homeLogo, match.home)}
        <span class="team-chip">${escapeHtml(match.home || "")}</span>
      </div>
      <span class="score-chip">${escapeHtml(match.score || "vs")}</span>
      <div class="match-line">
        ${logo(match.awayLogo, match.away)}
        <span class="team-chip">${escapeHtml(match.away || "")}</span>
      </div>
      <p class="match-detail">${escapeHtml(match.detail || "")}</p>`;
    root.appendChild(row);
  });
  return root;
};

const renderPortrait = (photo) => {
  const src = photo && typeof photo === "object" ? photo.src : "";
  if (!src) return null;
  const figure = document.createElement("figure");
  figure.className = "sports-portrait";
  const image = document.createElement("img");
  image.src = src;
  image.alt = photo.alt || "";
  image.addEventListener("error", () => figure.remove());
  figure.appendChild(image);
  if (photo.caption) {
    const caption = document.createElement("figcaption");
    caption.textContent = photo.caption;
    figure.appendChild(caption);
  }
  return figure;
};

const highlightMarks = (html) => String(html || "").replace(
  /⟦([^⟧]+)⟧/g,
  '<span class="grad-text">$1</span>'
);

const paintDefinition = (text) => {
  const escaped = escapeHtml(String(text || "")).replace(/\n/g, "<br>");
  return escaped.replace(/(^|<br>|[.!?]\s*)- ([^<]+)/, (all, lead, body) =>
    `${lead}<span class="def-lead">- ${body}</span>`);
};

const renderStoredMessage = (item) => {
  if (!item || !["user", "assistant"].includes(item.role)) return;
  const classes = item.role === "user" ? "user-message" : "bot-message";
  const avatar = item.role === "assistant"
    ? '<img class="bot-avatar" src="/static/images/artificial-intelligence.gif" alt="">'
    : "";
  const body = /\[[^\]]+\]\(https?:\/\//.test(String(item.content || ""))
    ? highlightMarks(formatMarked(String(item.content || "")))
    : highlightMarks(paintDefinition(item.content || ""));
  const element = createMsgElement(
    `${avatar}<div class="message-text">${body}</div>`,
    classes
  );
  if (item.weather) {
    element.querySelector(".message-text").classList.add("weather-bubble");
    element.querySelector(".message-text").appendChild(renderWeather(item.weather));
  }
  if (item.commons) element.querySelector(".message-text").appendChild(renderCommons(item.commons));
  if (item.translation) element.querySelector(".message-text").appendChild(renderTranslation(item.translation));
  if (item.sports && item.sports.kind === "standing") {
    element.classList.add("has-standings");
    element.appendChild(renderSports(item.sports));
  } else if (item.sports) element.querySelector(".message-text").appendChild(renderSports(item.sports));
  const storedPhoto = renderPortrait(item.portrait);
  if (storedPhoto) element.querySelector(".message-text").appendChild(storedPhoto);
  eChatBody.insertBefore(element, eChatBody.querySelector(".echat-footer"));
};

const openConversation = (conversationId) => {
  const thread = readThreads().find((item) => item.id === conversationId);
  if (!thread) return;
  activeConversationId = thread.id;
  localStorage.setItem(ACTIVE_KEY, thread.id);
  clearChatPanel();
  setWelcomeVisible(false);
  (thread.messages || []).forEach(renderStoredMessage);
  renderMemoryLinks(memorySearch.value);
  eChatBody.scrollTo({ top: eChatBody.scrollHeight });
};

const startNewConversation = () => {
  activeConversationId = null;
  localStorage.removeItem(ACTIVE_KEY);
  clearChatPanel();
  setWelcomeVisible(true);
  renderMemoryLinks(memorySearch.value);
  msgInput.focus();
};

const ensureConversation = (firstMessage) => {
  if (activeConversationId && currentThread()) return currentThread();
  const id = newConversationId();
  const thread = {
    id,
    title: conversationTitle(firstMessage),
    messages: [],
    updatedAt: new Date().toISOString()
  };
  const threads = readThreads();
  threads.unshift(thread);
  saveThreads(threads);
  activeConversationId = id;
  localStorage.setItem(ACTIVE_KEY, id);
  setWelcomeVisible(false);
  renderMemoryLinks(memorySearch.value);
  return thread;
};

const addThreadMessage = (conversationId, role, content, dictionary, weather, commons, translation, sports, portrait) => {
  const threads = readThreads();
  const index = threads.findIndex((thread) => thread.id === conversationId);
  if (index < 0) return;
  threads[index].messages = Array.isArray(threads[index].messages) ? threads[index].messages : [];
  const message = { role, content, created_at: new Date().toISOString() };
  if (dictionary) message.dictionary = dictionary;
  if (weather) message.weather = weather;
  if (commons) message.commons = commons;
  if (translation) message.translation = translation;
  if (sports) message.sports = sports;
  if (portrait) message.portrait = portrait;
  threads[index].messages.push(message);
  threads[index].updatedAt = new Date().toISOString();
  const [updated] = threads.splice(index, 1);
  threads.unshift(updated);
  saveThreads(threads);
  renderMemoryLinks(memorySearch.value);
};

const migrateOldMemory = () => {
  try {
    if (readThreads().length) return;
    const oldMessages = JSON.parse(localStorage.getItem(OLD_MEMORY_KEY) || "[]");
    if (!Array.isArray(oldMessages) || !oldMessages.length) return;
    const firstUser = oldMessages.find((item) => item.role === "user");
    saveThreads([{
      id: newConversationId(),
      title: conversationTitle(firstUser && firstUser.content),
      messages: oldMessages,
      updatedAt: new Date().toISOString()
    }]);
    localStorage.removeItem(OLD_MEMORY_KEY);
  } catch (_error) {
    localStorage.removeItem(OLD_MEMORY_KEY);
  }
};

// Helper to create message elements
const createMsgElement = (content, classes) => {
  const div = document.createElement("div");
  div.classList.add("message", classes);
  div.innerHTML = content;
  return div;
};

const finishMessage = (incomingMsgDiv) => {
  incomingMsgDiv.classList.remove("thinking");
  eChatBody.scrollTo({ top: eChatBody.scrollHeight, behavior: "smooth" });
};

const escapeHtml = (value) => value
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;");

const colorWords = (escaped) => escaped.replace(
  /\b(python|java|javascript|html|css|code)\b/gi,
  (word) => {
    const key = word.toLowerCase() === "javascript" ? "js" : word.toLowerCase();
    return `<span class="tok-word tok-${key}">${word}</span>`;
  }
);

const indentGuides = (line) => {
  const spaces = (line.match(/^( *)/) || [""])[0];
  const steps = Math.floor(spaces.length / 2);
  const leftover = spaces.length % 2;
  let guides = "";
  for (let i = 0; i < steps; i += 1) guides += '<span class="indent-guide">  </span>';
  if (leftover) guides += " ";
  return { guides, body: line.slice(spaces.length) };
};

const paintHtml = (body) => {
  let src = escapeHtml(body);
  src = src.replace(/(&lt;!--[\s\S]*?--&gt;)/g, '<span class="tok-c">$1</span>');
  src = src.replace(/(&lt;!DOCTYPE)(\s+)([a-zA-Z]+)/gi, '<span class="tok-punct">$1</span>$2<span class="tok-name">$3</span>');
  src = src.replace(/(&lt;\/?)([a-zA-Z][\w-]*)([^&]*?)(\/?&gt;)/g, (_full, open, tag, rest, close) => {
    const attrs = rest.replace(
      /([a-zA-Z_:][\w:.-]*)(=)("[^"]*")/g,
      '<span class="tok-attr">$1</span><span class="tok-punct">$2</span><span class="tok-str">$3</span>'
    );
    return `<span class="tok-punct">${open}</span><span class="tok-tag">${tag}</span>${attrs}<span class="tok-punct">${close}</span>`;
  });
  src = src.replace(/(^|[{;])\s*([a-zA-Z-]+)(\s*:)/g, '$1 <span class="tok-attr">$2</span><span class="tok-punct">$3</span>');
  return src;
};

const paintCode = (body) => {
  let src = escapeHtml(body);
  src = src.replace(/(#[^\n]*|\/\/[^\n]*)/g, '<span class="tok-c">$1</span>');
  src = src.replace(/(&quot;[^&]*&quot;|"[^"\n]*"|'[^'\n]*')/g, '<span class="tok-str">$1</span>');
  src = src.replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="tok-num">$1</span>');
  src = src.replace(
    /\b(def|class|return|if|else|for|while|import|from|public|static|void|new|function|const|let|var|print)\b/g,
    '<span class="tok-key">$1</span>'
  );
  src = src.replace(/\b([A-Za-z_][\w]*)(?=\s*\()/g, '<span class="tok-fn">$1</span>');
  return src;
};

const highlightCode = (code, language) => {
  const lang = (language || "").toLowerCase();
  const htmlLike = lang === "html" || /<\s*\/?[a-z!]/i.test(code);
  const lines = String(code).replace(/\n$/, "").split("\n");
  return lines.map((line, index) => {
    const { guides, body } = indentGuides(line);
    const painted = htmlLike ? paintHtml(body) : paintCode(body);
    const number = String(index + 1);
    return `<div class="code-line"><span class="ln">${number}</span><span class="code-text">${guides}${painted}</span></div>`;
  }).join("");
};

const COPY_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M4 16V6a2 2 0 0 1 2-2h10" fill="none" stroke="currentColor" stroke-width="2"/></svg>';

const renderReply = (text, blocks) => {
  const sourceText = String(text || "");
  const re = /```([a-zA-Z0-9+#]*)\n([\s\S]*?)```/g;
  let html = "";
  let cursor = 0;
  let match;
  while ((match = re.exec(sourceText)) !== null) {
    const prose = sourceText.slice(cursor, match.index).trim();
    if (prose) html += `<div class="reply-prose">${colorWords(escapeHtml(prose)).replace(/\n/g, "<br>")}</div>`;
    const language = (match[1] || "code").toLowerCase();
    const source = match[2].replace(/\n$/, "");
    blocks.push(source);
    const labels = { html: "HTML", python: "Python", java: "Java", css: "CSS", javascript: "JavaScript" };
    const label = labels[language] || language.toUpperCase();
    html += `<div class="code-card"><div class="code-bar"><span>${label}</span><button type="button" class="code-copy" aria-label="Copy code">${COPY_ICON}<span>Copy</span></button></div><div class="code-lines">${highlightCode(source, language)}</div></div>`;
    cursor = match.index + match[0].length;
  }
  const tail = sourceText.slice(cursor).trim();
  if (tail) html += `<div class="reply-prose">${colorWords(escapeHtml(tail)).replace(/\n/g, "<br>")}</div>`;
  if (!html) html = `<div class="reply-prose">${colorWords(escapeHtml(sourceText))}</div>`;
  return html;
};

const formatMarked = (text) => escapeHtml(text)
  .replace(
    /!\[([^\]\n]*)\]\((https:\/\/[^\s)"']+)\)/g,
    '<img class="src-icon" alt="$1" src="$2">'
  )
  .replace(
    /\[([^\]\n]+)\]\((https:\/\/[^\s)"']+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  )
  .replace(/\*([^*\n]+)\*/g, "<strong>$1</strong>")
  .replace(/_([^_\n]+)_/g, "<em>$1</em>")
  .replace(/`([^`\n]+)`/g, "<code>$1</code>")
  .replace(/\bp\. \d+/g, "<em>$&</em>")
  .replace(/\*/g, "")
  .replace(/\n/g, "<br>");

const wireCopyButtons = (root, blocks) => {
  root.querySelectorAll(".code-copy").forEach((button, index) => {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(blocks[index] || "");
        const label = button.querySelector("span");
        label.textContent = "Copied";
        button.classList.add("copied");
        setTimeout(() => {
          label.textContent = "Copy";
          button.classList.remove("copied");
        }, 1400);
      } catch (error) {
        console.error("Copy failed:", error);
      }
    });
  });
};

// Ask the server. It uses the independent agent, or the API when that API is active.
const generateEchatResponse = async (incomingMsgDiv, conversationId, sentMessage) => {
  const msgElement = incomingMsgDiv.querySelector(".message-text");
  const thread = readThreads().find((item) => item.id === conversationId);
  const pageName = new URLSearchParams(window.location.search).get("name");
  const payload = {
    message: sentMessage || "",
    conversation_id: conversationId,
    memory: ((thread && thread.messages) || []).slice(-40)
  };
  if (pageName) payload.username = pageName;
  if (thread && thread.focus) payload.focus = thread.focus;
  if (userData.file.data) payload.file = userData.file;
  userData.file = { data: null, mime_type: null };

  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    let data;
    try {
      data = await response.json();
    } catch (_error) {
      throw new Error(`Backend returned an unreadable response (HTTP ${response.status}).`);
    }

    if (!response.ok) {
      throw new Error(data.error || `Backend request failed (HTTP ${response.status}).`);
    }

    if (data.response) {
      msgElement.classList.remove("backend-error");
      const hasCode = /```[a-zA-Z0-9+#]*\n[\s\S]*?```/.test(data.response);
      const hasMarks = /\*[^*\n]+\*/.test(data.response) || /_[^_\n]+_/.test(data.response) || /\bp\. \d+/.test(data.response) || /\[[^\]]+\]\(https?:\/\//.test(data.response);
      if (hasCode) {
        const blocks = [];
        msgElement.innerHTML = highlightMarks(renderReply(data.response, blocks));
        msgElement.style.backgroundColor = "";
        msgElement.style.color = "";
        msgElement.style.padding = "";
        wireCopyButtons(msgElement, blocks);
      } else if (hasMarks) {
        msgElement.innerHTML = highlightMarks(formatMarked(data.response));
        if (data.source === "independent") {
          msgElement.style.backgroundColor = "#397d92";
          msgElement.style.color = "#fff8f2";
        }
      } else {
        msgElement.innerHTML = highlightMarks(paintDefinition(data.response));
        if (data.source === "independent") {
          msgElement.style.backgroundColor = "#397d92";
          msgElement.style.color = "#fff8f2";
        }
      }
      if (data.weather) {
        msgElement.classList.add("weather-bubble");
        msgElement.appendChild(renderWeather(data.weather));
      }
      if (data.sports && data.sports.kind === "standing") {
        incomingMsgDiv.classList.add("has-standings");
        incomingMsgDiv.appendChild(renderSports(data.sports));
      }
      const sportsPhoto = renderPortrait(data.portrait);
      if (sportsPhoto) msgElement.appendChild(sportsPhoto);
      if (data.translation) msgElement.appendChild(renderTranslation(data.translation));
      if (data.commons && data.commons.thumbnail) {
        const figure = document.createElement("figure");
        figure.className = "commons-photo";
        const image = document.createElement("img");
        image.src = data.commons.thumbnail;
        image.alt = data.commons.title || "Wikimedia Commons image";
        figure.appendChild(image);
        const caption = document.createElement("figcaption");
        const credit = document.createElement("a");
        credit.href = data.commons.page;
        credit.target = "_blank";
        credit.rel = "noopener";
        credit.textContent = data.commons.creator || "Wikimedia Commons";
        caption.appendChild(credit);
        caption.appendChild(document.createTextNode(" · " + (data.commons.license || "Commons")));
        if (data.commons.license_url) {
          const license = document.createElement("a");
          license.href = data.commons.license_url;
          license.target = "_blank";
          license.rel = "noopener";
          license.textContent = "license";
          caption.appendChild(document.createTextNode(" · "));
          caption.appendChild(license);
        }
        figure.appendChild(caption);
        msgElement.appendChild(figure);
      }
      if (typeof data.portrait === "string" && data.portrait) {
        const photo = document.createElement("img");
        photo.className = "creator-photo";
        photo.src = data.portrait;
        photo.alt = "";
        photo.addEventListener("error", () => photo.remove());
        msgElement.prepend(photo);
        const projects = document.createElement("div");
        projects.className = "creator-projects";
        (data.projects || []).forEach((project) => {
          const link = document.createElement("a");
          link.className = "creator-project";
          link.href = project.url;
          link.target = "_blank";
          link.rel = "noopener";
          link.innerHTML = `<img src="${project.icon}" alt=""> <span><strong>${escapeHtml(project.name || "")}</strong> ${escapeHtml(project.note || "")}</span>`;
          projects.appendChild(link);
        });
        if (projects.childElementCount) msgElement.appendChild(projects);
        const asks = document.createElement("div");
        asks.className = "creator-asks";
        (data.followups || []).forEach((question) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "creator-ask";
          button.textContent = question;
          button.addEventListener("click", () => {
            msgInput.value = question;
            handleOutgoingMsg();
          });
          asks.appendChild(button);
        });
        if (asks.childElementCount) msgElement.appendChild(asks);
      }
      if (data.focus) {
        const saved = readThreads();
        const savedIndex = saved.findIndex((item) => item.id === conversationId);
        if (savedIndex >= 0) {
          saved[savedIndex].focus = data.focus;
          saveThreads(saved);
        }
      }
      finishMessage(incomingMsgDiv);
      addThreadMessage(conversationId, "assistant", data.response, data.dictionary, data.weather, data.commons, data.translation, data.sports, data.portrait);
      return;
    }
    throw new Error(data.error || "Backend returned no answer.");
  } catch (error) {
    console.error("e-Chat request failed:", error);
    msgElement.innerText = `The backend request failed: ${error.message}`;
    msgElement.classList.add("backend-error");
    msgElement.setAttribute("role", "alert");
    finishMessage(incomingMsgDiv);
    return;
  }
};
// Handle outgoing messages
const handleOutgoingMsg = (e) => {
  if (e) e.preventDefault();
  userData.message = msgInput.value.trim();
  if (!userData.message && !userData.file.data) return;
  const sentMessage = userData.message;
  const thread = ensureConversation(userData.message || "Image conversation");
  const conversationId = thread.id;
  addThreadMessage(conversationId, "user", userData.message || "Uploaded an image");

  // Display user's message
  let msgContent = `<div class="message-text">${escapeHtml(userData.message || "")}</div>`;
  if (userData.file.data) {
    msgContent += `<div class="uploaded-image"><img src="data:${userData.file.mime_type};base64,${userData.file.data}" alt="Uploaded Image"></div>`;
  }

  const outgoingMsgDiv = createMsgElement(msgContent, "user-message");
  eChatBody.insertBefore(outgoingMsgDiv, eChatBody.querySelector(".echat-footer"));
  eChatBody.scrollTo({ top: eChatBody.scrollHeight, behavior: "smooth" });

  // Always display thinking bot first
  const botContent = `
    <img class="bot-avatar" src="/static/images/artificial-intelligence.gif" alt="">
    <div class="message-text">
      <div class="thinking-indicator">
        <div class="dot"></div>
        <div class="dot"></div>
        <div class="dot"></div>
      </div>
    </div>`;
  const incomingMsgDiv = createMsgElement(botContent, "bot-message");
  eChatBody.insertBefore(incomingMsgDiv, eChatBody.querySelector(".echat-footer"));
  eChatBody.scrollTo({ top: eChatBody.scrollHeight, behavior: "smooth" });

  // Generate response after short delay
  setTimeout(() => {
    generateEchatResponse(incomingMsgDiv, conversationId, sentMessage);
  }, 500);

  msgInput.value = "";
  fileUploadWrapper.classList.remove("eFile-uploaded");
};
// --- Event Listeners ---
msgInput.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.isComposing) return;
  e.preventDefault();
  if (msgInput.value.trim()) handleOutgoingMsg(e);
});

sendMsgBtn.addEventListener("click", handleOutgoingMsg);
newConversationButton.addEventListener("click", startNewConversation);
memoryToggle.addEventListener("click", toggleMemory);
memorySearch.addEventListener("input", () => renderMemoryLinks(memorySearch.value));
document.querySelector("#e-file-upload").addEventListener("click", () => eFile.click());

eFile.addEventListener("change", () => {
  const file = eFile.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    fileUploadWrapper.querySelector("img").src = e.target.result;
    fileUploadWrapper.classList.add("eFile-uploaded");
    const base64String = e.target.result.split(",")[1];
    userData.file = { data: base64String, mime_type: file.type };
    eFile.value = "";
  };
  reader.readAsDataURL(file);
});

const rememberWeather = (place, text, card) => {
  const threads = readThreads();
  threads.forEach((thread) => {
    (thread.messages || []).forEach((message) => {
      if (message.weather && message.weather.query === place) {
        message.weather = card;
        message.content = text;
      }
    });
  });
  saveThreads(threads);
};

const refreshWeatherCards = async () => {
  const cards = [...eChatBody.querySelectorAll(".weather-card[data-place]")];
  await Promise.all(cards.map(async (card) => {
    const place = card.dataset.place;
    try {
      const response = await fetch(`/weather?place=${encodeURIComponent(place)}`);
      if (!response.ok) return;
      const data = await response.json();
      if (!data.weather) return;
      const bubble = card.closest(".message-text");
      const fresh = renderWeather(data.weather);
      card.replaceWith(fresh);
      const line = bubble && bubble.childNodes[0];
      if (line && line.nodeType === Node.TEXT_NODE) {
        const named = line.textContent.match(/^(\s*[^,]{1,80}, )/);
        line.textContent = `${named ? named[1] : ""}${data.response}`;
      }
      rememberWeather(place, line && line.textContent ? line.textContent : data.response, data.weather);
    } catch (_error) {
      /* keep the card already on screen */
    }
  }));
};

migrateOldMemory();
const savedConversation = localStorage.getItem(ACTIVE_KEY);
if (savedConversation && readThreads().some((thread) => thread.id === savedConversation)) {
  openConversation(savedConversation);
}
setInterval(refreshWeatherCards, 60000);
refreshWeatherCards();
startNewConversation();

const zoomLayer = document.createElement("div");
zoomLayer.className = "image-zoom";
zoomLayer.hidden = true;
zoomLayer.innerHTML = `
  <button type="button" class="image-zoom-close" aria-label="Close">×</button>
  <img class="image-zoom-blur" alt="">
  <img class="image-zoom-photo" alt="">
`;
document.documentElement.appendChild(zoomLayer);

const openImageZoom = (src, alt) => {
  if (!src) return;
  zoomLayer.querySelector(".image-zoom-blur").src = src;
  const photo = zoomLayer.querySelector(".image-zoom-photo");
  photo.src = src;
  photo.alt = alt || "Expanded image";
  zoomLayer.hidden = false;
};

const closeImageZoom = () => {
  zoomLayer.hidden = true;
};

document.addEventListener("click", (event) => {
  const host = event.target.closest(".creator-photo, .uploaded-image, .commons-photo");
  if (!host) return;
  const image = host.tagName === "IMG" ? host : host.querySelector("img");
  if (!image) return;
  event.preventDefault();
  openImageZoom(image.currentSrc || image.src, image.alt);
}, true);

zoomLayer.addEventListener("click", (event) => {
  if (event.target.classList.contains("image-zoom-photo")) return;
  closeImageZoom();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeImageZoom();
});

// Tooltip & Emoji Systems remain as defined in your previous version...
// (Skipped for brevity but should be kept in your actual deployment)
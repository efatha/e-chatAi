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
    clearChatPanel();
    setWelcomeVisible(true);
  }
  renderMemoryLinks(memorySearch.value);
};

const renderStoredMessage = (item) => {
  if (!item || !["user", "assistant"].includes(item.role)) return;
  const classes = item.role === "user" ? "user-message" : "bot-message";
  const avatar = item.role === "assistant"
    ? '<img class="bot-avatar" src="/static/images/artificial-intelligence.gif" alt="">'
    : "";
  const element = createMsgElement(
    `${avatar}<div class="message-text">${escapeHtml(String(item.content || "")).replace(/\n/g, "<br>")}</div>`,
    classes
  );
  eChatBody.insertBefore(element, eChatBody.querySelector(".echat-footer"));
};

const openConversation = (conversationId) => {
  const thread = readThreads().find((item) => item.id === conversationId);
  if (!thread) return;
  activeConversationId = thread.id;
  clearChatPanel();
  setWelcomeVisible(false);
  (thread.messages || []).forEach(renderStoredMessage);
  renderMemoryLinks(memorySearch.value);
  eChatBody.scrollTo({ top: eChatBody.scrollHeight });
};

const startNewConversation = () => {
  activeConversationId = null;
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
  setWelcomeVisible(false);
  renderMemoryLinks(memorySearch.value);
  return thread;
};

const addThreadMessage = (conversationId, role, content) => {
  const threads = readThreads();
  const index = threads.findIndex((thread) => thread.id === conversationId);
  if (index < 0) return;
  threads[index].messages = Array.isArray(threads[index].messages) ? threads[index].messages : [];
  threads[index].messages.push({ role, content, created_at: new Date().toISOString() });
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
      const hasMarks = /\*[^*\n]+\*/.test(data.response) || /_[^_\n]+_/.test(data.response) || /\bp\. \d+/.test(data.response);
      if (hasCode) {
        const blocks = [];
        msgElement.innerHTML = renderReply(data.response, blocks);
        msgElement.style.backgroundColor = "";
        msgElement.style.color = "";
        msgElement.style.padding = "";
        wireCopyButtons(msgElement, blocks);
      } else if (hasMarks) {
        msgElement.innerHTML = formatMarked(data.response);
        if (data.source === "independent") {
          msgElement.style.backgroundColor = "#397d92";
          msgElement.style.color = "#fff8f2";
        }
      } else {
        msgElement.innerText = data.response;
        if (data.source === "independent") {
          msgElement.style.backgroundColor = "#397d92";
          msgElement.style.color = "#fff8f2";
        }
      }
      finishMessage(incomingMsgDiv);
      addThreadMessage(conversationId, "assistant", data.response);
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

migrateOldMemory();
startNewConversation();

// Tooltip & Emoji Systems remain as defined in your previous version...
// (Skipped for brevity but should be kept in your actual deployment)
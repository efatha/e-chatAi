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

const userData = {
  message: null,
  file: { data: null, mime_type: null }
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
  .replace(/\*([^*\n]+)\*/g, "<strong>$1</strong>")
  .replace(/_([^_\n]+)_/g, "<em>$1</em>")
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
const generateEchatResponse = async (incomingMsgDiv) => {
  const msgElement = incomingMsgDiv.querySelector(".message-text");
  const payload = { message: userData.message || "" };
  if (userData.file.data) payload.file = userData.file;
  userData.file = { data: null, mime_type: null };

  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();

    if (response.ok && data.response) {
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
      return;
    }
  } catch (error) {
    console.error("e-Chat request failed:", error);
  }

  msgElement.style.color = "pink";
  msgElement.style.borderLeft = "4px solid pink";
  msgElement.innerText = "I'm currently in limited mode. Please check your connection or backend.";
  finishMessage(incomingMsgDiv);
};
// Handle outgoing messages
const handleOutgoingMsg = (e) => {
  if (e) e.preventDefault();
  userData.message = msgInput.value.trim();
  if (!userData.message && !userData.file.data) return;

  // Display user's message
  let msgContent = `<div class="message-text">${userData.message || ""}</div>`;
  if (userData.file.data) {
    msgContent += `<div class="uploaded-image"><img src="data:${userData.file.mime_type};base64,${userData.file.data}" alt="Uploaded Image"></div>`;
  }

  const outgoingMsgDiv = createMsgElement(msgContent, "user-message");
  eChatBody.appendChild(outgoingMsgDiv);
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
  eChatBody.appendChild(incomingMsgDiv);
  eChatBody.scrollTo({ top: eChatBody.scrollHeight, behavior: "smooth" });

  // Generate response after short delay
  setTimeout(() => {
    generateEchatResponse(incomingMsgDiv);
  }, 500);

  msgInput.value = "";
  fileUploadWrapper.classList.remove("eFile-uploaded");
};
// --- Event Listeners ---
msgInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && msgInput.value.trim()) handleOutgoingMsg(e);
});

sendMsgBtn.addEventListener("click", handleOutgoingMsg);
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

// Tooltip & Emoji Systems remain as defined in your previous version...
// (Skipped for brevity but should be kept in your actual deployment)
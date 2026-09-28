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

// Ask the server. It uses the independent agent, or the API when that API is active.
const generateEchatResponse = async (incomingMsgDiv) => {
  const msgElement = incomingMsgDiv.querySelector(".message-text");
  const msgLower = (userData.message || "").toLowerCase();
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
      msgElement.innerText = data.response;

      if (data.source === "independent") {
        msgElement.style.backgroundColor = "#397d92";
        msgElement.style.color = "#fff8f2";
      }

      if (["code", "js", "html", "css", "python", "api"].some(key => msgLower.includes(key))) {
        msgElement.style.backgroundColor = "#282c34";
        msgElement.style.color = "#f8f8f2";
        msgElement.style.fontFamily = "monospace";
        msgElement.style.padding = "10px";
        msgElement.style.borderRadius = "5px";
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
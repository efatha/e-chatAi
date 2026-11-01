const accessForm = document.getElementById("access-form");
const nameInput = document.getElementById("user_name");
const emailInput = document.getElementById("user_email");
const sendButton = document.getElementById("sendBtn");
const wrapper = document.querySelector(".wrapper .form");
const title = document.querySelector(".efatha-chat");
const message = document.getElementById("efa-chatMessage");
const autoText = document.querySelector(".new");

accessForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!accessForm.reportValidity()) return;

  const username = nameInput.value.trim();
  const email = emailInput.value.trim();
  sendButton.disabled = true;
  sendButton.textContent = "Sending…";

  try {
    const response = await fetch("/get-username", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, email })
    });
    if (!response.ok) {
      throw new Error(`Server returned ${response.status}`);
    }
    showConfirmation(username, email);
  } catch (error) {
    console.error("Could not save access details:", error);
    sendButton.disabled = false;
    sendButton.textContent = "Send";
    alert("Could not open e-Chat. Please check that the local server is running.");
  }
});

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);
}

function showConfirmation(username, email) {
  const safeName = escapeHtml(username);
  const safeEmail = escapeHtml(email);
  wrapper.style.display = "none";
  title.style.display = "none";
  message.innerHTML = `<h3 class="hello">Warm Welcome ${safeName}!</h3>
    <p class="thanks">thanks for signing</p>
    <button id="newPage" type="button">
      <a href="/e-Chat?name=${encodeURIComponent(username)}" class="herebtn">click here</a>
    </button>`;

  const confirmation = `${safeName}, confirm that this is your email : <br>${safeEmail} by clicking <br>the button in the border...`;
  let characterIndex = 1;
  function typeNext() {
    autoText.innerHTML = `<h2 id="autoText">Hello ${confirmation.slice(0, characterIndex)}</h2>`;
    characterIndex += 1;
    if (characterIndex <= confirmation.length) {
      setTimeout(typeNext, 80);
    }
  }
  typeNext();
}

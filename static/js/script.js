const accessForm = document.getElementById("access-form");
const nameInput = document.getElementById("user_name");
const emailInput = document.getElementById("user_email");
const sendButton = document.getElementById("sendBtn");

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
    window.location.assign(`/e-Chat?name=${encodeURIComponent(username)}`);
  } catch (error) {
    console.error("Could not save access details:", error);
    sendButton.disabled = false;
    sendButton.textContent = "Send";
    alert("Could not open e-Chat. Please check that the local server is running.");
  }
});
var wrapper = document.querySelector(".wrapper .form");
const escapeHtml = (value) => String(value)
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;");
Name = document.querySelector(".inpName");
Email = document.querySelector(".inpEmail");
btn = document.querySelector("button");
const containerElement = document.querySelector(".new"); // Message in the auto complete text


btn.addEventListener("click", () => {
  let userName = Name.value; // Store user name for later use
  let userEmail = Email.value; // Store user email for later use
    // test to get user name and email without any bug
  console.log(` user-name: ${userName} \n user-email: ${userEmail}`);
    // Adding the empty area on which will be displayed the value grabbed from the input
  wrapper.style.display = "none";
let eChat = document.querySelector(".efatha-chat");
  eChat.style.display = "none";
    // The head message in the area
const forUser = document.getElementById("efa-chatMessage");
  const safeName = escapeHtml(userName);
  const safeEmail = escapeHtml(userEmail);
  forUser.innerHTML = `<h3 class="hello">Warm Welcome ${safeName}!</h3>
  <p class="thanks">thanks for signing</p>
  <button id="newPage" type="button">
    <a href="/e-Chat?name=${encodeURIComponent(userName)}" class="herebtn">click here</a>
  </button>`
  // Auto text effect animation
let isSearchActive = false; // This variable Controls flag for auto text effect
let characterIndex = 1;
  const note = `${userName}, confirm that this is your email: ${userEmail} by clicking the button in the border...`;
  function updateText() {
      if (isSearchActive) return;
      const shown = escapeHtml(note.slice(0, characterIndex));
      containerElement.innerHTML = `<h2 id="autoText">Hello ${shown}</h2>`;
      if (characterIndex >= note.length) return;
      characterIndex++;
      setTimeout(updateText, 80);
  }
  // Start the animation
  updateText();
});
const sendBtn = document.getElementById("sendBtn");

sendBtn.addEventListener("click", async () => {
  const username = document.querySelector(".inpName").value;
  const email = document.querySelector(".inpEmail").value;

  if (!username) {
    alert("Please enter your name");
    return;
  }

  // Send to backend
  await fetch('/get-username', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email })
  });

  // 👉 Show loading text
  showLoadingScreen();

  // 👉 Wait before redirect (2 seconds)
  setTimeout(() => {
    window.location.href = "/e-Chat";
  }, 2000);
});
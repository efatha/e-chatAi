var wrapper = document.querySelector(".wrapper .form");
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
  forUser.innerHTML = `<h3 class="hello"> Warm Welcome ${userName}!</h3><br>
  <p class="thanks">thanks for signing</p>
  <button id="newPage">
    <a href="/e-Chat?name=${encodeURIComponent(userName)}" class="herebtn">
click here<a>
  </button>`
  // Auto text effect animation
let isSearchActive = false; // This variable Controls flag for auto text effect
let efaChatIndex = 1;
let characterIndex = 1;
  const efaChatUsers = ["0", `${userName}, confirm that this is <br>your email : <br>${userEmail} by clicking <br>the button in the border...`];
  function updateText() {
      if (!isSearchActive) {
          containerElement.innerHTML = `<h2 id="autoText">Hello ${efaChatUsers[efaChatIndex].slice(0, characterIndex)}</h2>`;
          characterIndex++;
          setTimeout(updateText, 80);
      }
  }
  // Start the animation
  updateText();
});

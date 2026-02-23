const queryString = window.location.search;
const urlParams = new URLSearchParams(queryString);
const userName = urlParams.get('name');
const toogleUserName = document.querySelector(".iconUser");
toogleUserName.textContent = `${userName}`;

// Dark-mode script
const inputTheme = document.querySelector(".input");
const body = document.querySelector("body");
const eChatB = document.querySelector(".chat-body");
const header2 = document.querySelector(".chat-header");
const themeChanger = document.querySelector("#themeChangerIcon");

inputTheme.checked = JSON.parse(localStorage.getItem("mode"));
updateBody();

function updateBody() {
    if (inputTheme.checked) {
        body.style.background = "var(--efa-background2)"; // Dark mode background color
        eChatB.style.background = "var(--efa-gray-800)";
        header2.style.background = "var(--efa-gray-900)";
        themeChanger.style.fill = "var(--efa-gray-400)";  
    } else {
        body.style.background = "var(--efa-background)"; // Light mode background color
        eChatB.style.background = "var(--efa-gray-200)";
        header2.style.background = "var(--efa-sea)";
        themeChanger.style.fill = "var(--efa-sea)";
    }
}

inputTheme.addEventListener("input", () => {
    updateBody();
    updateLocalStorage();
});

function updateLocalStorage() {
    localStorage.setItem("mode", JSON.stringify(inputTheme.checked)); // Fixed inputTheme reference
}
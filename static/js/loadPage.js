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
    const memory = document.querySelector(".memory-sidebar");
    if (inputTheme.checked) {
        body.style.background = "var(--efa-background2)"; // Dark mode background color
        eChatB.style.background = "var(--efa-gray-800)";
        header2.style.background = "var(--efa-gray-900)";
        themeChanger.style.fill = "var(--efa-gray-400)";
        if (memory) {
            memory.style.background = "var(--efa-gray-800)";
            memory.style.color = "var(--efa-gray-100)";
            memory.style.borderColor = "var(--efa-gray-700)";
            memory.style.setProperty("--memory-mark", "var(--efa-gray-400)");
            memory.style.setProperty("--memory-menu", "var(--efa-gray-900)");
            memory.style.setProperty("--memory-field", "var(--efa-gray-900)");
            memory.style.setProperty("--memory-accent", "var(--efa-gray-900)");
        }
    } else {
        body.style.background = "var(--efa-background)"; // Light mode background color
        eChatB.style.background = "var(--efa-gray-200)";
        header2.style.background = "var(--efa-sea)";
        themeChanger.style.fill = "var(--efa-sea)";
        if (memory) {
            memory.style.background = "var(--efa-gray-100)";
            memory.style.color = "var(--efa-gray-900)";
            memory.style.borderColor = "rgba(57, 125, 146, 0.18)";
            memory.style.setProperty("--memory-mark", "var(--efa-sea)");
            memory.style.setProperty("--memory-menu", "var(--efa-white)");
            memory.style.setProperty("--memory-field", "var(--efa-white)");
            memory.style.setProperty("--memory-accent", "var(--efa-sea)");
        }
    }
}

inputTheme.addEventListener("input", () => {
    updateBody();
    updateLocalStorage();
});

function updateLocalStorage() {
    localStorage.setItem("mode", JSON.stringify(inputTheme.checked)); // Fixed inputTheme reference
}
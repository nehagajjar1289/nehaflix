console.log("NehaFlix Loaded 🚀");

// Welcome popup
setTimeout(() => {
    alert("Welcome to NehaFlix 🎬🔥");
}, 1500);

// Scroll effect
window.onscroll = function() {
    console.log("Scrolling...");
};


console.log("NehaFlix Loaded 🚀");

// 🎬 Welcome Popup
setTimeout(() => {
    alert("Welcome to NehaFlix 🎬🔥 Enjoy Movies!");
}, 1500);

// 🎯 Click Effect (Track clicks)
document.addEventListener("click", function() {
    console.log("User clicked something 👆");
});

// 🎥 Image Hover Zoom Effect
document.querySelectorAll("img").forEach(img => {
    img.addEventListener("mouseover", () => {
        img.style.transform = "scale(1.1)";
    });
    img.addEventListener("mouseout", () => {
        img.style.transform = "scale(1)";
    });
});

// 🌓 Dark / Light Mode Toggle
function toggleMode() {
    document.body.classList.toggle("light-mode");
}

// 🔊 Sound Effect
function playSound() {
    let audio = new Audio("https://www.soundjay.com/button/beep-07.wav");
    audio.play();
}

// ⏱️ Page Load Message
window.onload = function() {
    console.log("App fully loaded ✅");
};

// 📜 Scroll Detection
window.onscroll = function() {
    console.log("Scrolling...");
};

// 🎬 Fake Loading Animation
function showLoader() {
    let loader = document.createElement("div");
    loader.innerHTML = "Loading Movies...";
    loader.style.position = "fixed";
    loader.style.top = "50%";
    loader.style.left = "50%";
    loader.style.transform = "translate(-50%, -50%)";
    loader.style.background = "black";
    loader.style.color = "white";
    loader.style.padding = "20px";
    loader.style.zIndex = "9999";

    document.body.appendChild(loader);

    setTimeout(() => {
        loader.remove();
    }, 2000);
}

// Run loader on start
showLoader();
(() => {
  setInterval(() => {
    const screen = document.getElementById("rick-hole-screen");
    if (screen) screen.src = "img/rick-hole-live.png?t=" + Date.now();
  }, 15000);
})();

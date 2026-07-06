(function () {
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".modernisation-token button");
    if (!button) return;
    var token = button.closest(".modernisation-token");
    if (!token) return;
    token.dataset.decision = button.dataset.action || "";
  });
})();

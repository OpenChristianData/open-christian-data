(function () {
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".structural-control button");
    if (!button) return;
    var control = button.closest(".structural-control");
    if (!control) return;
    control.dataset.reviewAction = button.dataset.action || "";
  });
})();

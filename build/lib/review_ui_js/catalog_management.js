(function () {
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".catalog-management button");
    if (!button) return;
    var row = button.closest(".catalog-rendering");
    if (!row) return;
    row.dataset.reviewAction = button.dataset.action || "";
  });
})();

(function () {
  document.addEventListener("click", function (event) {
    var reading = event.target.closest(".reading");
    if (!reading) return;
    var group = reading.closest(".disagreement");
    if (!group) return;
    group.querySelectorAll(".reading").forEach(function (item) {
      item.setAttribute("aria-pressed", item === reading ? "true" : "false");
    });
  });
})();

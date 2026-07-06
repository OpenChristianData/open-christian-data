(function () {
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".download-review-state");
    if (!button) return;
    var state = {
      generated_at: new Date().toISOString(),
      decisions: Array.from(document.querySelectorAll("[data-review-action], [data-decision]")).map(function (node) {
        return {
          id: node.id || node.dataset.renderingId || node.dataset.ruleId || "",
          action: node.dataset.reviewAction || node.dataset.decision || ""
        };
      })
    };
    var blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" });
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "review-decisions.json";
    link.click();
    URL.revokeObjectURL(link.href);
  });
})();

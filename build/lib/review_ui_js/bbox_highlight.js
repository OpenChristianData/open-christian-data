(function () {
  function selectTarget(target) {
    if (!target || !target.dataset || !target.dataset.bbox) return;
    var bbox;
    try {
      bbox = JSON.parse(target.dataset.bbox);
    } catch (error) {
      return;
    }
    var selector = '.scan-page[data-rendering-id="' + target.dataset.renderingId + '"][data-page-number="' + target.dataset.pageNumber + '"]';
    var page = document.querySelector(selector);
    if (!page) return;
    var overlay = page.querySelector(".bbox-overlay");
    if (!overlay) return;
    overlay.style.left = bbox.x + "px";
    overlay.style.top = bbox.y + "px";
    overlay.style.width = bbox.w + "px";
    overlay.style.height = bbox.h + "px";
    overlay.hidden = false;
    page.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  document.addEventListener("click", function (event) {
    var target = event.target.closest(".hocr-block");
    selectTarget(target);
  });
})();

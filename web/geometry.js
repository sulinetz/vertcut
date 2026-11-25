/* Геометрия split-screen. Чистая функция, зеркало render.split_geometry. */
(function (root) {
  function splitGeometry(width, height, ratio) {
    var w = Math.max(2, Math.round(Number(width) || 1080));
    var h = Math.max(2, Math.round(Number(height) || 1920));
    var r = Math.max(0.25, Math.min(0.85, Number(ratio) || 0.5));
    var top = Math.max(2, Math.floor(h * r / 2 + 0.5) * 2);
    top = Math.min(top, h - 2);
    return {
      width: w,
      height: h,
      ratio: r,
      top_h: top,
      bottom_h: h - top,
      top: { x: 0, y: 0, w: w, h: top },
      bottom: { x: 0, y: top, w: w, h: h - top }
    };
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { splitGeometry: splitGeometry };
  } else {
    root.VCGeometry = { splitGeometry: splitGeometry };
  }
})(typeof window !== "undefined" ? window : globalThis);

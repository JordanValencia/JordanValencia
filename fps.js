// Cheap FPS counter: the per-frame work is one increment and one subtraction.
// The DOM is touched only once per `interval` ms, not every frame.
export function fpsCounter({ interval = 500, parent = document.body } = {}) {
  const el = document.createElement('div');
  el.style.cssText =
    'position:fixed;top:4px;left:4px;padding:2px 6px;font:12px monospace;' +
    'color:#0f0;background:#0008;pointer-events:none;z-index:99999';
  parent.appendChild(el);

  let frames = 0;
  let last = performance.now();
  let id = requestAnimationFrame(tick);

  function tick(now) {
    frames++;
    const dt = now - last;
    if (dt >= interval) {
      el.textContent = Math.round((frames * 1000) / dt) + ' FPS';
      frames = 0;
      last = now;
    }
    id = requestAnimationFrame(tick);
  }

  return () => {
    cancelAnimationFrame(id);
    el.remove();
  };
}

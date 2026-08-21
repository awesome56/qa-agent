/**
 * highlight.js — injected via Playwright addInitScript
 * Pulses and outlines buttons to stress visual regression + makes recording obvious.
 * No deps, safe to inject on any page.
 */
(() => {
  const STYLE_ID = "__qa_highlight_style";
  if (document.getElementById(STYLE_ID)) return;

  const css = `
    @keyframes qa-pulse {
      0% { box-shadow: 0 0 0 0 rgba(255,0,85,0.7); }
      70% { box-shadow: 0 0 0 12px rgba(255,0,85,0); }
      100% { box-shadow: 0 0 0 0 rgba(255,0,85,0); }
    }
    .__qa-highlight {
      outline: 3px solid #ff0055 !important;
      outline-offset: 2px !important;
      animation: qa-pulse 1.2s infinite !important;
      position: relative;
      z-index: 9999;
    }
    .__qa-badge {
      position: absolute;
      top: -10px; right: -10px;
      background: #ff0055;
      color: white;
      font: 10px/1 monospace;
      padding: 2px 5px;
      border-radius: 4px;
      pointer-events: none;
    }
  `;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = css;
  document.documentElement.appendChild(style);

  function highlightButtons() {
    const sel = "button, a[role='button'], [data-testid*='button'], input[type='button'], input[type='submit'], .btn, [class*='Button']";
    document.querySelectorAll(sel).forEach((el, i) => {
      if (el.__qa_highlighted) return;
      el.__qa_highlighted = true;
      el.classList.add("__qa-highlight");
      // badge
      try {
        const b = document.createElement("span");
        b.className = "__qa-badge";
        b.textContent = `QA:${i+1}`;
        if (getComputedStyle(el).position === "static") el.style.position = "relative";
        el.appendChild(b);
      } catch {}
      // log for recorder
      if (window._qa_log) window._qa_log(`highlight button ${i+1}: ${el.innerText?.slice(0,30) || el.tagName}`);
    });
  }

  // run on load + observer for SPA
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", highlightButtons);
  } else {
    highlightButtons();
  }
  new MutationObserver(highlightButtons).observe(document.documentElement, { childList: true, subtree: true });
  setInterval(highlightButtons, 1500);
})();

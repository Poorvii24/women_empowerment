/**
 * copilot_widget.js
 * ==================
 * Self-contained AI Career Copilot floating widget. Include with a single
 * <script src="copilot_widget.js"></script> near the end of <body> on any
 * authenticated page — it injects its own styles and markup, so no other
 * changes to that page are required.
 *
 * Reuses the app's existing CSS design tokens (--primary, --surface, --text,
 * --border, --radius-*, --shadow-*, all defined in styles.css and already
 * theme-aware via [data-bs-theme]), so the widget automatically matches
 * light/dark mode without any extra styling of its own.
 *
 * Talks to: POST /copilot/ask, GET /copilot/history, POST /copilot/clear
 * (see app.py's "AI Career Copilot" routes / services/ai_copilot.py).
 */
(function () {
    "use strict";

    const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

    const I18N = window.COPILOT_I18N || {};
    const SUGGESTED_QUESTIONS = I18N.suggestedQuestions || [
        "How ready am I for my next opportunity?",
        "What skills could I learn next?",
        "What should I try building next?",
        "Am I ready for the role I want?",
    ];

    // ── Inject highlight.js (for fenced code-block syntax highlighting) ────
    function loadHighlightJs(cb) {
        if (window.hljs) return cb();
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css";
        document.head.appendChild(link);
        const script = document.createElement("script");
        script.src = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js";
        script.onload = cb;
        script.onerror = cb; // degrade gracefully — code blocks just render unhighlighted
        document.head.appendChild(script);
    }

    // ── Styles ───────────────────────────────────────────────────────────
    const style = document.createElement("style");
    style.textContent = `
    .isis-copilot-fab {
      position: fixed; bottom: 24px; right: 24px; z-index: 2147483000;
      width: 58px; height: 58px; border-radius: 50%;
      background: linear-gradient(135deg, var(--primary), var(--secondary));
      color: #fff; border: none; box-shadow: var(--shadow-lg);
      display: flex; align-items: center; justify-content: center;
      cursor: pointer; font-size: 26px; transition: transform var(--transition);
    }
    .isis-copilot-fab:hover { transform: scale(1.08); }
    .isis-copilot-fab .badge-dot {
      position: absolute; top: 4px; right: 4px; width: 10px; height: 10px;
      border-radius: 50%; background: var(--success); border: 2px solid var(--surface);
    }
    .isis-copilot-panel {
      position: fixed; bottom: 96px; right: 24px; z-index: 2147483000;
      width: 400px; max-width: calc(100vw - 32px); height: 600px; max-height: calc(100vh - 140px);
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg);
      box-shadow: var(--shadow-hover); display: none; flex-direction: column; overflow: hidden;
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
    }
    .isis-copilot-panel.open { display: flex; }
    .isis-copilot-header {
      background: linear-gradient(135deg, var(--primary), var(--secondary)); color: #fff;
      padding: 14px 16px; display: flex; align-items: center; justify-content: space-between;
      flex-shrink: 0;
    }
    .isis-copilot-header .title { font-weight: 700; font-size: 15px; display: flex; align-items: center; gap: 8px; }
    .isis-copilot-header .actions { display: flex; gap: 6px; }
    .isis-copilot-header button {
      background: rgba(255,255,255,0.15); border: none; color: #fff; border-radius: 8px;
      width: 30px; height: 30px; cursor: pointer; display: flex; align-items: center; justify-content: center;
      transition: background var(--transition);
    }
    .isis-copilot-header button:hover { background: rgba(255,255,255,0.28); }
    .isis-copilot-body {
      flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px;
      background: var(--bg);
    }
    .isis-copilot-suggested { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
    .isis-copilot-suggested-title { font-size: 12.5px; color: var(--text-muted); font-weight: 600; margin-bottom: 2px; }
    .isis-copilot-chip {
      background: var(--primary-light); color: var(--primary); border: 1px solid var(--border);
      border-radius: 999px; padding: 7px 12px; font-size: 12.5px; cursor: pointer; text-align: left;
      transition: background var(--transition);
    }
    .isis-copilot-chip:hover { background: var(--border); }
    .isis-copilot-msg { max-width: 88%; padding: 10px 13px; border-radius: 14px; font-size: 13.5px; line-height: 1.5; }
    .isis-copilot-msg.user {
      align-self: flex-end; background: var(--primary); color: #fff; border-bottom-right-radius: 4px;
    }
    .isis-copilot-msg.assistant {
      align-self: flex-start; background: var(--surface); color: var(--text); border: 1px solid var(--border);
      border-bottom-left-radius: 4px; box-shadow: var(--shadow-xs);
    }
    .isis-copilot-msg.assistant pre {
      background: #0d1117; color: #e6edf3; padding: 10px; border-radius: 8px; overflow-x: auto; font-size: 12px;
    }
    .isis-copilot-msg.assistant code:not(pre code) {
      background: var(--bg-alt); padding: 1px 5px; border-radius: 4px; font-size: 12px;
    }
    .isis-copilot-insight {
      margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border);
      font-size: 12px; color: var(--text-muted); display: flex; flex-direction: column; gap: 3px;
    }
    .isis-copilot-insight b { color: var(--text-secondary); }
    .isis-copilot-followups { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .isis-copilot-copy {
      background: none; border: none; color: var(--text-faint); cursor: pointer; font-size: 11px;
      padding: 2px 0; margin-top: 6px; display: flex; align-items: center; gap: 4px;
    }
    .isis-copilot-copy:hover { color: var(--text-muted); }
    .isis-copilot-typing { align-self: flex-start; display: flex; gap: 4px; padding: 10px 13px; }
    .isis-copilot-typing span {
      width: 6px; height: 6px; border-radius: 50%; background: var(--text-faint);
      animation: isis-copilot-bounce 1.2s infinite ease-in-out;
    }
    .isis-copilot-typing span:nth-child(2) { animation-delay: 0.15s; }
    .isis-copilot-typing span:nth-child(3) { animation-delay: 0.3s; }
    @keyframes isis-copilot-bounce { 0%, 60%, 100% { transform: translateY(0); opacity: 0.5; } 30% { transform: translateY(-4px); opacity: 1; } }
    .isis-copilot-footer {
      padding: 12px; border-top: 1px solid var(--border); display: flex; gap: 8px; flex-shrink: 0; background: var(--surface);
    }
    .isis-copilot-footer textarea {
      flex: 1; resize: none; border: 1px solid var(--border); border-radius: 10px; padding: 9px 12px;
      font-size: 13.5px; font-family: inherit; background: var(--bg); color: var(--text); max-height: 80px;
    }
    .isis-copilot-footer textarea:focus { outline: none; border-color: var(--primary); }
    .isis-copilot-send {
      background: var(--primary); color: #fff; border: none; border-radius: 10px; width: 40px; flex-shrink: 0;
      cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background var(--transition);
    }
    .isis-copilot-send:hover { background: var(--primary-hover); }
    .isis-copilot-send:disabled { opacity: 0.5; cursor: not-allowed; }
    @media (max-width: 480px) {
      .isis-copilot-panel { right: 16px; left: 16px; width: auto; bottom: 88px; height: calc(100vh - 160px); }
      .isis-copilot-fab { right: 16px; bottom: 16px; }
    }
  `;
    document.head.appendChild(style);

    // ── Markup ───────────────────────────────────────────────────────────
    const fab = document.createElement("button");
    fab.className = "isis-copilot-fab";
    fab.setAttribute("aria-label", I18N.openCareerGuide || "Open Your Career Guide");
    fab.innerHTML = '<i class="bi bi-stars"></i><span class="badge-dot"></span>';

    const panel = document.createElement("div");
    panel.className = "isis-copilot-panel";
    panel.innerHTML = `
    <div class="isis-copilot-header">
      <div class="title"><i class="bi bi-stars"></i> ${I18N.careerGuideTitle || "Your Career Guide"}</div>
      <div class="actions">
        <button class="isis-copilot-clear" title="${I18N.clearConversation || "Clear conversation"}"><i class="bi bi-trash3"></i></button>
        <button class="isis-copilot-close" title="${I18N.close || "Close"}"><i class="bi bi-x-lg"></i></button>
      </div>
    </div>
    <div class="isis-copilot-body"></div>
    <div class="isis-copilot-footer">
      <textarea rows="1" placeholder="${I18N.inputPlaceholder || "Ask me anything — how ready you are, what to learn next, what to try..."}"></textarea>
      <button class="isis-copilot-send" aria-label="${I18N.send || "Send"}"><i class="bi bi-send-fill"></i></button>
    </div>
  `;

    document.body.appendChild(fab);
    document.body.appendChild(panel);

    const bodyEl = panel.querySelector(".isis-copilot-body");
    const textarea = panel.querySelector("textarea");
    const sendBtn = panel.querySelector(".isis-copilot-send");
    const closeBtn = panel.querySelector(".isis-copilot-close");
    const clearBtn = panel.querySelector(".isis-copilot-clear");

    let historyLoaded = false;

    // ── Lightweight markdown (bold, inline code, fenced code, bullets) ──────
    function escapeHtml(s) {
        return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function renderMarkdown(text) {
        let html = escapeHtml(text || "");
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) =>
            `<pre><code class="language-${lang || "plaintext"}">${code.trim()}</code></pre>`);
        html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
        html = html.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
        html = html.replace(/^- (.+)$/gm, "&bull; $1<br>");
        html = html.replace(/\n/g, "<br>");
        return html;
    }

    function scrollToBottom() {
        bodyEl.scrollTop = bodyEl.scrollHeight;
    }

    function renderSuggested() {
        const wrap = document.createElement("div");
        wrap.className = "isis-copilot-suggested";
        wrap.innerHTML = '<div class="isis-copilot-suggested-title">Try asking:</div>';
        SUGGESTED_QUESTIONS.forEach((q) => {
            const chip = document.createElement("button");
            chip.className = "isis-copilot-chip";
            chip.textContent = q;
            chip.onclick = () => sendMessage(q);
            wrap.appendChild(chip);
        });
        bodyEl.appendChild(wrap);
    }

    function addUserMessage(text) {
        const el = document.createElement("div");
        el.className = "isis-copilot-msg user";
        el.textContent = text;
        bodyEl.appendChild(el);
        scrollToBottom();
    }

    function addAssistantMessage(result) {
        const el = document.createElement("div");
        el.className = "isis-copilot-msg assistant";
        el.innerHTML = renderMarkdown(result.answer || "");

        const hasInsight = result.confidence || result.next_action || result.expected_impact || result.estimated_effort
            || (result.evidence && result.evidence.length);
        if (hasInsight) {
            const insight = document.createElement("div");
            insight.className = "isis-copilot-insight";
            if (result.evidence && result.evidence.length)
                insight.innerHTML += `<div><b>Based on:</b> ${escapeHtml(result.evidence.join(" \u2022 "))}</div>`;
            if (result.confidence) insight.innerHTML += `<div><b>How sure we are:</b> ${escapeHtml(result.confidence)}</div>`;
            if (result.next_action) insight.innerHTML += `<div><b>Try this next:</b> ${escapeHtml(result.next_action)}</div>`;
            if (result.expected_impact) insight.innerHTML += `<div><b>Why it helps:</b> ${escapeHtml(result.expected_impact)}</div>`;
            if (result.estimated_effort) insight.innerHTML += `<div><b>Time needed:</b> ${escapeHtml(result.estimated_effort)}</div>`;
            el.appendChild(insight);
        }

        if (result.follow_up_questions && result.follow_up_questions.length) {
            const fu = document.createElement("div");
            fu.className = "isis-copilot-followups";
            result.follow_up_questions.forEach((q) => {
                const chip = document.createElement("button");
                chip.className = "isis-copilot-chip";
                chip.textContent = q;
                chip.onclick = () => sendMessage(q);
                fu.appendChild(chip);
            });
            el.appendChild(fu);
        }

        const copyBtn = document.createElement("button");
        copyBtn.className = "isis-copilot-copy";
        copyBtn.innerHTML = '<i class="bi bi-clipboard"></i> Copy';
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(result.answer || "");
            copyBtn.innerHTML = '<i class="bi bi-check2"></i> Copied';
            setTimeout(() => (copyBtn.innerHTML = '<i class="bi bi-clipboard"></i> Copy'), 1500);
        };
        el.appendChild(copyBtn);

        bodyEl.appendChild(el);
        if (window.hljs) el.querySelectorAll("pre code").forEach((b) => window.hljs.highlightElement(b));
        scrollToBottom();
    }

    function showTyping() {
        const el = document.createElement("div");
        el.className = "isis-copilot-typing";
        el.innerHTML = "<span></span><span></span><span></span>";
        el.dataset.typing = "1";
        bodyEl.appendChild(el);
        scrollToBottom();
        return el;
    }

    async function sendMessage(text) {
        text = (text || "").trim();
        if (!text) return;
        textarea.value = "";
        sendBtn.disabled = true;
        addUserMessage(text);
        const typingEl = showTyping();

        try {
            const resp = await fetch("/copilot/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF_TOKEN },
                body: JSON.stringify({ message: text }),
            });
            const data = await resp.json();
            typingEl.remove();
            if (data.status === "ok") {
                addAssistantMessage(data);
            } else {
                addAssistantMessage({ answer: data.message || I18N.genericError || "Something went wrong. Please try again." });
            }
        } catch (err) {
            typingEl.remove();
            addAssistantMessage({ answer: I18N.networkError || "Network error — please check your connection and try again." });
        } finally {
            sendBtn.disabled = false;
        }
    }

    async function loadHistory() {
        if (historyLoaded) return;
        historyLoaded = true;
        try {
            const resp = await fetch("/copilot/history");
            const data = await resp.json();
            if (data.status === "ok" && data.history && data.history.length) {
                data.history.forEach((m) => {
                    if (m.role === "user") addUserMessage(m.content);
                    else addAssistantMessage({ answer: m.content });
                });
            } else {
                renderSuggested();
            }
        } catch (err) {
            renderSuggested();
        }
    }

    fab.addEventListener("click", () => {
        panel.classList.toggle("open");
        if (panel.classList.contains("open")) {
            loadHighlightJs(() => {});
            loadHistory();
            textarea.focus();
        }
    });
    closeBtn.addEventListener("click", () => panel.classList.remove("open"));
    clearBtn.addEventListener("click", async () => {
        if (!confirm(I18N.confirmClear || "Clear this conversation? This can't be undone.")) return;
        try {
            await fetch("/copilot/clear", { method: "POST", headers: { "X-CSRFToken": CSRF_TOKEN } });
        } catch (err) { /* best-effort */ }
        bodyEl.innerHTML = "";
        renderSuggested();
    });
    sendBtn.addEventListener("click", () => sendMessage(textarea.value));
    textarea.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage(textarea.value);
        }
    });
})();

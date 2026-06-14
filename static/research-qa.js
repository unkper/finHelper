(function () {
  const cfg = window.FINANCIAL_REPORT_PAGE || {};
  const sessionMessages = [];

  function $(id) {
    return document.getElementById(id);
  }

  function setStatus(text, isError) {
    const el = $("qaStatus");
    if (!el) return;
    if (!text) {
      el.hidden = true;
      el.textContent = "";
      el.classList.remove("is-error");
      return;
    }
    el.hidden = false;
    el.textContent = text;
    el.classList.toggle("is-error", !!isError);
  }

  function setLoading(loading) {
    const askBtn = $("qaAskBtn");
    const presets = document.querySelectorAll(".research-qa-preset");
    if (askBtn) askBtn.disabled = loading || cfg.parseStatus === "extracting_text" || cfg.parseStatus === "ai_analyzing";
    presets.forEach((btn) => {
      btn.disabled = loading;
    });
    if (loading) {
      setStatus("AI 正在思考…", false);
    } else {
      setStatus("", false);
    }
  }

  function appendTurn(question, answer) {
    const list = $("qaSessionList");
    if (!list) return;

    const turn = document.createElement("div");
    turn.className = "research-qa-turn";

    const userBubble = document.createElement("div");
    userBubble.className = "research-qa-bubble research-qa-bubble--user";
    userBubble.innerHTML = `<span class="research-qa-bubble-label">你的问题</span>${escapeHtml(question)}`;

    const assistantBubble = document.createElement("div");
    assistantBubble.className = "research-qa-bubble research-qa-bubble--assistant";
    assistantBubble.innerHTML = `<span class="research-qa-bubble-label">AI 回答</span>${escapeHtml(answer)}`;

    turn.appendChild(userBubble);
    turn.appendChild(assistantBubble);
    list.appendChild(turn);
    turn.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function askQuestion(question, presetId) {
    if (!cfg.askUrl || !cfg.aiConfigured) {
      setStatus("未配置 AI 服务", true);
      return;
    }
    const trimmed = String(question || "").trim();
    if (!trimmed && !presetId) {
      setStatus("请输入问题或选择预设", true);
      return;
    }

    setLoading(true);
    try {
      const body = {
        question: trimmed,
        session_messages: sessionMessages,
      };
      if (presetId) body.preset_id = presetId;

      const res = await fetch(cfg.askUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload.error || "提问失败");

      const answer = payload.answer || "";
      const displayQuestion = trimmed || (cfg.qaPresets || []).find((p) => p.id === presetId)?.question || trimmed;
      sessionMessages.push({ role: "user", content: displayQuestion });
      sessionMessages.push({ role: "assistant", content: answer });
      appendTurn(displayQuestion, answer);
      const input = $("qaQuestionInput");
      if (input) input.value = "";
      setStatus("", false);
    } catch (error) {
      setStatus(error.message || "提问失败", true);
    } finally {
      setLoading(false);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!$("researchQaPanel")) return;

    $("qaAskBtn")?.addEventListener("click", () => {
      askQuestion($("qaQuestionInput")?.value || "", null);
    });

    document.querySelectorAll(".research-qa-preset").forEach((btn) => {
      btn.addEventListener("click", () => {
        const presetId = btn.dataset.presetId;
        const preset = (cfg.qaPresets || []).find((p) => p.id === presetId);
        if (preset && $("qaQuestionInput")) {
          $("qaQuestionInput").value = preset.question;
        }
        askQuestion(preset?.question || "", presetId);
      });
    });

    $("qaQuestionInput")?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        askQuestion($("qaQuestionInput")?.value || "", null);
      }
    });
  });
})();

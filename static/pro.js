"use strict";

/* Pro mode: streamed replies. The answer text appears as it is written, labelled as an
   unverified draft; the verified reply then replaces it. Standard mode never calls this. */

const PRO_I18N = {
  en: { draftLabel: "Draft, not verified yet", rewriting: "Rewriting after a failed check…" },
  ar: { draftLabel: "مسودة، لم يتم التحقق منها بعد", rewriting: "إعادة الكتابة بعد فشل أحد الفحوصات…" },
};

function guessLanguage(text) {
  const arabic = (text.match(/[؀-ۿ]/g) || []).length;
  const latin = (text.match(/[A-Za-z]/g) || []).length;
  if (!arabic && !latin) return uiLang;
  return arabic / (arabic + latin) >= 0.3 ? "ar" : "en";
}

/** Typing dots until the first words arrive, then the streaming draft. */
function createLiveCard(lang) {
  const p = PRO_I18N[lang];
  const dots = el("div", { className: "typing", role: "status" },
    el("span", { className: "dots", "aria-hidden": "true" }, el("i"), el("i"), el("i")), el("span", {}, I18N[lang].typing));
  const draftNote = el("p", { className: "draft-note" }, p.draftLabel);
  const draftText = el("div", { className: "draft-text answer", dir: "auto" });
  const draft = el("div", { className: "draft", hidden: true }, draftNote, draftText);
  const card = el("div", { className: "card live", dir: lang === "ar" ? "rtl" : "ltr", lang }, dots, draft);
  const node = el("li", { className: "msg msg-bot" }, el("div", { className: "avatar", "aria-hidden": "true" }, "م"), card);
  els.messages.append(node);
  scrollToBottom();
  let attempt = 1, raw = "";

  return {
    draft(e) {
      if (e.attempt !== attempt) { attempt = e.attempt; raw = ""; draftNote.textContent = p.rewriting; }
      dots.remove();
      draft.hidden = false;
      raw += e.delta;
      draftText.innerHTML = renderMarkdown(raw, 0);  // escaped first; [n] markers stay plain text in a draft
      if (window.scrollY + innerHeight > document.body.scrollHeight - 200) window.scrollTo({ top: document.body.scrollHeight });
    },
    remove() { node.remove(); },
  };
}

/** POST to the streaming endpoint and feed draft events to the live card; resolves with the final reply. */
async function streamReply(question, live) {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: question, session_id: sessionId }),
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const data = frame.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("");
      if (!data) continue;
      const event = JSON.parse(data);
      if (event.type === "draft") live.draft(event);
      else if (event.type === "result") return event.reply;
      else if (event.type === "error") throw new Error("stream error");
    }
  }
  throw new Error("stream ended without a result");
}

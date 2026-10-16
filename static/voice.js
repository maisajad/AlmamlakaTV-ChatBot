"use strict";

/* Pro mode voice, with the browser's own speech APIs: dictate a question, and listen to answers.
   Each control only appears where the browser supports it (Chrome and Edge best; Safari's
   speech recognition and Arabic voices vary). */

const VOICE_I18N = {
  en: { speak: "Ask by voice", stop: "Stop listening", listen: "Listen", stopListen: "Stop", heard: "Listening…" },
  ar: { speak: "اسأل بصوتك", stop: "إيقاف الاستماع", listen: "استمع", stopListen: "إيقاف", heard: "جارٍ الاستماع…" },
};
const RECOGNITION_LANG = { en: "en-US", ar: "ar-JO" };  // Jordanian Arabic for dictation

const Voice = (() => {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;
  let recognizer = null;
  let micButton = null;

  // ---------- dictation ----------

  function setupMic() {
    if (!Recognition) return;
    micButton = el("button", { type: "button", className: "mic pro-only", "aria-pressed": "false" });
    micButton.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/></svg>';
    els.send.before(micButton);
    micButton.addEventListener("click", () => (recognizer ? recognizer.stop() : listen()));
    relabel();
  }

  function relabel() {
    if (!micButton) return;
    const t = VOICE_I18N[uiLang];
    micButton.setAttribute("aria-label", recognizer ? t.stop : t.speak);
    micButton.title = recognizer ? t.stop : t.speak;
  }

  function listen() {
    if (busy) return;
    const r = new Recognition();
    r.lang = RECOGNITION_LANG[uiLang];
    r.interimResults = true;
    r.continuous = false;
    let finalText = "";
    const before = els.input.value;
    r.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
        else interim += e.results[i][0].transcript;
      }
      els.input.value = (before ? before + " " : "") + finalText + interim;
      autosize();
    };
    r.onend = () => {
      recognizer = null;
      micButton.classList.remove("is-listening");
      micButton.setAttribute("aria-pressed", "false");
      els.input.placeholder = I18N[uiLang].placeholder;
      relabel();
      if (finalText.trim()) ask(els.input.value);
    };
    r.onerror = () => {};  // onend follows; nothing heard means nothing sent
    recognizer = r;
    micButton.classList.add("is-listening");
    micButton.setAttribute("aria-pressed", "true");
    els.input.placeholder = VOICE_I18N[uiLang].heard;
    relabel();
    r.start();
  }

  // ---------- read aloud ----------

  function voiceFor(lang) {
    const voices = synth ? synth.getVoices() : [];
    return voices.find((v) => v.lang === (lang === "ar" ? "ar-JO" : "en-US"))
      || voices.find((v) => v.lang.toLowerCase().startsWith(lang));
  }

  function plainText(markdown) {
    return markdown.replace(/\[\d+\]/g, "").replace(/[*_`#>|]/g, "").replace(/^\s*[-•]\s+/gm, "").replace(/\s+/g, " ").trim();
  }

  /** Adds a "Listen" button to an answer card, if this device can speak its language. */
  function decorate(card, reply, lang) {
    if (!synth || !reply.answer || reply.status === "error") return;
    const t = VOICE_I18N[lang];
    const button = el("button", { type: "button", className: "listen pro-only" }, t.listen);
    button.hidden = !voiceFor(lang);  // voices can load late; re-checked below
    let speaking = false;
    button.addEventListener("click", () => {
      synth.cancel();
      if (speaking) return;
      const u = new SpeechSynthesisUtterance(plainText(reply.answer));
      u.voice = voiceFor(lang) || null;
      u.lang = lang === "ar" ? "ar-JO" : "en-US";
      u.onend = u.onerror = () => { speaking = false; button.textContent = t.listen; button.classList.remove("is-speaking"); };
      speaking = true;
      button.textContent = t.stopListen;
      button.classList.add("is-speaking");
      synth.speak(u);
    });
    card.append(button);
  }

  if (synth) {
    synth.addEventListener?.("voiceschanged", () => {
      document.querySelectorAll(".listen").forEach((b) => { b.hidden = !voiceFor(b.closest(".card").lang); });
    });
  }
  setupMic();
  return { decorate, relabel };
})();

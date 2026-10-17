"use strict";

/* Access code for normal users. Only active when the server has ACCESS_TOKENS set: then the
   chat, the source PDFs and the test report need the code, sent as a Bearer token. The code is
   remembered on this device until it stops working. */

const Auth = (() => {
  const KEY = "accessCode";
  const TEXT = {
    en: { title: "Enter your access code", text: "This assistant is private. Enter the access code you were given.",
          label: "Access code", button: "Continue", wrong: "That code isn't valid. Check it and try again." },
    ar: { title: "أدخل رمز الدخول", text: "هذا المساعد خاص. أدخل رمز الدخول الذي حصلت عليه.",
          label: "رمز الدخول", button: "متابعة", wrong: "هذا الرمز غير صحيح. تحقق منه وحاول مجددًا." },
  };
  let code = "";
  try { code = localStorage.getItem(KEY) || ""; } catch { /* storage unavailable */ }
  let gate = null;
  let waiting = [];

  const headers = () => (code ? { Authorization: `Bearer ${code}` } : {});

  async function check() {
    const res = await fetch("/api/auth", { headers: headers(), cache: "no-store" });
    return res.ok ? res.json() : { required: false, ok: true };
  }

  function remember(value) {
    code = value;
    try { value ? localStorage.setItem(KEY, value) : localStorage.removeItem(KEY); } catch { /* storage unavailable */ }
  }

  /** Show the code screen; resolves once a valid code has been entered. */
  function prompt() {
    return new Promise((resolve) => {
      waiting.push(resolve);
      if (gate) return;
      const lang = document.documentElement.lang === "ar" ? "ar" : "en";
      const t = TEXT[lang];
      gate = document.createElement("div");
      gate.className = "auth-gate";
      gate.setAttribute("role", "dialog");
      gate.setAttribute("aria-modal", "true");
      gate.setAttribute("aria-labelledby", "auth-title");
      gate.dir = lang === "ar" ? "rtl" : "ltr";
      gate.innerHTML = `
        <form class="auth-card">
          <img src="/static/logo.png" alt="قناة المملكة" width="119" height="35">
          <h2 id="auth-title"></h2>
          <p class="auth-text"></p>
          <label class="visually-hidden" for="auth-code"></label>
          <input id="auth-code" type="password" autocomplete="current-password" required>
          <p class="auth-error" hidden></p>
          <button class="btn-primary" type="submit"></button>
        </form>`;
      gate.querySelector("h2").textContent = t.title;
      gate.querySelector(".auth-text").textContent = t.text;
      gate.querySelector("label").textContent = t.label;
      gate.querySelector("input").placeholder = t.label;
      gate.querySelector("button").textContent = t.button;
      gate.querySelector("form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const button = gate.querySelector("button");
        button.disabled = true;
        remember(gate.querySelector("input").value.trim());
        const status = await check().catch(() => ({ ok: false }));
        button.disabled = false;
        if (!status.ok) {
          remember("");
          const err = gate.querySelector(".auth-error");
          err.textContent = t.wrong;
          err.hidden = false;
          gate.querySelector("input").select();
          return;
        }
        gate.remove();
        gate = null;
        waiting.splice(0).forEach((done) => done());
      });
      document.body.append(gate);
      gate.querySelector("input").focus();
    });
  }

  /** On page load: ask for a code only if the server requires one and we don't have a valid one. */
  async function ensure() {
    const status = await check().catch(() => ({ required: false, ok: true }));
    if (status.required && !status.ok) {
      remember("");
      await prompt();
    }
  }

  /** fetch() with the access code; a 401 asks for the code again and retries once. */
  async function authFetch(url, options = {}) {
    let res = await fetch(url, { ...options, headers: { ...(options.headers || {}), ...headers() } });
    if (res.status === 401) {
      remember("");
      await prompt();
      res = await fetch(url, { ...options, headers: { ...(options.headers || {}), ...headers() } });
    }
    return res;
  }

  return { headers, ensure, fetch: authFetch };
})();

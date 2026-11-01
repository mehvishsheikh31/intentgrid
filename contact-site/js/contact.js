// Contact form: validation and UI states (step 3.2).
// Sends to the API (step 3.3). Needs js/config.js. Rules below match backend/app/schemas.py.
(function () {
  "use strict";

  const form = document.getElementById("contact-form");
  if (!form) return;

  const successBox = document.getElementById("form-success");
  const errorBox = document.getElementById("form-error");
  const errorText = document.getElementById("form-error-text");
  const submitBtn = document.getElementById("submit-btn");
  const spinner = document.getElementById("submit-spinner");
  const submitText = document.getElementById("submit-text");
  const messageField = document.getElementById("message");
  const counter = document.getElementById("message-count");

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  const PHONE_RE = /^[0-9+() -]{6,30}$/;
  const CATEGORIES = ["complaint", "refund_request", "order_status", "product_inquiry",
                      "pricing_quote", "appointment_booking", "feedback", "other"];

  // Each rule returns an error text, or "" when the value is fine.
  const RULES = {
    name: (v) => (!v ? "Please enter your name." : v.length > 120 ? "Name is too long (max 120)." : ""),
    email: (v) => (!v ? "Please enter your email." : !EMAIL_RE.test(v) ? "Enter a valid email, like name@example.com." : ""),
    phone: (v) => (!v ? "" : !PHONE_RE.test(v) ? "Use 6 to 30 digits. You may use + ( ) - and spaces." : ""),
    category: (v) => (!CATEGORIES.includes(v) ? "Please choose an inquiry type." : ""),
    subject: (v) => (!v ? "Please enter a subject." : v.length > 200 ? "Subject is too long (max 200)." : ""),
    message: (v) => (v.length < 5 ? "Please write at least 5 characters." : v.length > 2000 ? "Message is too long (max 2000)." : ""),
  };

  function setFieldError(field, text) {
    const input = document.getElementById(field);
    const box = document.getElementById(field + "-error");
    input.classList.toggle("is-invalid", Boolean(text));
    input.classList.toggle("is-valid", !text && input.value.trim() !== "");
    input.setAttribute("aria-invalid", text ? "true" : "false");
    box.textContent = text;
  }

  function validateField(field) {
    const value = document.getElementById(field).value.trim();
    const text = RULES[field](value);
    setFieldError(field, text);
    return text === "";
  }

  function validateAll() {
    let firstBad = null;
    Object.keys(RULES).forEach((field) => {
      if (!validateField(field) && !firstBad) firstBad = field;
    });
    return firstBad; // null means everything is valid
  }

  function getData() {
    const data = {};
    new FormData(form).forEach((value, key) => { data[key] = String(value).trim(); });
    if (!data.phone) delete data.phone; // optional field: omit when empty
    return data;
  }

  function setBusy(busy) {
    submitBtn.disabled = busy;
    spinner.classList.toggle("d-none", !busy);
    submitText.textContent = busy ? "Sending..." : "Send message";
  }

  function showError(text) {
    errorText.textContent = text;
    errorBox.classList.remove("d-none");
    errorBox.focus();
  }

  const TIMEOUT_MS = 60000; // Render free tier can need about 1 minute to wake up
  const WAKING_AFTER_MS = 4000;

  // POST the form to the backend. Throws an Error with a friendly message on failure.
  async function sendToApi(data) {
    const controller = new AbortController();
    const killTimer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    const wakeTimer = setTimeout(() => {
      submitText.textContent = "Server waking up, please wait...";
    }, WAKING_AFTER_MS);

    try {
      const res = await fetch(API_BASE_URL + "/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
        signal: controller.signal,
      });
      if (res.ok) return;
      if (res.status === 429) throw new Error("Too many messages. Please wait a minute and try again.");
      if (res.status === 422) throw new Error("Some details look invalid. Please check the form and try again.");
      throw new Error("The server had a problem. Please try again in a moment.");
    } catch (err) {
      if (err.name === "AbortError") {
        throw new Error("The server took too long to answer. Please try again.");
      }
      if (err instanceof TypeError) {
        throw new Error("Could not reach the server. Check your internet and try again.");
      }
      throw err;
    } finally {
      clearTimeout(killTimer);
      clearTimeout(wakeTimer);
    }
  }

  // Live feedback: check a field when the user leaves it, re-check while fixing an error.
  Object.keys(RULES).forEach((field) => {
    const input = document.getElementById(field);
    input.addEventListener("blur", () => validateField(field));
    input.addEventListener("input", () => {
      if (input.classList.contains("is-invalid")) validateField(field);
    });
  });

  messageField.addEventListener("input", () => { counter.textContent = messageField.value.length; });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.add("d-none");
    successBox.classList.add("d-none");

    const firstBad = validateAll();
    if (firstBad) {
      document.getElementById(firstBad).focus();
      return;
    }

    setBusy(true);
    try {
      await sendToApi(getData());
      form.reset();
      form.querySelectorAll(".is-valid, .is-invalid").forEach((el) => el.classList.remove("is-valid", "is-invalid"));
      counter.textContent = "0";
      successBox.classList.remove("d-none");
      successBox.focus();
    } catch (err) {
      showError(err.message || "We could not send your message. Please try again.");
    } finally {
      setBusy(false);
    }
  });
})();
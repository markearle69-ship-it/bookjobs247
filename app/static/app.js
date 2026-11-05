(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }

  // ---- ON/OFF switch ----
  var toggle = document.getElementById("agent-toggle");
  if (toggle) {
    toggle.addEventListener("change", function () {
      var on = toggle.checked;
      setToggleUI(on);
      var body = new URLSearchParams({ enabled: on ? "1" : "0" });
      fetch("/app/toggle", { method: "POST", body: body, credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
        .then(function (d) { toggle.checked = d.agent_enabled; setToggleUI(d.agent_enabled); })
        .catch(function () {
          toggle.checked = !on; setToggleUI(!on);
          alert("Couldn't change the setting - check your signal and try again.");
        });
    });
  }
  function setToggleUI(on) {
    var s = document.getElementById("agent-state");
    var d = document.getElementById("agent-desc");
    if (s) { s.textContent = on ? "Assistant ON" : "Assistant OFF"; s.className = "state " + (on ? "on" : "off"); }
    if (d) {
      d.textContent = on
        ? "Missed calls are answered by your AI assistant, which takes the full job details."
        : "Missed calls go to a simple voicemail. Turn on to have your assistant answer.";
    }
  }

  // ---- Push notifications ----
  var isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  var pushCard = document.getElementById("push-card");
  var vapidKey = document.body.getAttribute("data-vapid");

  function b64ToBytes(b64) {
    var pad = "=".repeat((4 - (b64.length % 4)) % 4);
    var raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function show(id) { var el = document.getElementById(id); if (el) el.classList.remove("hidden"); }
  function hide(id) { var el = document.getElementById(id); if (el) el.classList.add("hidden"); }

  function refreshPushCard() {
    if (!pushCard) return;
    var supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
    hide("push-ios"); hide("push-enable"); hide("push-unsupported"); hide("push-denied");
    if (isIOS && !standalone) { pushCard.classList.remove("hidden"); show("push-ios"); return; }
    if (!supported || !vapidKey) { pushCard.classList.remove("hidden"); show("push-unsupported"); return; }
    if (Notification.permission === "denied") { pushCard.classList.remove("hidden"); show("push-denied"); return; }
    navigator.serviceWorker.ready.then(function (reg) {
      return reg.pushManager.getSubscription();
    }).then(function (sub) {
      if (sub && Notification.permission === "granted") {
        pushCard.classList.add("hidden");
        sendSubscription(sub); // keep the server copy fresh
      } else {
        pushCard.classList.remove("hidden"); show("push-enable");
      }
    });
  }

  function sendSubscription(sub) {
    return fetch("/app/push/subscribe", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(sub)
    });
  }

  var enableBtn = document.getElementById("push-enable-btn");
  if (enableBtn) {
    enableBtn.addEventListener("click", function () {
      enableBtn.disabled = true;
      Notification.requestPermission().then(function (perm) {
        if (perm !== "granted") throw new Error("denied");
        return navigator.serviceWorker.ready;
      }).then(function (reg) {
        return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(vapidKey) });
      }).then(function (sub) {
        return sendSubscription(sub);
      }).then(function () {
        return fetch("/app/push/test", { method: "POST", credentials: "same-origin" });
      }).then(function () {
        refreshPushCard();
      }).catch(function () {
        enableBtn.disabled = false;
        refreshPushCard();
      });
    });
  }
  refreshPushCard();

  // ---- Keep the call list fresh when coming back to the app ----
  if (document.body.getAttribute("data-autorefresh") === "1") {
    var hiddenAt = 0;
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) { hiddenAt = Date.now(); }
      else if (hiddenAt && Date.now() - hiddenAt > 15000) { location.reload(); }
    });
    if (navigator.serviceWorker) {
      navigator.serviceWorker.addEventListener("message", function (e) {
        if (e.data && e.data.type === "new-call") location.reload();
      });
    }
  }
})();

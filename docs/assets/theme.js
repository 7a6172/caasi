/* Caasi CLI documentation — theme bootstrap.
 * Loaded synchronously from <head> so the palette is decided before first
 * paint (no flash). Choice order:
 *   1. an explicit choice the reader made (localStorage, cookie fallback),
 *   2. the OS preference (prefers-color-scheme),
 *   3. dark.
 * The choice is stored in localStorage and mirrored into a cookie because
 * browsers block localStorage on file:// pages — without the cookie the
 * theme would reset on every page when the docs are opened locally.
 * A toggle button is injected into the top bar.
 */
(function () {
  "use strict";

  var KEY = "caasi-docs-theme";
  var root = document.documentElement;

  function valid(value) {
    return value === "light" || value === "dark" ? value : null;
  }

  function readCookie() {
    try {
      var parts = document.cookie ? document.cookie.split(";") : [];
      for (var i = 0; i < parts.length; i++) {
        var part = parts[i].replace(/^\s+/, "");
        if (part.indexOf(KEY + "=") === 0) {
          return valid(part.slice(KEY.length + 1));
        }
      }
    } catch (e) {
      /* cookies unavailable */
    }
    return null;
  }

  function stored() {
    try {
      var value = valid(window.localStorage.getItem(KEY));
      if (value) return value;
    } catch (e) {
      /* private mode / file:// — fall through to the cookie */
    }
    return readCookie();
  }

  function osTheme() {
    var mq = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)");
    return mq && mq.matches ? "light" : "dark";
  }

  function apply(theme, remember) {
    root.setAttribute("data-theme", theme);
    if (!remember) return;
    try {
      window.localStorage.setItem(KEY, theme);
    } catch (e) {
      /* private mode / file:// — the cookie below still remembers */
    }
    try {
      document.cookie = KEY + "=" + theme + ";path=/;max-age=31536000;samesite=lax";
    } catch (e) {
      /* nothing else we can do — theme still applies for this page */
    }
  }

  apply(stored() || osTheme(), false);

  // Follow the OS while the reader has not chosen explicitly.
  if (window.matchMedia && !stored()) {
    var mq = window.matchMedia("(prefers-color-scheme: light)");
    var onChange = function (e) {
      if (!stored()) apply(e.matches ? "light" : "dark", false);
    };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }

  function installToggle() {
    var topbar = document.querySelector(".topbar");
    if (!topbar || document.getElementById("theme-toggle")) return;

    var navToggle = document.getElementById("nav-toggle");
    var button = document.createElement("button");
    button.id = "theme-toggle";
    button.type = "button";
    button.title = "Switch between light and dark theme";
    button.setAttribute("aria-label", "Switch between light and dark theme");

    function paint() {
      var dark = root.getAttribute("data-theme") === "dark";
      button.textContent = dark ? "☀" : "☾";
      button.title = dark ? "Switch to light theme" : "Switch to dark theme";
    }

    button.addEventListener("click", function () {
      apply(root.getAttribute("data-theme") === "dark" ? "light" : "dark", true);
      paint();
    });

    paint();
    topbar.insertBefore(button, navToggle || null);
  }

  document.addEventListener("DOMContentLoaded", installToggle);
})();

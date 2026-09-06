/* Caasi CLI documentation — copy buttons for caasi commands.
 * Injects a small "copy" button next to every command that invokes caasi:
 *   • each `$ caasi …` input line of a terminal example (pre.term .in),
 *   • each synopsis block (pre.syn) whose signature starts with caasi.
 * Output lines, YAML/JSON samples and non-caasi shell lines are left alone.
 * The async clipboard API is tried first, with an execCommand fallback
 * because the docs are also read straight off disk (file://), where
 * navigator.clipboard is frequently unavailable.
 */
(function () {
  "use strict";

  var LABEL = "copy";

  // caasi counts as "the command" when it starts the line or follows a shell
  // separator (&&, ||, ;, |, (, $(, sudo) — not when it is merely an argument
  // or a path component (`cd caasi`, `~/.caasi/runs`).
  var CAASI_CALL = /(?:^|&&|\|\||[;|(]|\$\(|\bsudo)\s*caasi(?:\s|$)/;

  function legacyCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;top:0;left:-9999px;opacity:0";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(area);
    return ok ? Promise.resolve() : Promise.reject(new Error("copy failed"));
  }

  function writeClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () {
        return legacyCopy(text);
      });
    }
    return legacyCopy(text);
  }

  /* host — the element the button is appended to (styled absolute in CSS). */
  function attach(host, text) {
    var button = document.createElement("button");
    var timer = 0;

    button.type = "button";
    button.className = "copy-cmd";
    button.textContent = LABEL;
    button.title = "Copy: " + text.split("\n")[0];
    button.setAttribute("aria-label", "Copy command to clipboard");

    function flash(message, cls) {
      window.clearTimeout(timer);
      button.textContent = message;
      button.classList.add(cls);
      timer = window.setTimeout(function () {
        button.textContent = LABEL;
        button.classList.remove("done", "fail");
      }, 1400);
    }

    button.addEventListener("click", function () {
      writeClipboard(text).then(
        function () {
          flash("copied", "done");
        },
        function () {
          flash("failed", "fail");
        }
      );
    });

    host.appendChild(button);
  }

  function install() {
    var lines = document.querySelectorAll("pre.term .in");
    Array.prototype.forEach.call(lines, function (line) {
      var text = line.textContent.replace(/\s+$/, "");
      if (CAASI_CALL.test(text)) attach(line, text);
    });

    var synopses = document.querySelectorAll("pre.syn");
    Array.prototype.forEach.call(synopses, function (pre) {
      var code = pre.querySelector("code");
      if (!code) return;
      var text = code.textContent.replace(/\s+$/, "");
      if (/^caasi(?:\s|$)/m.test(text)) attach(pre, text);
    });
  }

  document.addEventListener("DOMContentLoaded", install);
})();

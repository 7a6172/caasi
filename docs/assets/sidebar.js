/* Caasi CLI documentation — shared sidebar navigation.
 * Every page includes this script; it renders the nav into <aside id="sidebar">
 * and marks the current page/section as active.
 */
(function () {
  "use strict";

  var NAV = [
    {
      title: "Getting Started",
      items: [
        { href: "index.html", label: "Overview" },
        { href: "index.html#architecture", label: "Architecture", sub: true },
        { href: "index.html#installation", label: "Installation", sub: true },
        { href: "index.html#quickstart", label: "Quickstart", sub: true },
        { href: "index.html#conventions", label: "Global options & conventions", sub: true },
        { href: "index.html#command-map", label: "Command map", sub: true }
      ]
    },
    {
      title: "Fundamentals",
      items: [
        { href: "environment.html", label: "Environment" },
        { href: "environment.html#doctor", label: "doctor", sub: true },
        { href: "environment.html#gpu", label: "gpu", sub: true },
        { href: "environment.html#system", label: "system", sub: true },
        { href: "environment.html#info", label: "info & version", sub: true },
        { href: "configuration.html", label: "Configuration" },
        { href: "configuration.html#files", label: "Files & precedence", sub: true },
        { href: "configuration.html#tools", label: "Tool registry", sub: true },
        { href: "configuration.html#config-cmd", label: "caasi config", sub: true },
        { href: "configuration.html#env-vars", label: "Environment variables", sub: true },
        { href: "runs.html", label: "Runs & Logs" },
        { href: "runs.html#model", label: "The run model", sub: true },
        { href: "runs.html#run", label: "caasi run", sub: true },
        { href: "runs.html#logs", label: "caasi logs", sub: true }
      ]
    },
    {
      title: "Projects",
      items: [
        { href: "projects.html", label: "Project workflow" },
        { href: "projects.html#init", label: "init", sub: true },
        { href: "projects.html#setup", label: "setup", sub: true },
        { href: "projects.html#project", label: "project", sub: true },
        { href: "projects.html#definitions", label: "robot / scene / task", sub: true }
      ]
    },
    {
      title: "Simulation & Training",
      items: [
        { href: "simulation.html", label: "sim & lab" },
        { href: "simulation.html#experiment", label: "Experiment YAML", sub: true },
        { href: "simulation.html#sim-run", label: "sim run", sub: true },
        { href: "simulation.html#sim-control", label: "sim status/check/stop", sub: true },
        { href: "simulation.html#lab", label: "lab status", sub: true },
        { href: "training.html", label: "train & benchmark" },
        { href: "training.html#train", label: "train", sub: true },
        { href: "training.html#benchmark", label: "benchmark", sub: true }
      ]
    },
    {
      title: "Data & Review",
      items: [
        { href: "data.html", label: "dataset / sensor / vision" },
        { href: "data.html#dataset", label: "dataset", sub: true },
        { href: "data.html#sensor", label: "sensor", sub: true },
        { href: "data.html#vision", label: "vision", sub: true },
        { href: "review.html", label: "replay & view" },
        { href: "review.html#replay", label: "replay", sub: true },
        { href: "review.html#view", label: "view", sub: true }
      ]
    },
    {
      title: "ROS Ecosystem",
      items: [
        { href: "ros.html", label: "ros / nav / moveit / control" },
        { href: "ros.html#ros", label: "ros", sub: true },
        { href: "ros.html#nav", label: "nav (Nav2)", sub: true },
        { href: "ros.html#moveit", label: "moveit (MoveIt 2)", sub: true },
        { href: "ros.html#control", label: "control (ros2_control)", sub: true }
      ]
    },
    {
      title: "Advanced",
      items: [
        { href: "native.html", label: "native & shell" },
        { href: "native.html#native", label: "native", sub: true },
        { href: "native.html#shell", label: "shell", sub: true },
        { href: "remote.html", label: "remote & container" },
        { href: "remote.html#remote", label: "remote", sub: true },
        { href: "remote.html#container", label: "container", sub: true }
      ]
    }
  ];

  function currentFile() {
    var path = window.location.pathname;
    var file = path.substring(path.lastIndexOf("/") + 1);
    return file === "" ? "index.html" : file;
  }

  function render() {
    var sidebar = document.getElementById("sidebar");
    if (!sidebar) return;
    var here = currentFile();
    var hash = window.location.hash;
    var html = "";

    NAV.forEach(function (group) {
      html += '<div class="nav-group"><div class="nav-title">' + group.title + "</div>";
      group.items.forEach(function (item) {
        var file = item.href.split("#")[0];
        var anchor = item.href.indexOf("#") >= 0 ? item.href.split("#")[1] : "";
        var active =
          file === here &&
          (anchor === "" ? hash === "" || hash === "#" + (item.sub ? "" : anchor) : hash === "#" + anchor);
        if (file === here && anchor !== "" && hash === "#" + anchor) active = true;
        var cls = (item.sub ? "sub" : "") + (active ? " active" : "");
        html += '<a class="' + cls.trim() + '" href="' + item.href + '">' + item.label + "</a>";
      });
      html += "</div>";
    });

    sidebar.innerHTML = html;

    // If only the page (no hash) matches, highlight the top-level entry.
    if (!hash) {
      var links = sidebar.querySelectorAll('a:not(.sub)');
      links.forEach(function (a) {
        if (a.getAttribute("href").split("#")[0] === here) a.classList.add("active");
      });
    }
  }

  function installToggle() {
    var toggle = document.getElementById("nav-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", function () {
      document.body.classList.toggle("nav-open");
    });
    document.getElementById("sidebar").addEventListener("click", function (e) {
      if (e.target.tagName === "A") document.body.classList.remove("nav-open");
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    render();
    installToggle();
  });
})();

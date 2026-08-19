/* FetchJAV marketing site — small vanilla-JS interactions */
(function () {
  "use strict";

  /* Mobile nav toggle */
  var toggle = document.querySelector(".nav-toggle");
  var links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      links.classList.toggle("open");
      var expanded = links.classList.contains("open");
      toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (!e.target.closest(".nav") && links.classList.contains("open")) {
        links.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  /* Scroll-reveal */
  var revealEls = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && revealEls.length) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
    );
    revealEls.forEach(function (el) {
      io.observe(el);
    });
  } else {
    revealEls.forEach(function (el) {
      el.classList.add("in");
    });
  }

  /* Footer year */
  var year = document.querySelectorAll("[data-year]");
  year.forEach(function (el) {
    el.textContent = String(new Date().getFullYear());
  });

  /* Request form → GitHub issue */
  var reqForm = document.getElementById("requestForm");
  if (reqForm) {
    var GITHUB_REPO = "Deepu770/FetchJav-Help-Repo";

    var typeLabels = {
      question: "Question",
      feature: "Feature Request",
      change: "Change Request",
      bug: "Bug Report",
    };

    var typeTemplates = {
      question: "## Question\n\n<!-- Describe your question here -->",
      feature: "## Feature request\n\n**Describe the feature you'd like**\n\n\n\n**Why is this useful?**\n\n",
      change: "## Change request\n\n**What would you like changed?**\n\n\n\n**Why should it change?**\n\n",
      bug: "## Bug report\n\n**Steps to reproduce**\n1. \n2. \n3. \n\n**Expected behavior**\n\n\n\n**Actual behavior**\n\n",
    };

    reqForm.addEventListener("submit", function (e) {
      e.preventDefault();

      var type = reqForm.querySelector('input[name="type"]:checked').value;
      var subject = document.getElementById("reqSubject").value.trim();
      var desc = document.getElementById("reqDesc").value.trim();
      var email = document.getElementById("reqEmail").value.trim();
      var version = document.getElementById("reqVersion").value.trim();

      if (!subject) {
        document.getElementById("reqSubject").focus();
        return;
      }
      if (!desc) {
        document.getElementById("reqDesc").focus();
        return;
      }

      var body = typeTemplates[type] || "";
      body = body.replace("<!-- Describe your question here -->", desc);

      if (email) body += "\n**Contact:** " + email;
      if (version) body += "\n**App version:** " + version;
      body += "\n\n---\n*Submitted via FetchJAV request page*";

      var title = encodeURIComponent("[" + typeLabels[type] + "] " + subject);
      var bodyEnc = encodeURIComponent(body);
      var labels = encodeURIComponent(type);

      var url =
        "https://github.com/" +
        GITHUB_REPO +
        "/issues/new?title=" +
        title +
        "&body=" +
        bodyEnc +
        "&labels=" +
        labels;

      window.open(url, "_blank", "noopener");

      reqForm.innerHTML =
        '<div class="req-success">' +
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>' +
        "<h3>Opening GitHub&hellip;</h3>" +
        "<p>A new tab should open with your pre-filled issue. If it didn't, check your popup blocker.</p>" +
        "</div>";
    });
  }
})();

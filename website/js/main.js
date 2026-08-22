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

  /* Version history on download page */
  var verList = document.getElementById("versionList");
  if (verList) {
    var API_URL = "https://api.github.com/repos/FetchJAV/FetchJAV_Public/releases";

    fetch(API_URL)
      .then(function (res) { return res.json(); })
      .then(function (releases) {
        if (!Array.isArray(releases) || !releases.length) {
          verList.innerHTML = '<div class="ver-loading">No releases found.</div>';
          return;
        }

        var html = "";
        releases.forEach(function (r, i) {
          var tag = r.tag_name || "";
          var name = r.name || tag;
          var date = r.published_at ? new Date(r.published_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "";
          var body = (r.body || "").split("\n").slice(0, 3).join(" ").replace(/[*_`#]/g, "").trim();
          if (body.length > 140) body = body.slice(0, 140) + "…";
          var latest = i === 0;
          var exeAsset = (r.assets || []).find(function (a) { return a.name && a.name.endsWith(".exe"); });
          var downloadUrl = exeAsset ? exeAsset.browser_download_url : r.html_url;
          var allAssetsUrl = r.html_url;

          html += '<div class="ver-item' + (latest ? " ver-latest" : "") + '">';
          html += '  <div class="ver-info">';
          html += '    <div class="ver-head">';
          html += '      <span class="ver-tag">' + name + "</span>";
          if (latest) html += '      <span class="ver-badge">Latest</span>';
          html += '      <span class="ver-date">' + date + "</span>";
          html += "    </div>";
          if (body) html += '    <p class="ver-note">' + body + "</p>";
          html += "  </div>";
          html += '  <div class="ver-actions">';
          html += '    <a class="btn btn-primary" href="' + downloadUrl + '" download>';
          html += '      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="width:14px;height:14px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>';
          html += "      Download";
          html += "    </a>";
          html += '    <a class="btn btn-ghost" href="' + allAssetsUrl + '" target="_blank" rel="noopener">View release</a>';
          html += "  </div>";
          html += "</div>";
        });

        verList.innerHTML = html;
      })
      .catch(function () {
        verList.innerHTML = '<div class="ver-loading">Could not load releases. <a href="https://github.com/Deepu770/FetchJav-Help-Repo/releases" target="_blank" rel="noopener" style="color:var(--link);">View on GitHub</a></div>';
      });
  }

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

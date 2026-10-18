// Fresh finds strip on the home page. Two small extras; everything works
// without them too:
// 1. The very first time, the feeds are still being read when the page
//    opens. Check back a few times and swap in the strip once it's ready.
// 2. Import takes a few seconds (it reads the recipe site), so the button
//    says "Importing..." and can't be pressed twice.

(function () {
    var tries = 0;

    function checkAgain() {
        var strip = document.getElementById("fresh-finds");
        if (!strip || !strip.hasAttribute("data-refreshing") || tries >= 6) {
            return;
        }
        tries += 1;
        setTimeout(function () {
            fetch("/fresh-finds")
                .then(function (response) { return response.ok ? response.text() : null; })
                .then(function (html) {
                    if (html) {
                        strip.outerHTML = html;
                    }
                    checkAgain();
                })
                .catch(function () { /* offline: leave the page as it is */ });
        }, 3000);
    }

    // On the whole page, so it also works for a strip that was swapped in
    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (form.classList && form.classList.contains("find-import")) {
            var button = form.querySelector("button");
            // Wait a moment so the form still sends before the button is disabled
            setTimeout(function () {
                button.disabled = true;
                button.textContent = "Importing…";
            }, 0);
        }
    });

    checkAgain();
})();

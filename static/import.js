// Import page: the "Copy prompt" button. Same approach as "Copy as text"
// on the grocery list (see grocery.js).

const promptBox = document.getElementById("prompt-text");
const promptStatus = document.getElementById("copy-prompt-status");

// Old-style copy: select the text box and ask the browser to copy it.
// If even that fails, leave the text selected for a manual copy.
function fallbackCopyPrompt() {
    promptBox.closest("details").open = true;
    promptBox.focus();
    promptBox.select();
    promptBox.setSelectionRange(0, promptBox.value.length); // needed on iPhones
    let copied = false;
    try {
        copied = document.execCommand("copy");
    } catch (e) {}
    promptStatus.textContent = copied ? "Copied!" : "Select the text below and copy it.";
}

document.getElementById("copy-prompt").addEventListener("click", () => {
    // navigator.clipboard only exists on https or localhost
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(promptBox.value)
            .then(() => (promptStatus.textContent = "Copied!"))
            .catch(fallbackCopyPrompt);
    } else {
        fallbackCopyPrompt();
    }
});

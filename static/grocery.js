// Grocery list page: remember ticks, clear them, and copy the list as text.

// --- Remembering ticks ---
// The page names this exact plan in data-plan (recipe ids and servings, e.g.
// "2x4,3x8"). Ticks are saved in the browser under that name, so a different
// week's plan starts with a clean list, but switching US/metric keeps your ticks.
const storageKey = "grocery-checks:" + document.getElementById("grocery").dataset.plan;

const boxes = document.querySelectorAll("#grocery input[type=checkbox]");

// Read the saved ticks: a list of item keys like ["butter", "eggs"].
// Wrapped in try because private browsing can block storage.
function loadChecks() {
    try {
        return JSON.parse(localStorage.getItem(storageKey)) || [];
    } catch (e) {
        return [];
    }
}

function saveChecks() {
    const checked = [...boxes].filter(box => box.checked).map(box => box.dataset.key);
    try {
        localStorage.setItem(storageKey, JSON.stringify(checked));
    } catch (e) {
        // Can't save: ticks still work, they just won't survive a reload
    }
    updateText();
}

// Tick the saved boxes when the page loads
const saved = loadChecks();
boxes.forEach(box => {
    box.checked = saved.includes(box.dataset.key);
    box.addEventListener("change", saveChecks);
});

document.getElementById("clear-checks").addEventListener("click", () => {
    boxes.forEach(box => (box.checked = false));
    saveChecks();
});

// --- Copy as text ---
const textBox = document.getElementById("list-text");
const copyStatus = document.getElementById("copy-status");

// Build the unticked items as text, grouped by aisle. Same format as
// grocery_text() in grocery.py (which is tested): heading, "- item" lines,
// a blank line between aisles, and aisles with nothing left are skipped.
function listText() {
    const sections = [];
    document.querySelectorAll("#grocery .aisle").forEach(aisle => {
        const lines = [];
        aisle.querySelectorAll("li").forEach(li => {
            if (!li.querySelector("input").checked) {
                lines.push("- " + li.querySelector("span").textContent);
            }
        });
        if (lines.length) {
            sections.push([aisle.querySelector("h3").textContent, ...lines].join("\n"));
        }
    });
    return sections.join("\n\n");
}

// Keep the "Show list as text" box in step with the ticks
function updateText() {
    textBox.value = listText();
}
updateText();

// Old-style copy: select the text box and ask the browser to copy it.
// If even that fails, leave the box open and selected for a manual copy.
function fallbackCopy() {
    document.getElementById("list-text-box").open = true;
    textBox.focus();
    textBox.select();
    textBox.setSelectionRange(0, textBox.value.length); // needed on iPhones
    let copied = false;
    try {
        copied = document.execCommand("copy");
    } catch (e) {}
    copyStatus.textContent = copied ? "Copied!" : "Select the text below and copy it.";
}

document.getElementById("copy-list").addEventListener("click", () => {
    updateText();
    // navigator.clipboard only exists on https or localhost, not on plain
    // http from a phone, so check for it first
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(textBox.value)
            .then(() => (copyStatus.textContent = "Copied!"))
            .catch(fallbackCopy);
    } else {
        fallbackCopy();
    }
});

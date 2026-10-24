// Shared page helpers: relative times and tabs. Loaded in <head>, so page
// scripts can call these functions directly.

// "in 12 min" / "3 h ago"; the absolute time stays in the title.
function relativeTime(date) {
  const minutes = Math.round((date.getTime() - Date.now()) / 60000);
  const abs = Math.abs(minutes);
  if (abs < 1) return "now";
  let text;
  if (abs < 60) text = `${abs} min`;
  else if (abs < 48 * 60) text = `${Math.round(abs / 60)} h`;
  else text = `${Math.round(abs / 1440)} d`;
  return minutes > 0 ? `in ${text}` : `${text} ago`;
}

function renderRelativeTimes() {
  document.querySelectorAll(".js-rel").forEach((element) => {
    // data-utc: naive UTC ISO from the run records; data-local: server-local "YYYY-MM-DD HH:MM".
    const raw = element.dataset.utc ? `${element.dataset.utc}Z` : (element.dataset.local || "").replace(" ", "T");
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return;
    if (!element.title) element.title = date.toLocaleString();
    element.textContent = relativeTime(date);
  });
}

// Tabs: each [data-tab] link shows the panel with the same id. Anchors inside a
// panel (e.g. #run-log) open the panel that contains them.
function initTabs() {
  const links = Array.from(document.querySelectorAll(".tabs [data-tab]"));
  if (!links.length) return;
  const panels = links.map((link) => document.getElementById(link.dataset.tab));

  function show(hash) {
    const target = hash ? document.getElementById(hash.slice(1)) : null;
    const panel = (target && panels.find((candidate) => candidate && candidate.contains(target))) || panels[0];
    panels.forEach((candidate) => candidate && candidate.classList.toggle("is-hidden", candidate !== panel));
    links.forEach((link) => link.setAttribute("aria-selected", String(link.dataset.tab === panel.id)));
    // A tab link keeps the page at the top; an anchor inside a panel scrolls to it.
    if (target && target !== panel) target.scrollIntoView();
    else window.scrollTo(0, 0);
  }

  links.forEach((link) =>
    link.addEventListener("click", (event) => {
      event.preventDefault();
      history.replaceState(null, "", `#${link.dataset.tab}`);
      show(`#${link.dataset.tab}`);
    }),
  );
  window.addEventListener("hashchange", () => show(window.location.hash));
  show(window.location.hash);
}

document.addEventListener("DOMContentLoaded", () => {
  renderRelativeTimes();
  window.setInterval(renderRelativeTimes, 30000);
  initTabs();
});

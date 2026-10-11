// The viewer page: draws what /api/view returns and turns clicks into requests.
//
// Every graph decision — links, cycles, metrics, frames, labels — is made by the
// server; this file keeps the view state (in the URL), the package tree, and
// the canvas.

/* global cytoscape, cytoscapeElk */

cytoscape.use(cytoscapeElk);

const $ = (id) => document.getElementById(id);

// --- state ----------------------------------------------------------------

const state = {
  patterns: [],
  folded: new Set(),
  links: "module",
  metric: "",
  focus: null,
};

/** The package tree: id → {id, package, children: [ids]}. */
const tree = new Map();
let roots = [];
let view = null;
let sequence = 0;

function readUrl() {
  const params = new URLSearchParams(location.search);
  state.patterns = params.getAll("m");
  state.folded = new Set(params.getAll("fold"));
  state.links = params.get("links") === "class" ? "class" : "module";
  state.metric = params.get("metric") || "";
  state.focus = params.get("focus");
}

function writeUrl() {
  const params = new URLSearchParams();
  state.patterns.forEach((p) => params.append("m", p));
  params.set("links", state.links);
  [...state.folded].sort().forEach((f) => params.append("fold", f));
  if (state.metric) params.set("metric", state.metric);
  if (state.focus) params.set("focus", state.focus);
  history.replaceState(null, "", `?${params}`);
}

// --- server ---------------------------------------------------------------

async function loadTree() {
  const response = await fetch("/api/tree");
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  $("project").textContent = data.project;
  roots = data.roots;
  for (const module of data.modules) {
    tree.set(module.id, { ...module, children: [] });
  }
  for (const module of data.modules) {
    const parent = parentOf(module.id);
    if (parent !== null && tree.has(parent)) tree.get(parent).children.push(module.id);
  }
  if (state.patterns.length === 0) {
    // Opened bare: what `serve` opens on — every root, its subpackages folded.
    state.patterns = roots.map((r) => `${r}.**`);
    roots.forEach((r) => subpackages(r).forEach((child) => state.folded.add(child)));
  }
}

async function refresh() {
  pending = false;
  showPending();
  writeUrl();
  const mine = ++sequence;
  $("busy").hidden = false;
  try {
    const response = await fetch("/api/view", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patterns: state.patterns,
        folded: [...state.folded],
        links: state.links,
        metric: state.metric || null,
      }),
    });
    const data = await response.json();
    if (mine !== sequence) return; // a newer request superseded this one
    if (!response.ok) {
      showError(data.error);
      return;
    }
    showError(null);
    view = data;
    draw();
  } catch (error) {
    if (mine === sequence) showError(`the server did not answer: ${error}`);
  } finally {
    if (mine === sequence) $("busy").hidden = true;
  }
  renderTree();
}

function showError(message) {
  $("banner").hidden = !message;
  $("banner").textContent = message || "";
}

// --- packages and modules -----------------------------------------------------

/** "1 module", "12 modules". */
function modulesText(id) {
  const count = moduleCount(id);
  return `${count} module${count === 1 ? "" : "s"}`;
}

/** How many modules lie under a package (its own facade not counted). */
function moduleCount(id) {
  let count = 0;
  for (const entry of tree.values()) {
    if (!entry.package && entry.id.startsWith(`${id}.`)) count += 1;
  }
  return count;
}

/** Whether ``id`` names a package: a frame or a folded box is one, a module file is not. */
function isPackage(id) {
  const entry = tree.get(id);
  return entry ? entry.package : true;
}

const PACKAGE_ICON = "📁";
const OPEN_PACKAGE_ICON = "📂";
const MODULE_ICON = "📄";

// --- folding ----------------------------------------------------------------

function parentOf(id) {
  const cut = id.lastIndexOf(".");
  return cut === -1 ? null : id.slice(0, cut);
}

function isUnder(id, prefix) {
  return id === prefix || id.startsWith(`${prefix}.`);
}

function subpackages(id) {
  const entry = tree.get(id);
  return entry ? entry.children.filter((child) => tree.get(child).package) : [];
}

/** Unfold one level: the package's own subpackages stay folded. */
function unfold(id) {
  state.folded.delete(id);
  subpackages(id).forEach((child) => state.folded.add(child));
}

/** Show a package one level deep: its modules, each subpackage folded. */
function openOneLevel(id) {
  [...state.folded].filter((f) => isUnder(f, id)).forEach((f) => state.folded.delete(f));
  subpackages(id).forEach((child) => state.folded.add(child));
}

function foldInto(id) {
  [...state.folded].filter((f) => isUnder(f, id)).forEach((f) => state.folded.delete(f));
  state.folded.add(id);
}

/** Unfold whatever hides ``id`` inside a folded package. */
function reveal(id) {
  let hidden = [...state.folded].find((f) => f !== id && isUnder(id, f));
  while (hidden) {
    unfold(hidden);
    hidden = [...state.folded].find((f) => f !== id && isUnder(id, f));
  }
}

function toggleFold(id) {
  if (state.folded.has(id)) unfold(id);
  else foldInto(id);
  refresh();
}

// --- selection (the tree's checkboxes) ---------------------------------------

/** Whether ``id`` is selected by the current patterns (globs approximated by their stem). */
function selected(id) {
  return state.patterns.some((pattern) => {
    const star = pattern.indexOf("*");
    const stem = star === -1 ? pattern : pattern.slice(0, Math.max(star - 1, 0));
    return stem !== "" && isUnder(id, stem);
  });
}

function patternOf(id) {
  return tree.get(id).package ? `${id}.**` : id;
}

/** Patterns for a set of checked ids: a whole package as one pattern. */
function patternsFor(checked) {
  const out = [];
  const walk = (id) => {
    if (checked.has(id)) {
      out.push(patternOf(id));
      return;
    }
    tree.get(id).children.forEach(walk);
  };
  roots.filter((r) => tree.has(r)).forEach(walk);
  return out;
}

function checkedIds() {
  const checked = new Set();
  for (const id of tree.keys()) {
    const parent = parentOf(id);
    if (selected(id) && (parent === null || !selected(parent))) checked.add(id);
  }
  return checked;
}

function setChecked(id, on) {
  const checked = checkedIds();
  // A box under a checked package: replace the package by its other children.
  let ancestor = parentOf(id);
  while (ancestor !== null) {
    if (checked.has(ancestor)) {
      checked.delete(ancestor);
      const expand = (pkg) => {
        tree.get(pkg).children.forEach((child) => {
          if (isUnder(id, child) && child !== id) expand(child);
          else if (child !== id) checked.add(child);
        });
      };
      expand(ancestor);
      break;
    }
    ancestor = parentOf(ancestor);
  }
  const inside = [...checked].filter((c) => c !== id && isUnder(c, id));
  [...checked].filter((c) => isUnder(c, id)).forEach((c) => checked.delete(c));
  if (on) {
    checked.add(id);
    if (tree.get(id).package) tickPackage(id, inside);
  }
  state.patterns = patternsFor(checked);
  selectionChanged();
}

/**
 * How a package just ticked is drawn. On its own: one box, the user unfolds it.
 * Around what is already shown (``inside``): one level deep, so that stays in
 * view as it was — each other subpackage folded.
 */
function tickPackage(id, inside) {
  if (inside.length === 0) {
    foldInto(id);
    return;
  }
  state.folded.delete(id);
  for (const child of subpackages(id)) {
    if (!inside.some((shown) => isUnder(shown, child))) foldInto(child);
  }
}

// --- redrawing: at once, or when asked -----------------------------------------

const AUTO_REDRAW_KEY = "arch-blueprint.autoRedraw";
let autoRedraw = readAutoRedraw();
let pending = false;

function readAutoRedraw() {
  try {
    return localStorage.getItem(AUTO_REDRAW_KEY) !== "off";
  } catch {
    return true;
  }
}

function writeAutoRedraw(on) {
  try {
    localStorage.setItem(AUTO_REDRAW_KEY, on ? "on" : "off");
  } catch {
    // no storage (a private window): the toggle lasts for this page only
  }
}

/** The ticked boxes changed: redraw now, or hold the change for "Redraw". */
function selectionChanged() {
  if (autoRedraw) {
    redraw();
    return;
  }
  pending = true;
  showPending();
  renderTree();
}

function redraw() {
  if (state.patterns.length === 0) {
    showError("tick at least one package or module");
    renderTree();
    return;
  }
  refresh();
}

function showPending() {
  $("redraw").disabled = !pending;
  $("redraw").classList.toggle("pending", pending);
  $("redraw").textContent = pending ? "Redraw ●" : "Redraw";
}

// --- the tree -------------------------------------------------------------

/** The selected, folded package ``id`` is drawn inside, if any. */
function foldedAround(id) {
  return [...state.folded].find((f) => f !== id && isUnder(id, f) && selected(f)) ?? null;
}

/**
 * What a tree row's checkbox shows — what is drawn, not what the patterns
 * cover: "on" for a box on the graph (a module, a folded package), "hidden" for
 * one inside a folded box, "off" for one not selected, and for an opened
 * package, "on" / "partial" / "off" by what is drawn inside it.
 */
function shownState(id, memo) {
  if (memo.has(id)) return memo.get(id);
  let result;
  const entry = tree.get(id);
  if (!selected(id) && !entry.package) result = "off";
  else if (selected(id) && foldedAround(id) !== null) result = "hidden";
  else if (!entry.package || (selected(id) && state.folded.has(id))) {
    result = selected(id) ? "on" : "off";
  } else {
    const inner = entry.children.map((child) => shownState(child, memo));
    const on = inner.filter((s) => s === "on").length;
    if (inner.length > 0 && on === inner.length) result = "on";
    else if (inner.some((s) => s === "on" || s === "partial")) result = "partial";
    else result = "off";
  }
  memo.set(id, result);
  return result;
}

const expanded = new Set();

function renderTree() {
  const container = $("tree");
  container.replaceChildren();
  const memo = new Map();
  const rows = [];
  const walk = (id, depth) => {
    const entry = tree.get(id);
    const row = document.createElement("div");
    row.className = "row";
    if (id === state.focus) row.classList.add("current");
    row.style.paddingLeft = `${depth * 14}px`;

    const fold = document.createElement("span");
    fold.className = "fold";
    const open = expanded.has(id);
    if (entry.package) {
      fold.textContent = open ? "▾" : "▸";
      fold.title = open ? "collapse in the tree" : "expand in the tree";
      fold.onclick = () => {
        if (open) expanded.delete(id);
        else expanded.add(id);
        renderTree();
      };
    } else {
      fold.classList.add("off");
      fold.textContent = "·";
    }

    const box = document.createElement("input");
    box.type = "checkbox";
    const shown = shownState(id, memo);
    box.checked = shown === "on";
    box.indeterminate = shown === "partial";
    box.title =
      shown === "hidden"
        ? `inside the folded ${foldedAround(id)} — tick to draw it on its own`
        : "draw on the graph";
    box.onchange = () => {
      if (shown === "hidden") {
        reveal(id);
        selectionChanged();
      } else {
        setChecked(id, box.checked);
      }
    };

    const name = document.createElement("span");
    name.className = "name";
    const icon = entry.package ? PACKAGE_ICON : MODULE_ICON;
    name.textContent = `${icon} ${depth === 0 ? id : id.slice(id.lastIndexOf(".") + 1)}`;
    name.title = state.folded.has(id) ? `${id} (folded)` : id;
    if (state.folded.has(id) && state.links === "module") name.textContent += "  ⊞";
    name.onclick = () => goTo(id);
    if (shown === "off" || shown === "hidden") name.style.opacity = "0.6";

    row.append(fold, box, name);
    if (entry.package) {
      const only = document.createElement("button");
      only.type = "button";
      only.className = "only";
      only.textContent = "only";
      only.title = `Show only what ${id} holds (Back returns)`;
      only.onclick = () => isolate(id);
      row.append(only);
    }
    rows.push(row);
    if (entry.package && open) entry.children.forEach((child) => walk(child, depth + 1));
  };
  roots.filter((r) => tree.has(r)).forEach((r) => walk(r, 0));
  container.append(...rows);
}

// --- the canvas -------------------------------------------------------------

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const cy = cytoscape({
  container: $("canvas"),
  wheelSensitivity: 0.3,
  minZoom: 0.05,
  maxZoom: 3,
  style: [
    {
      selector: "node",
      style: {
        shape: "round-rectangle",
        label: "data(label)",
        "text-wrap": "wrap",
        "text-valign": "center",
        "text-halign": "center",
        "font-size": 12,
        "font-family": "ui-monospace, monospace",
        color: css("--fg"),
        "background-color": "data(color)",
        "background-opacity": 0.18,
        "border-width": 1.5,
        "border-color": "data(color)",
        width: "label",
        height: "label",
        padding: "8px",
      },
    },
    {
      selector: "node.folded",
      style: {
        shape: "rectangle",
        "border-width": 5,
        "border-style": "double",
        "background-opacity": 0.4,
        "font-weight": "bold",
      },
    },
    {
      selector: "node.frame",
      style: {
        shape: "round-rectangle",
        "background-color": css("--frame"),
        "background-opacity": 0.6,
        "border-color": css("--frame-line"),
        "border-width": 1,
        "text-valign": "top",
        "text-halign": "center",
        "font-size": 11,
        color: css("--muted"),
        padding: "14px",
      },
    },
    {
      selector: "edge",
      style: {
        width: 1.4,
        "curve-style": "bezier",
        "line-color": css("--muted"),
        "target-arrow-color": css("--muted"),
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.9,
        label: "data(label)",
        "font-size": 10,
        color: css("--muted"),
        "text-background-color": css("--bg"),
        "text-background-opacity": 1,
        "text-background-padding": "2px",
      },
    },
    {
      selector: "edge.cyclic, edge.cycle",
      style: { "line-color": "data(cycleColor)", "target-arrow-color": "data(cycleColor)" },
    },
    {
      selector: "edge.cycle",
      style: {
        width: 2.2,
        "source-arrow-shape": "triangle",
        "source-arrow-color": "data(cycleColor)",
      },
    },
    { selector: ".dim", style: { opacity: 0.12 } },
    { selector: "node.match", style: { "border-color": css("--accent"), "border-width": 3 } },
    {
      selector: "node:selected, edge:selected",
      style: { "overlay-color": css("--accent"), "overlay-opacity": 0.15 },
    },
  ],
});

window.viewer = { cy, state }; // for the browser console
cy.on("resize", () => cy.fit(undefined, 30));

function nodeLabel(node) {
  let label = node.label;
  if (node.folded) {
    label = `${PACKAGE_ICON} ${label}\n${modulesText(node.id)}`;
  }
  const value = state.metric && node.metrics[state.metric];
  return value === undefined || value === "" || value === false
    ? label
    : `${label}\n${state.metric} ${value}`;
}

function frameLabel(frame) {
  return `${isPackage(frame.id) ? OPEN_PACKAGE_ICON : MODULE_ICON} ${frame.label}`;
}

function linkLabel(link) {
  const value = state.metric && link.metrics[state.metric];
  return value === undefined || value === false ? "" : String(value);
}

function elements() {
  const cycleColor = view.cycleColor;
  const out = [];
  for (const frame of view.frames) {
    out.push({
      group: "nodes",
      data: { id: frame.id, label: frameLabel(frame), parent: frame.parent ?? undefined },
      classes: "frame",
    });
  }
  for (const node of view.nodes) {
    out.push({
      group: "nodes",
      data: {
        id: node.id,
        label: nodeLabel(node),
        parent: node.parent ?? undefined,
        color: node.color,
      },
      classes: node.folded ? "folded" : "",
    });
  }
  for (const link of view.links) {
    out.push({
      group: "edges",
      data: {
        id: `link:${link.source}>${link.target}`,
        source: link.source,
        target: link.target,
        label: linkLabel(link),
        cycleColor,
      },
      classes: link.cyclic ? "cyclic" : "",
    });
  }
  for (const cycle of view.cycles) {
    out.push({
      group: "edges",
      data: {
        id: `cycle:${cycle.a}|${cycle.b}`,
        source: cycle.a,
        target: cycle.b,
        label: linkLabel(cycle),
        cycleColor,
      },
      classes: "cycle",
    });
  }
  return out;
}

function draw() {
  const metricSelect = $("metric");
  const names = [...view.metrics.node, ...view.metrics.link];
  metricSelect.replaceChildren(new Option("none", ""), ...names.map((n) => new Option(n, n)));
  metricSelect.value = names.includes(state.metric) ? state.metric : "";
  $("links").value = state.links;

  const wanted = elements();
  const same =
    wanted.length === cy.elements().length &&
    wanted.every((item) => {
      const current = cy.getElementById(item.data.id);
      return current.nonempty() && (current.data("parent") ?? undefined) === item.data.parent;
    });
  if (same) {
    // Only labels or styles changed (a metric): keep the picture where it is.
    wanted.forEach((item) => {
      const current = cy.getElementById(item.data.id);
      current.data(item.data);
      current.classes(item.classes);
    });
  } else {
    cy.elements().remove();
    cy.add(wanted);
    layout();
  }
  showScope();

  const stats = `${view.nodes.length} boxes · ${view.links.length + view.cycles.length} arrows`;
  $("stats").textContent = view.cycles.length
    ? `${stats} · ${view.cycles.length} cycles`
    : stats;

  if (state.focus && cy.getElementById(state.focus).nonempty()) {
    focusOn(cy.getElementById(state.focus), false);
  } else {
    state.focus = null;
    showHelp();
  }
}

function layout() {
  cy.layout({
    name: "elk",
    fit: true,
    padding: 30,
    nodeDimensionsIncludeLabels: true,
    elk: {
      algorithm: "layered",
      "elk.direction": "DOWN",
      "elk.hierarchyHandling": "INCLUDE_CHILDREN",
      "elk.layered.spacing.nodeNodeBetweenLayers": 40,
      "elk.spacing.nodeNode": 24,
    },
  }).run();
}

// --- showing only one package --------------------------------------------------

/** The package the view is narrowed to, when it shows exactly one. */
function scope() {
  if (state.patterns.length !== 1) return null;
  const [pattern] = state.patterns;
  const stem = pattern.endsWith(".**") ? pattern.slice(0, -3) : pattern;
  return roots.includes(stem) ? null : stem;
}

/** Show only what ``id`` holds; the browser's Back button returns. */
function isolate(id) {
  history.pushState(null, "", location.search);
  state.patterns = [isPackage(id) ? `${id}.**` : id];
  state.folded = new Set();
  openOneLevel(id);
  state.focus = null;
  for (let name = id; name !== null; name = parentOf(name)) expanded.add(name);
  refresh();
}

function showAll() {
  history.pushState(null, "", location.search);
  state.patterns = roots.map((r) => `${r}.**`);
  state.folded = new Set(roots.flatMap((r) => subpackages(r)));
  state.focus = null;
  refresh();
}

function showScope() {
  const only = scope();
  $("scope").hidden = only === null;
  $("scope-name").textContent = only ?? "";
}

window.addEventListener("popstate", () => {
  readUrl();
  refresh();
});

function clearFocus() {
  cy.elements().removeClass("dim match");
  cy.elements().unselect();
}

function focusOn(element, center = true) {
  clearFocus();
  // A frame stands for everything in it: keep the arrows of what it holds.
  const members = element.isNode() ? element.union(element.descendants()) : element;
  const keep = element.isEdge()
    ? element.union(element.connectedNodes())
    : members.union(members.closedNeighborhood());
  const ancestors = keep.nodes().ancestors();
  cy.elements().not(keep.union(ancestors)).addClass("dim");
  element.select();
  if (element.isNode()) {
    state.focus = element.id();
    writeUrl();
    showNode(element);
    if (center) cy.animate({ center: { eles: element }, duration: 250 });
  } else {
    showEdge(element);
  }
}

cy.on("tap", "node", (event) => focusOn(event.target, false));
cy.on("tap", "edge", (event) => focusOn(event.target, false));
cy.on("tap", (event) => {
  if (event.target === cy) {
    clearFocus();
    state.focus = null;
    writeUrl();
    showHelp();
  }
});
cy.on("dbltap", "node", (event) => {
  const id = event.target.id();
  if (state.links !== "module") return;
  if (event.target.hasClass("frame") || state.folded.has(id)) toggleFold(id);
});

// --- the inspector ----------------------------------------------------------

function el(tag, text, attrs = {}) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  Object.assign(element, attrs);
  return element;
}

function link(id) {
  return el("a", id, { onclick: () => goTo(id) });
}

function showHelp() {
  const details = $("details");
  details.replaceChildren(
    el(
      "p",
      "Click a box to see what it depends on and what depends on it. Click an arrow " +
        "for the imports behind it. Double-click a package to fold or unfold it. " +
        "Esc clears the focus.",
      { className: "hint" },
    ),
  );
}

function metricTable(values) {
  const table = el("table");
  for (const [name, value] of Object.entries(values)) {
    const row = el("tr");
    row.append(el("td", name), el("td", String(value)));
    table.append(row);
  }
  return table;
}

function connectionsOf(id) {
  const out = [];
  const into = [];
  for (const l of view.links) {
    if (l.source === id) out.push(l.target);
    if (l.target === id) into.push(l.source);
  }
  for (const c of view.cycles) {
    if (c.a === id) {
      out.push(c.b);
      into.push(c.b);
    }
    if (c.b === id) {
      out.push(c.a);
      into.push(c.a);
    }
  }
  return { out: [...new Set(out)].sort(), into: [...new Set(into)].sort() };
}

function list(title, ids) {
  const section = [el("h4", `${title} (${ids.length})`)];
  const ul = el("ul");
  ids.forEach((id) => {
    const li = el("li");
    li.append(link(id));
    ul.append(li);
  });
  section.push(ul);
  return section;
}

function showNode(element) {
  const details = $("details");
  const id = element.id();
  if (element.hasClass("frame")) {
    const actions = el("div", undefined, { className: "actions" });
    if (state.links === "module") {
      const fold = el("button", "fold into one box", { type: "button" });
      fold.onclick = () => toggleFold(id);
      actions.append(fold);
    }
    actions.append(onlyButton(id));
    const what = isPackage(id) ? `package · ${modulesText(id)}` : "module";
    details.replaceChildren(el("h3", id), el("p", what, { className: "hint" }), actions);
    return;
  }
  const node = view.nodes.find((n) => n.id === id);
  const { out, into } = connectionsOf(id);
  const kinds = {
    M: state.folded.has(id) ? `package (folded) · ${modulesText(id)}` : "module",
    C: "class",
    F: "function",
  };
  const parts = [el("h3", id), el("p", kinds[node.kind] || node.kind, { className: "hint" })];
  if (Object.keys(node.metrics).length) parts.push(el("h4", "metrics"), metricTable(node.metrics));
  parts.push(...list("depends on", out), ...list("used by", into));
  if (node.folded) {
    const unfoldButton = el("button", "unfold", { type: "button" });
    unfoldButton.onclick = () => toggleFold(id);
    const actions = el("div", undefined, { className: "actions" });
    actions.append(unfoldButton, onlyButton(id));
    parts.push(actions);
  }
  details.replaceChildren(...parts);
}

function onlyButton(id) {
  const button = el("button", "show only this", {
    type: "button",
    title: "Show only what this package holds (Back returns)",
  });
  button.onclick = () => isolate(id);
  return button;
}

function showEdge(element) {
  const details = $("details");
  const { source, target } = element.data();
  const cyclic = element.hasClass("cycle");
  const data = cyclic
    ? view.cycles.find((c) => c.a === source && c.b === target)
    : view.links.find((l) => l.source === source && l.target === target);
  const heading = el("h3");
  heading.append(link(source), document.createTextNode(cyclic ? " ⇄ " : " → "), link(target));
  const parts = [heading];
  if (cyclic) parts.push(el("p", "a dependency cycle", { className: "hint" }));
  else if (data.cyclic) parts.push(el("p", "on a longer cycle", { className: "hint" }));
  if (Object.keys(data.metrics).length) parts.push(el("h4", "metrics"), metricTable(data.metrics));
  parts.push(el("h4", `imports (${data.imports.length})`));
  const ul = el("ul");
  data.imports.forEach(([importer, imported]) => ul.append(el("li", `${importer} → ${imported}`)));
  parts.push(ul);
  details.replaceChildren(...parts);
}

// --- navigation and search ----------------------------------------------------

/** Focus ``id``: on the canvas if drawn, else unfold what hides it first. */
function goTo(id) {
  const target = cy.getElementById(id);
  if (target.nonempty()) {
    focusOn(target);
    renderTree();
    return;
  }
  if (state.links === "module" && [...state.folded].some((f) => isUnder(id, f))) {
    reveal(id);
    state.focus = id;
    refresh();
    return;
  }
  showError(`${id} is not on the graph — tick it in the tree to show it`);
}

function search(text, go) {
  cy.nodes().removeClass("match");
  const needle = text.trim().toLowerCase();
  if (!needle) return;
  const matches = cy.nodes().filter((n) => !n.hasClass("frame") && n.id().toLowerCase().includes(needle));
  matches.addClass("match");
  if (!go) return;
  if (matches.nonempty()) {
    focusOn(matches[0]);
    return;
  }
  const hidden = [...tree.keys()].find((id) => id.toLowerCase().includes(needle));
  if (hidden) goTo(hidden);
  else showError(`no module matches ${JSON.stringify(text)}`);
}

$("search").addEventListener("input", (event) => search(event.target.value, false));
$("search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") search(event.target.value, true);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    clearFocus();
    state.focus = null;
    writeUrl();
    showHelp();
    renderTree();
  }
});

$("links").addEventListener("change", (event) => {
  state.links = event.target.value;
  state.focus = null;
  refresh();
});

$("metric").addEventListener("change", (event) => {
  state.metric = event.target.value;
  refresh();
});

$("fit").addEventListener("click", () => cy.fit(undefined, 30));
$("show-all").addEventListener("click", showAll);

$("auto-redraw").checked = autoRedraw;
$("auto-redraw").addEventListener("change", (event) => {
  autoRedraw = event.target.checked;
  writeAutoRedraw(autoRedraw);
  if (autoRedraw && pending) redraw();
});
$("redraw").addEventListener("click", redraw);
$("select-all").addEventListener("click", () => {
  state.patterns = roots.map((r) => `${r}.**`);
  roots.forEach(openOneLevel);
  selectionChanged();
});
$("select-none").addEventListener("click", () => {
  state.patterns = [];
  selectionChanged();
});

$("copy-cli").addEventListener("click", async () => {
  if (!view) return;
  $("cli-text").textContent = view.cli;
  try {
    await navigator.clipboard.writeText(view.cli);
    $("copy-cli").textContent = "✓ copied";
    setTimeout(() => {
      $("copy-cli").textContent = "⧉ CLI command";
    }, 1500);
  } catch {
    $("cli-dialog").showModal();
  }
});

// --- start ------------------------------------------------------------------

readUrl();
try {
  await loadTree();
  roots.forEach((r) => expanded.add(r));
  renderTree();
  await refresh();
} catch (error) {
  showError(error.message);
}

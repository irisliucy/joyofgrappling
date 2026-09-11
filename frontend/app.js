// Same-origin API when served by the FastAPI app; null (static/GitHub Pages
// mode, no live API) when opened directly as a file:// page.
const API_BASE = window.location.protocol.startsWith("http") ? "" : null;

const CATEGORY_COLORS = {
  guard: "#4f8cff",
  submission: "#ff5c5c",
  top_control: "#f5a623",
  back_control: "#9b6bff",
  mount: "#ff8dc7",
  leglock: "#2ecc71",
  transition: "#8b93a1",
  takedown: "#20c0d8",
};

// Edge color encodes stage (entry/transition/result -- what the user asked
// to visually split the graph by); dash/width encodes confidence instead.
const STAGE_COLORS = {
  entry: "#ffffff",
  transition: "#ff3b3b",
  result: "#a80000",
};
const STAGE_LABELS = {
  entry: "Entry",
  transition: "Transition (solving a problem)",
  result: "Result (submission / sweep / pass → control)",
};
const CONTESTED_COLOR = "#00e5ff"; // distinct from the white/red stage palette

const CONFIDENCE_LINE = {
  established: { width: 4, dashes: false },
  emerging: { width: 3, dashes: false },
  contested: { width: 3, dashes: [4, 4] },
  signature: { width: 1, dashes: [2, 4] },
  unverified: { width: 1, dashes: [1, 3] },
};

const HIGHLIGHT_COLOR = "#ffd54a";
const DIM_NODE_COLOR = "#2a2f3a";
const DIM_EDGE_COLOR = "#333844";

const form = document.getElementById("research-form");
const statusEl = document.getElementById("status");
const results = document.getElementById("results");
let network = null;
let nodesDataSet = null;
let edgesDataSet = null;
let nodeOriginalStyle = new Map();
let edgeOriginalStyle = new Map();
let currentInsights = [];
let insightIdxByEdgeId = new Map();
let insightIdxsByNodeId = new Map(); // node id -> array of insight indices

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = document.getElementById("query-input").value.trim();
  const player = document.getElementById("player-input").value.trim();
  if (!query) return;

  if (!API_BASE) {
    setStatus("No live backend reachable from this page — this is a static export. Run the local server to start new research.");
    return;
  }

  setStatus(`Starting research on "${query}"...`);
  const resp = await fetch(`${API_BASE}/api/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, target_player: player || null }),
  });
  const { query_id } = await resp.json();
  pollJob(query_id);
});

function setStatus(text) {
  statusEl.hidden = false;
  statusEl.textContent = text;
}

async function pollJob(queryId) {
  const resp = await fetch(`${API_BASE}/api/jobs/${queryId}`);
  const job = await resp.json();
  setStatus(`[${job.status}] ${job.progress || ""}`);

  if (job.status === "done" || job.status === "error") {
    if (job.has_output) {
      const outResp = await fetch(`${API_BASE}/api/output/${queryId}`);
      renderOutput(await outResp.json());
    }
    return;
  }
  setTimeout(() => pollJob(queryId), 2000);
}

function renderOutput(output) {
  results.hidden = false;
  renderLegend();
  renderGraph(output.graph);
  renderInsights(output.insights);
  renderContested(output.contested);
  renderSources(output.sources_used);
}

function renderLegend() {
  const legend = document.getElementById("legend");
  legend.innerHTML = Object.entries(CATEGORY_COLORS)
    .map(([cat, color]) => `<span class="legend-item"><span class="dot" style="background:${color}"></span>${cat}</span>`)
    .join("");
}

function renderGraph(graph) {
  nodeOriginalStyle = new Map();
  edgeOriginalStyle = new Map();

  const nodeItems = graph.nodes.map((n) => {
    const item = {
      id: n.id,
      label: `${n.label}\n(${n.mention_count})`,
      color: { background: CATEGORY_COLORS[n.category] || CATEGORY_COLORS.transition, border: "#1a1d24" },
      borderWidth: 2,
      shape: "dot",
      size: 10 + Math.min(n.source_count * 3, 30),
      font: { color: "#e8eaed" },
    };
    nodeOriginalStyle.set(n.id, { color: item.color, borderWidth: item.borderWidth });
    return item;
  });

  const edgeItems = graph.edges.map((e) => {
    const line = CONFIDENCE_LINE[e.confidence_label] || CONFIDENCE_LINE.unverified;
    const color = e.confidence_label === "contested" ? CONTESTED_COLOR : (STAGE_COLORS[e.stage] || STAGE_COLORS.transition);
    const item = {
      id: e.id,
      from: e.from,
      to: e.to,
      label: e.transition_type,
      width: line.width,
      dashes: line.dashes,
      color: { color },
      arrows: "to",
      font: { color: "#9aa3af", size: 10, strokeWidth: 0 },
      title: `${e.stage} · ${e.confidence_label}${e.has_competition_footage ? " · competition-verified" : ""}`,
      stage: e.stage,
    };
    edgeOriginalStyle.set(e.id, { color: item.color, width: item.width });
    return item;
  });

  nodesDataSet = new vis.DataSet(nodeItems);
  edgesDataSet = new vis.DataSet(edgeItems);

  const container = document.getElementById("mindmap");
  const data = { nodes: nodesDataSet, edges: edgesDataSet };
  const options = {
    physics: { stabilization: true, barnesHut: { gravitationalConstant: -8000 } },
    interaction: { hover: true },
    layout: { randomSeed: 42 }, // pinned so the same data always lays out the same way
  };
  if (network) network.destroy();
  network = new vis.Network(container, data, options);
  network.on("click", onGraphClick);

  renderStageFilter();
  document.getElementById("graph-stats").textContent =
    `${nodeItems.length} nodes · ${edgeItems.length} edges`;
}

function renderStageFilter() {
  const container = document.getElementById("stage-filter");
  container.innerHTML = Object.entries(STAGE_LABELS)
    .map(
      ([stage, label]) => `
        <label class="stage-check">
          <input type="checkbox" data-stage="${stage}" checked />
          <span class="dot" style="background:${STAGE_COLORS[stage]}"></span>${label}
        </label>`
    )
    .join("");

  container.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", applyStageFilter);
  });
}

const FILTERED_OUT_OPACITY = 0.06;

function applyStageFilter() {
  if (!edgesDataSet || !nodesDataSet) return;
  const checked = new Set(
    Array.from(document.querySelectorAll("#stage-filter input:checked")).map((cb) => cb.dataset.stage)
  );

  const activeNodeIds = new Set();
  edgesDataSet.forEach((edge) => {
    const isActive = checked.has(edge.stage);
    const original = edgeOriginalStyle.get(edge.id);
    edgesDataSet.update({
      id: edge.id,
      color: { color: original.color.color, opacity: isActive ? 1 : FILTERED_OUT_OPACITY },
      width: isActive ? original.width : 1,
    });
    if (isActive) {
      activeNodeIds.add(edge.from);
      activeNodeIds.add(edge.to);
    }
  });

  nodesDataSet.forEach((node) => {
    nodesDataSet.update({ id: node.id, opacity: activeNodeIds.has(node.id) ? 1 : FILTERED_OUT_OPACITY });
  });
}

function highlightGraphForInsight(insight) {
  if (!nodesDataSet || !edgesDataSet) return;
  const relevantNodeIds = new Set([insight.from_node_id, insight.to_node_id].filter(Boolean));
  const relevantEdgeId = insight.graph_edge_id;

  nodesDataSet.forEach((node) => {
    if (relevantNodeIds.has(node.id)) {
      const original = nodeOriginalStyle.get(node.id);
      nodesDataSet.update({
        id: node.id,
        color: { background: original.color.background, border: HIGHLIGHT_COLOR },
        borderWidth: 4,
      });
    } else {
      nodesDataSet.update({ id: node.id, color: { background: DIM_NODE_COLOR, border: DIM_NODE_COLOR }, borderWidth: 1 });
    }
  });

  edgesDataSet.forEach((edge) => {
    if (edge.id === relevantEdgeId) {
      const original = edgeOriginalStyle.get(edge.id);
      edgesDataSet.update({ id: edge.id, color: { color: HIGHLIGHT_COLOR }, width: original.width + 2 });
    } else {
      edgesDataSet.update({ id: edge.id, color: { color: DIM_EDGE_COLOR }, width: 1 });
    }
  });
}

function clearGraphHighlight() {
  if (!nodesDataSet || !edgesDataSet) return;
  nodesDataSet.forEach((node) => {
    const original = nodeOriginalStyle.get(node.id);
    if (original) nodesDataSet.update({ id: node.id, color: original.color, borderWidth: original.borderWidth });
  });
  edgesDataSet.forEach((edge) => {
    const original = edgeOriginalStyle.get(edge.id);
    if (original) edgesDataSet.update({ id: edge.id, color: original.color, width: original.width });
  });
}

// Clicking an insight "pins" its highlight (so it survives hovering over
// other insights afterward) and zooms the graph viewport to just its nodes.
// Clicking the same insight again un-pins and zooms back out.
let pinnedInsightIdx = null;

function selectInsightOnGraph(idx, insight) {
  document.querySelectorAll("#insights-list li.insight-selected").forEach((li) => li.classList.remove("insight-selected"));

  if (pinnedInsightIdx === idx) {
    pinnedInsightIdx = null;
    clearGraphHighlight();
    if (network) network.fit({ animation: { duration: 500, easingFunction: "easeInOutQuad" } });
    return;
  }

  pinnedInsightIdx = idx;
  const li = document.getElementById(`insight-${idx}`);
  if (li) li.classList.add("insight-selected");
  highlightGraphForInsight(insight);

  if (network) {
    const nodeIds = [insight.from_node_id, insight.to_node_id].filter(Boolean);
    if (nodeIds.length) {
      network.fit({ nodes: nodeIds, animation: { duration: 500, easingFunction: "easeInOutQuad" } });
    }
  }
}

function renderInsights(insights) {
  const list = document.getElementById("insights-list");
  list.innerHTML = "";
  currentInsights = insights;
  insightIdxByEdgeId = new Map();
  insightIdxsByNodeId = new Map();

  if (!insights.length) {
    list.innerHTML = "<li class=\"muted\">No insights extracted yet.</li>";
    return;
  }

  insights.forEach((insight, idx) => {
    if (insight.graph_edge_id) insightIdxByEdgeId.set(insight.graph_edge_id, idx);
    for (const nodeId of [insight.from_node_id, insight.to_node_id]) {
      if (!nodeId) continue;
      if (!insightIdxsByNodeId.has(nodeId)) insightIdxsByNodeId.set(nodeId, []);
      insightIdxsByNodeId.get(nodeId).push(idx);
    }

    const li = document.createElement("li");
    li.id = `insight-${idx}`;
    li.addEventListener("mouseenter", () => highlightGraphForInsight(insight));
    li.addEventListener("mouseleave", () => {
      if (pinnedInsightIdx !== null) {
        highlightGraphForInsight(currentInsights[pinnedInsightIdx]);
      } else {
        clearGraphHighlight();
      }
    });
    li.addEventListener("click", (e) => {
      if (e.target.closest(".watch-btn")) return; // let the watch button handle its own click
      selectInsightOnGraph(idx, insight);
    });

    const watchButtons = (insight.sources || [])
      .map(
        (s, sIdx) =>
          `<button class="watch-btn" data-insight="${idx}" data-source="${sIdx}">
             ▶ watch at ${formatTimestamp(s.timestamp_start)}
           </button>`
      )
      .join(" ");

    li.innerHTML = `
      <span class="badge badge-${insight.confidence_label}">${insight.confidence_label}</span>
      ${insight.text}
      <span class="muted"> — ${insight.source_count} source${insight.source_count === 1 ? "" : "s"}</span>
      <div class="watch-row">${watchButtons}</div>
      <div class="player-slot" id="player-${idx}"></div>
    `;
    list.appendChild(li);
  });

  list.querySelectorAll(".watch-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const insightIdx = btn.dataset.insight;
      const sourceIdx = Number(btn.dataset.source);
      const source = insights[insightIdx].sources[sourceIdx];
      togglePlayer(`player-${insightIdx}`, source);
    });
  });
}

function formatTimestamp(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}

function togglePlayer(slotId, source) {
  const slot = document.getElementById(slotId);
  if (slot.dataset.open === "true") {
    slot.innerHTML = "";
    slot.dataset.open = "false";
    return;
  }
  openPlayer(slotId, source);
}

function openPlayer(slotId, source) {
  const slot = document.getElementById(slotId);
  if (slot.dataset.open === "true") return; // already open, leave it
  const start = Math.max(0, Math.floor(source.timestamp_start || 0));
  const embedUrl = `https://www.youtube.com/embed/${source.video_id}?start=${start}&autoplay=1`;
  slot.innerHTML = `
    <div class="player-wrap">
      <iframe src="${embedUrl}" title="${source.channel_name}" frameborder="0"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
        allowfullscreen></iframe>
    </div>
    <div class="quote">"${source.raw_quote}"</div>
  `;
  slot.dataset.open = "true";
}

// Clicking a node/edge in the graph jumps to and highlights the matching
// insight(s) in the list; clicking an edge also opens its video at the
// exact timestamp.
function onGraphClick(params) {
  document.querySelectorAll("#insights-list li.insight-selected").forEach((li) => li.classList.remove("insight-selected"));

  let indices = [];
  if (params.edges.length > 0) {
    const idx = insightIdxByEdgeId.get(params.edges[0]);
    if (idx !== undefined) indices = [idx];
  } else if (params.nodes.length > 0) {
    indices = insightIdxsByNodeId.get(params.nodes[0]) || [];
  } else {
    pinnedInsightIdx = null;
    clearGraphHighlight();
    return; // clicked empty canvas -- just clear selection
  }

  indices.forEach((idx, i) => {
    const li = document.getElementById(`insight-${idx}`);
    if (!li) return;
    li.classList.add("insight-selected");
    if (i === 0) li.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  if (params.edges.length > 0 && indices.length > 0) {
    const insight = currentInsights[indices[0]];
    if (insight.sources && insight.sources.length > 0) {
      openPlayer(`player-${indices[0]}`, insight.sources[0]);
    }
  }
}

function renderContested(contested) {
  const list = document.getElementById("contested-list");
  list.innerHTML = contested
    .map(
      (c) => `<li><strong>${c.technique}</strong>: ${c.point_of_disagreement}<br/>
        <span class="muted">A: ${c.side_a}</span><br/>
        <span class="muted">B: ${c.side_b}</span></li>`
    )
    .join("") || "<li class=\"muted\">Nothing contested.</li>";
}

function renderSources(sources) {
  const list = document.getElementById("sources-list");
  list.innerHTML = sources
    .map(
      (s) =>
        `<li><a href="${s.video_url}" target="_blank" rel="noopener">${s.channel_name}</a>
          <span class="muted">(tier ${s.authority_tier}${s.is_competition_footage ? ", competition" : ""})</span></li>`
    )
    .join("");
}

// Static (GitHub Pages) mode: if a ?export=<id> param is present, load it directly.
const params = new URLSearchParams(window.location.search);
const exportId = params.get("export");
if (exportId) {
  fetch(`./exports/${exportId}/output.json`)
    .then((r) => r.json())
    .then(renderOutput);
}

// Live mode: ?job=<id> loads an existing result straight from the running API.
const jobId = params.get("job");
if (jobId && API_BASE !== null) {
  fetch(`${API_BASE}/api/output/${jobId}`)
    .then((r) => r.json())
    .then(renderOutput);
}

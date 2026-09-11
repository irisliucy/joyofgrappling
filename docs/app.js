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

const CONFIDENCE_STYLE = {
  established: { width: 4, dashes: false, color: "#e8eaed" },
  emerging: { width: 3, dashes: false, color: "#4f8cff" },
  contested: { width: 3, dashes: [4, 4], color: "#ff5c5c" },
  signature: { width: 1, dashes: [2, 4], color: "#8b93a1" },
  unverified: { width: 1, dashes: [1, 3], color: "#5a616e" },
};

const form = document.getElementById("research-form");
const statusEl = document.getElementById("status");
const results = document.getElementById("results");
let network = null;

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
  const nodes = new vis.DataSet(
    graph.nodes.map((n) => ({
      id: n.id,
      label: `${n.label}\n(${n.mention_count})`,
      color: CATEGORY_COLORS[n.category] || CATEGORY_COLORS.transition,
      shape: "dot",
      size: 10 + Math.min(n.source_count * 3, 30),
      font: { color: "#e8eaed" },
    }))
  );

  const edges = new vis.DataSet(
    graph.edges.map((e) => {
      const style = CONFIDENCE_STYLE[e.confidence_label] || CONFIDENCE_STYLE.unverified;
      return {
        from: e.from,
        to: e.to,
        label: e.transition_type,
        width: style.width,
        dashes: style.dashes,
        color: { color: style.color },
        arrows: "to",
        font: { color: "#9aa3af", size: 10, strokeWidth: 0 },
        title: `${e.confidence_label}${e.has_competition_footage ? " · competition-verified" : ""}`,
      };
    })
  );

  const container = document.getElementById("mindmap");
  const data = { nodes, edges };
  const options = {
    physics: { stabilization: true, barnesHut: { gravitationalConstant: -8000 } },
    interaction: { hover: true },
  };
  if (network) network.destroy();
  network = new vis.Network(container, data, options);
}

function renderInsights(insights) {
  const list = document.getElementById("insights-list");
  list.innerHTML = insights
    .map(
      (i) => `<li><span class="badge badge-${i.confidence_label}">${i.confidence_label}</span> ${i.text}
        <span class="muted"> — ${i.source_count} source${i.source_count === 1 ? "" : "s"}</span></li>`
    )
    .join("") || "<li class=\"muted\">No insights extracted yet.</li>";
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

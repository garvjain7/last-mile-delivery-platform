const list = document.querySelector("#service-list");
const checkedAt = document.querySelector("#checked-at");
const refreshButton = document.querySelector("#refresh-status");
const overallStatus = document.querySelector("#overall-status");
const summaryCount = document.querySelector("#summary-count");

function renderServices(services) {
  list.replaceChildren(...services.map((service) => {
    const card = document.createElement("article");
    card.className = "service-card";

    const name = document.createElement("span");
    name.className = "service-name";
    name.textContent = service.name;

    const badge = document.createElement("span");
    badge.className = `badge badge-${service.status}`;
    badge.textContent = service.status;

    const detail = document.createElement("span");
    detail.className = "service-detail";
    detail.textContent = service.detail;

    card.append(name, badge, detail);
    return card;
  }));
}

async function checkStatus() {
  refreshButton.disabled = true;
  list.setAttribute("aria-busy", "true");
  checkedAt.textContent = "Checking services…";
  try {
    const response = await fetch("/status/data", { cache: "no-store" });
    if (!response.ok) throw new Error(`Status request returned ${response.status}`);
    const result = await response.json();
    renderServices(result.services);
    const active = result.services.filter((service) => service.status === "active").length;
    const failed = result.services.filter((service) => service.status === "failed").length;
    const inactive = result.services.filter((service) => service.status === "inactive").length;
    const needsAttention = failed > 0 || inactive > 0;
    overallStatus.textContent = failed > 0 ? "Service failure" : needsAttention ? "Degraded" : "Operational";
    overallStatus.className = `overall-status${failed > 0 ? " outage" : needsAttention ? " degraded" : ""}`;
    summaryCount.textContent = `${active} active · ${inactive} inactive · ${failed} failed · ${result.services.length} total`;
    checkedAt.textContent = `Snapshot generated at ${new Date(result.checked_at).toLocaleString()}`;
  } catch {
    list.replaceChildren();
    overallStatus.textContent = "Status unavailable";
    overallStatus.className = "overall-status outage";
    summaryCount.textContent = "The status endpoint did not return a snapshot.";
    checkedAt.textContent = "Could not load service status. Try again.";
  } finally {
    refreshButton.disabled = false;
    list.setAttribute("aria-busy", "false");
  }
}

refreshButton.addEventListener("click", checkStatus);
checkStatus();

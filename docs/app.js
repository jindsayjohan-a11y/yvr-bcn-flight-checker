const CAD = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  maximumFractionDigits: 0,
});

const CABIN_LABELS = {
  economy: "Economy",
  "premium-economy": "Premium economy",
  business: "Business",
};

const FLIGHT_COLORS = {
  economy: "#0f7a8a",
  "premium-economy": "#d97706",
  business: "#7c3aed",
};

const HOTEL_COLORS = {
  "pre-cruise": "#0f7a8a",
  "post-cruise": "#d97706",
};

function money(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return CAD.format(Number(value));
}

function parseTs(text) {
  if (!text) return null;
  const normalized = String(text).replace(" UTC", "Z").replace(" ", "T");
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

function shortWhen(text) {
  const d = parseTs(text);
  if (!d) return text || "—";
  return d.toLocaleString("en-CA", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function drawSeries(canvas, seriesMap, colors) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 600;
  const cssH = Number(canvas.getAttribute("height") || 160);
  canvas.width = Math.floor(cssW * dpr);
  canvas.height = Math.floor(cssH * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const entries = Object.entries(seriesMap)
    .map(([key, points]) => [
      key,
      (points || []).filter((p) => p && p[1] != null),
    ])
    .filter(([, points]) => points.length > 0);

  if (!entries.length) {
    ctx.fillStyle = "#6b8490";
    ctx.font = "500 14px Manrope, sans-serif";
    ctx.fillText("No priced points to chart yet", 8, cssH / 2);
    return;
  }

  const all = entries.flatMap(([, pts]) => pts);
  const times = all.map((p) => parseTs(p[0])?.getTime()).filter(Boolean);
  const prices = all.map((p) => Number(p[1]));
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const padX = 8;
  const padY = 16;
  const spanT = Math.max(maxT - minT, 1);
  const spanP = Math.max(maxP - minP, 1);

  ctx.strokeStyle = "rgba(16,42,54,0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i++) {
    const y = padY + ((cssH - padY * 2) * i) / 3;
    ctx.beginPath();
    ctx.moveTo(padX, y);
    ctx.lineTo(cssW - padX, y);
    ctx.stroke();
  }

  for (const [key, pts] of entries) {
    const sorted = [...pts].sort(
      (a, b) => (parseTs(a[0])?.getTime() || 0) - (parseTs(b[0])?.getTime() || 0)
    );
    ctx.strokeStyle = colors[key] || "#0f7a8a";
    ctx.lineWidth = 2.25;
    ctx.lineJoin = "round";
    ctx.beginPath();
    sorted.forEach((p, i) => {
      const t = parseTs(p[0])?.getTime() || minT;
      const x = padX + ((t - minT) / spanT) * (cssW - padX * 2);
      const y =
        cssH - padY - ((Number(p[1]) - minP) / spanP) * (cssH - padY * 2);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }
}

function legend(rootId, keys, colors, labels) {
  const root = document.getElementById(rootId);
  root.innerHTML = keys
    .map(
      (k) =>
        `<span><i class="swatch" style="background:${colors[k]}"></i>${
          labels[k] || k
        }</span>`
    )
    .join("");
}

function renderFlightStats(data) {
  const root = document.getElementById("flight-stats");
  const empty = document.getElementById("flight-empty");
  root.innerHTML = "";
  const thresholds = data.thresholds || {};
  const latest = data.latest || {};
  let any = false;
  for (const cabin of ["economy", "premium-economy", "business"]) {
    const row = latest[cabin];
    const price = row?.price;
    const threshold = thresholds[cabin];
    any = any || price != null;
    const under = price != null && threshold != null && price <= threshold;
    root.appendChild(
      el(`
      <article class="stat ${price == null ? "missing" : under ? "alert" : ""}">
        <p class="label">${CABIN_LABELS[cabin]}</p>
        <p class="value">${price == null ? "No fare yet" : money(price)}</p>
        <p class="meta">Alert ≤ ${money(threshold)}${
          row?.outbound ? ` · depart ${row.outbound}` : ""
        }</p>
      </article>`)
    );
  }
  empty.hidden = any;
}

function renderHotelStats(data) {
  const root = document.getElementById("hotel-stats");
  root.innerHTML = "";
  const threshold = data.threshold ?? 200;
  for (const stay of data.latest || []) {
    const price = stay.price_per_night;
    const under = stay.bookable && price != null && price <= threshold;
    const book =
      stay.booking_links?.ota ||
      stay.booking_links?.google_hotels ||
      stay.booking_links?.booking_com;
    const note = !stay.found
      ? stay.note || "No priced stay"
      : !stay.bookable
        ? "Listed but not verified bookable"
        : stay.name || "Hotel";
    root.appendChild(
      el(`
      <article class="stat ${price == null ? "missing" : under ? "alert" : ""}">
        <p class="label">${stay.label || stay.id}</p>
        <p class="value">${
          price == null
            ? "—"
            : `${money(price)}<span style="font-size:.55em">/n</span>`
        }</p>
        <p class="meta">${note}${stay.stars ? ` · ${stay.stars}★` : ""}${
          stay.km_from_center != null ? ` · ${stay.km_from_center} km` : ""
        }</p>
        ${
          book
            ? `<p class="meta book"><a href="${book}" target="_blank" rel="noopener">Open bookable link</a></p>`
            : ""
        }
      </article>`)
    );
  }
}

function renderSkyStats(data) {
  const root = document.getElementById("sky-stats");
  const empty = document.getElementById("sky-empty");
  root.innerHTML = "";
  if (!data.enabled) {
    empty.hidden = false;
    empty.textContent =
      data.note ||
      "Skyscanner needs RAPIDAPI_KEY before daily scans appear here.";
    return;
  }
  empty.hidden = true;
  const thresholds = data.thresholds || {};
  const latest = data.latest || {};
  for (const cabin of ["economy", "premium-economy", "business"]) {
    const row = latest[cabin];
    const price = row?.price;
    const threshold = thresholds[cabin];
    const under = price != null && threshold != null && price <= threshold;
    root.appendChild(
      el(`
      <article class="stat ${price == null ? "missing" : under ? "alert" : ""}">
        <p class="label">${CABIN_LABELS[cabin]}</p>
        <p class="value">${price == null ? "No fare yet" : money(price)}</p>
        <p class="meta">Alert ≤ ${money(threshold)}</p>
      </article>`)
    );
  }
}

async function main() {
  const res = await fetch("./data.json", { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load data.json (${res.status})`);
  const data = await res.json();

  document.getElementById("hero-meta").innerHTML = `
    <span class="dot" aria-hidden="true"></span>
    <span>Site data built ${shortWhen(data.generated_at)}</span>
    <span>·</span>
    <span>${data.flights?.scan_count ?? 0} flight scans · ${
      data.hotels?.scan_count ?? 0
    } hotel scans</span>
  `;

  document.getElementById("flight-sub").textContent =
    data.trip?.flights || "Outbound Jul 9–12 · Return Jul 25";
  document.getElementById("flight-checked").textContent = data.flights
    ?.checked_at
    ? `Checked ${shortWhen(data.flights.checked_at)}`
    : "No flight checks yet";
  document.getElementById("hotel-checked").textContent = data.hotels?.checked_at
    ? `Checked ${shortWhen(data.hotels.checked_at)}`
    : "No hotel checks yet";
  document.getElementById("sky-checked").textContent = data.skyscanner
    ?.checked_at
    ? `Checked ${shortWhen(data.skyscanner.checked_at)}`
    : "Daily · waiting for API key";

  renderFlightStats(data.flights || {});
  renderHotelStats(data.hotels || {});
  renderSkyStats(data.skyscanner || {});

  const flightKeys = Object.keys(data.flights?.series || {}).filter(
    (k) => (data.flights.series[k] || []).length
  );
  legend("flight-legend", flightKeys, FLIGHT_COLORS, CABIN_LABELS);
  drawSeries(
    document.getElementById("flight-chart"),
    data.flights?.series || {},
    FLIGHT_COLORS
  );

  const hotelKeys = Object.keys(data.hotels?.series || {}).filter(
    (k) => (data.hotels.series[k] || []).length
  );
  legend("hotel-legend", hotelKeys, HOTEL_COLORS, {
    "pre-cruise": "Pre-cruise",
    "post-cruise": "Post-cruise",
  });
  const hotelSeries = {};
  for (const [k, pts] of Object.entries(data.hotels?.series || {})) {
    const bookable = (pts || []).filter((p) => p[3] !== false);
    hotelSeries[k] = bookable.length ? bookable : pts;
  }
  drawSeries(document.getElementById("hotel-chart"), hotelSeries, HOTEL_COLORS);
}

main().catch((err) => {
  document.getElementById("hero-meta").textContent = String(err.message || err);
});

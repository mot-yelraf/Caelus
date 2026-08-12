(function () {
  const dialog = document.getElementById("settingsDialog");
  const form = document.getElementById("settingsForm");
  if (!dialog || !form) return;

  const body = document.body;
  const themeInputs = Array.from(form.querySelectorAll('input[name="theme"]'));
  const tabs = Array.from(dialog.querySelectorAll("[data-settings-pane]"));
  const panes = Array.from(dialog.querySelectorAll("[data-pane]"));
  const settingsStatus = form.querySelector("[data-settings-status]");
  let originalTheme = themeInputs.find((input) => input.checked)?.value || "garden";

  function applyTheme(theme) {
    Array.from(body.classList)
      .filter((name) => name.startsWith("theme-"))
      .forEach((name) => body.classList.remove(name));
    body.classList.add(`theme-${theme}`);
  }

  function activatePane(name, focusTab) {
    tabs.forEach((tab) => {
      const active = tab.dataset.settingsPane === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      if (active && focusTab) tab.focus();
    });
    panes.forEach((pane) => {
      const active = pane.dataset.pane === name;
      pane.classList.toggle("is-active", active);
      pane.hidden = !active;
    });
  }

  function openSettings() {
    originalTheme = themeInputs.find((input) => input.checked)?.value || "garden";
    dialog.showModal();
    body.classList.add("modal-open");
    activatePane("station", false);
  }

  function closeSettings(restoreTheme) {
    if (restoreTheme) applyTheme(originalTheme);
    dialog.close();
    body.classList.remove("modal-open");
  }

  document.querySelectorAll("[data-open-settings]").forEach((button) => {
    button.addEventListener("click", openSettings);
  });
  dialog.querySelectorAll("[data-close-settings]").forEach((button) => {
    button.addEventListener("click", () => closeSettings(true));
  });
  tabs.forEach((tab, index) => {
    const paneName = tab.dataset.settingsPane;
    const pane = panes.find((item) => item.dataset.pane === paneName);
    tab.id = `settings-tab-${paneName}`;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", `settings-pane-${paneName}`);
    if (pane) {
      pane.id = `settings-pane-${paneName}`;
      pane.setAttribute("role", "tabpanel");
      pane.setAttribute("aria-labelledby", tab.id);
    }
    tab.addEventListener("click", () => activatePane(tab.dataset.settingsPane, false));
    tab.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      const next = (index + direction + tabs.length) % tabs.length;
      activatePane(tabs[next].dataset.settingsPane, true);
    });
  });
  themeInputs.forEach((input) => {
    input.addEventListener("change", () => applyTheme(input.value));
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeSettings(true);
  });
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    const inside = event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
    if (!inside) closeSettings(true);
  });
  form.addEventListener("invalid", (event) => {
    const pane = event.target.closest("[data-pane]");
    if (pane) activatePane(pane.dataset.pane, false);
    if (settingsStatus) {
      const fieldName = event.target.closest("label")?.querySelector("span")?.textContent || "highlighted field";
      settingsStatus.textContent = `Check the ${fieldName.toLowerCase()} before saving.`;
      settingsStatus.classList.add("is-error");
    }
  }, true);
  async function savePane(paneName, saveButton) {
    const pane = panes.find((item) => item.dataset.pane === paneName);
    if (!pane) return;
    const controls = Array.from(pane.querySelectorAll("input, select, textarea"));
    const invalidControl = controls.find((control) => !control.checkValidity());
    if (invalidControl) {
      activatePane(paneName, false);
      invalidControl.reportValidity();
      return;
    }

    const formData = new FormData();
    formData.append("csrf_token", form.querySelector('input[name="csrf_token"]')?.value || "");
    formData.append("settings_pane", paneName);
    controls.forEach((control) => {
      if (!control.name || control.disabled) return;
      if (control.type === "radio" && !control.checked) return;
      if (control.type === "checkbox") {
        formData.append(control.name, control.checked ? "true" : "false");
        return;
      }
      formData.append(control.name, control.value);
    });

    const originalLabel = saveButton.textContent;
    saveButton.disabled = true;
    saveButton.textContent = "Saving…";
    if (settingsStatus) {
      settingsStatus.textContent = `Saving ${paneName.replace("-", " & ")} settings…`;
      settingsStatus.classList.remove("is-error");
    }
    try {
      const response = await fetch(form.action, {method: "POST", body: formData});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) {
        throw new Error(payload.detail || `Settings could not be saved (${response.status})`);
      }
      if (paneName === "appearance") {
        originalTheme = themeInputs.find((input) => input.checked)?.value || originalTheme;
      }
      if (settingsStatus) settingsStatus.textContent = `${originalLabel.replace("Save ", "")} saved.`;
      if (paneName === "station") {
        setDashboardRefreshInterval(Number(ecowittInterval?.value));
      }
    } catch (error) {
      if (settingsStatus) {
        settingsStatus.textContent = error.message || "Settings could not be saved.";
        settingsStatus.classList.add("is-error");
      }
    } finally {
      saveButton.disabled = false;
      saveButton.textContent = originalLabel;
    }
  }

  form.querySelectorAll("[data-save-pane]").forEach((button) => {
    button.addEventListener("click", () => savePane(button.dataset.savePane, button));
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const activePane = panes.find((pane) => pane.classList.contains("is-active"));
    activePane?.querySelector("[data-save-pane]")?.click();
  });

  const ecowittUrl = document.getElementById("ecowittGatewayUrl");
  const ecowittInterval = document.getElementById("ecowittPollInterval");
  const ecowittStatus = form.querySelector("[data-ecowitt-status]");
  const ecowittInventory = form.querySelector("[data-ecowitt-inventory]");
  const ecowittDiscoverButton = form.querySelector("[data-ecowitt-discover]");
  const ecowittSaveButton = form.querySelector("[data-ecowitt-save]");
  const ecowittDisableButton = form.querySelector("[data-ecowitt-disable]");
  const csrfToken = form.querySelector('input[name="csrf_token"]')?.value || "";
  let ecowittDiscovery = null;

  function renderEcowittInventory(inventory) {
    if (!ecowittInventory) return;
    ecowittInventory.replaceChildren();
    (Array.isArray(inventory) ? inventory : []).forEach((sensor) => {
      const row = document.createElement("div");
      const name = document.createElement("strong");
      const detail = document.createElement("span");
      name.textContent = sensor.name || "Ecowitt sensor";
      detail.textContent = `${sensor.family || "Ecowitt"} · ID ${sensor.id || "unknown"} · ${sensor.reporting === false ? "not reporting" : `signal ${sensor.signal ?? "—"}`}`;
      row.append(name, detail);
      ecowittInventory.append(row);
    });
  }

  async function ecowittRequest(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...body, csrf_token: csrfToken}),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || payload.detail || `Ecowitt request failed (${response.status})`);
    }
    return payload;
  }

  ecowittDiscoverButton?.addEventListener("click", async () => {
    ecowittDiscoverButton.disabled = true;
    ecowittSaveButton.disabled = true;
    if (ecowittStatus) ecowittStatus.textContent = "Querying the Ecowitt gateway…";
    try {
      ecowittDiscovery = await ecowittRequest("/api/ecowitt/discover", {gateway_url: ecowittUrl.value});
      renderEcowittInventory(ecowittDiscovery.inventory);
      if (ecowittStatus) ecowittStatus.textContent = `${ecowittDiscovery.gateway_model}: ${ecowittDiscovery.inventory.length} registered sensor(s), ${ecowittDiscovery.live_metric_count} live metric(s).`;
      ecowittSaveButton.disabled = false;
    } catch (error) {
      ecowittDiscovery = null;
      renderEcowittInventory([]);
      if (ecowittStatus) ecowittStatus.textContent = error.message || "Gateway discovery failed.";
    } finally {
      ecowittDiscoverButton.disabled = false;
    }
  });

  ecowittSaveButton?.addEventListener("click", async () => {
    if (!ecowittDiscovery) return;
    ecowittSaveButton.disabled = true;
    if (ecowittStatus) ecowittStatus.textContent = "Validating and saving the gateway…";
    try {
      const result = await ecowittRequest("/api/ecowitt/save", {
        gateway_url: ecowittUrl.value,
        poll_interval_seconds: Number(ecowittInterval.value),
      });
      renderEcowittInventory(result.inventory);
      if (ecowittStatus) ecowittStatus.textContent = `${result.gateway_model} saved; Ecowitt polling is enabled.`;
      setDashboardRefreshInterval(Number(result.poll_interval_seconds));
    } catch (error) {
      if (ecowittStatus) ecowittStatus.textContent = error.message || "Gateway could not be saved.";
      ecowittSaveButton.disabled = false;
    }
  });

  ecowittDisableButton?.addEventListener("click", async () => {
    ecowittDisableButton.disabled = true;
    try {
      await ecowittRequest("/api/ecowitt/disable", {});
      if (ecowittStatus) ecowittStatus.textContent = "Ecowitt polling disabled; historical SQLite readings were retained.";
    } catch (error) {
      if (ecowittStatus) ecowittStatus.textContent = error.message || "Gateway could not be disabled.";
    } finally {
      ecowittDisableButton.disabled = false;
    }
  });

  const forecastDialog = document.getElementById("forecastDialog");
  document.querySelectorAll("[data-open-forecast]").forEach((button) => {
    button.addEventListener("click", () => {
      forecastDialog?.showModal();
      body.classList.add("modal-open");
    });
  });
  forecastDialog?.querySelectorAll("[data-close-forecast]").forEach((button) => {
    button.addEventListener("click", () => forecastDialog.close());
  });
  forecastDialog?.addEventListener("close", () => body.classList.remove("modal-open"));
  forecastDialog?.addEventListener("click", (event) => {
    if (event.target === forecastDialog) forecastDialog.close();
  });

  document.querySelectorAll("[data-hourly-carousel]").forEach((carousel) => {
    const hours = Array.from(carousel.querySelectorAll("[data-hourly-index]"));
    const previousButton = carousel.querySelector("[data-hourly-previous]");
    const nextButton = carousel.querySelector("[data-hourly-next]");
    const status = carousel.parentElement?.querySelector("[data-hourly-status]");
    const pageSize = Number(carousel.dataset.pageSize) || 8;
    let pageStart = 0;

    function showPage() {
      const pageEnd = Math.min(pageStart + pageSize, hours.length);
      hours.forEach((hour, index) => {
        hour.hidden = index < pageStart || index >= pageEnd;
      });
      if (previousButton) previousButton.hidden = pageStart === 0;
      if (nextButton) nextButton.hidden = pageEnd >= hours.length;
      if (status) status.textContent = `Hours ${pageStart + 1}–${pageEnd} of ${hours.length}`;
    }

    previousButton?.addEventListener("click", () => {
      pageStart = Math.max(0, pageStart - 1);
      showPage();
    });
    nextButton?.addEventListener("click", () => {
      pageStart = Math.min(Math.max(0, hours.length - pageSize), pageStart + 1);
      showPage();
    });
    showPage();
  });

  const detectButton = dialog.querySelector("[data-detect-location]");
  const detectStatus = dialog.querySelector("[data-location-status]");
  if (detectButton) {
    detectButton.addEventListener("click", async () => {
      detectButton.disabled = true;
      if (detectStatus) detectStatus.textContent = "Finding approximate location…";
      try {
        const csrfToken = form.querySelector('input[name="csrf_token"]')?.value || "";
        const response = await fetch("/api/location/detect", {
          method: "POST",
          headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
          body: new URLSearchParams({csrf_token: csrfToken}).toString(),
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.reason || "Location detection failed");
        document.getElementById("locationLatitude").value = Number(payload.latitude).toFixed(4);
        document.getElementById("locationLongitude").value = Number(payload.longitude).toFixed(4);
        document.getElementById("locationTimezone").value = payload.timezone || "UTC";
        if (payload.location_name) document.getElementById("locationName").value = payload.location_name;
        document.getElementById("autoLocation").checked = true;
        if (detectStatus) detectStatus.textContent = `Located via ${payload.provider}. Save Settings to refresh the dashboard.`;
      } catch (error) {
        if (detectStatus) detectStatus.textContent = error.message || "Location detection failed";
      } finally {
        detectButton.disabled = false;
      }
    });
  }

  const moonSurfaceImage = new Image();
  const moonRenders = new Map();

  function renderMoonDisk(canvas, moon) {
    if (!canvas) return;
    moonRenders.set(canvas, moon);
    const context = canvas.getContext("2d");
    if (!context) return;

    const canonicalIllumination = [0, 15, 50, 85, 100, 85, 50, 15];
    const phaseIndex = Number(moon.index ?? canvas.dataset.phaseIndex);
    let illuminationPercent = Number(moon.illumination);
    if (!Number.isFinite(illuminationPercent)
      || (canvas.hasAttribute("data-phase-moon") && phaseIndex > 0 && illuminationPercent === 0)) {
      illuminationPercent = canonicalIllumination[phaseIndex] ?? 0;
    }
    const illumination = Math.max(0, Math.min(100, illuminationPercent)) / 100;
    const angle = Number(moon.bright_limb_angle || 0) * Math.PI / 180;
    const diskRotation = Number(moon.disk_rotation || 0) * Math.PI / 180;
    const rotationCosine = Math.cos(diskRotation);
    const rotationSine = Math.sin(diskRotation);
    const width = canvas.width;
    const height = canvas.height;
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width, height) * 0.455;
    const lightDepth = 2 * illumination - 1;
    const lightAcross = Math.sqrt(Math.max(0, 1 - lightDepth * lightDepth));
    const lightX = Math.sin(angle) * lightAcross;
    const lightY = Math.cos(angle) * lightAcross;
    const pixels = context.createImageData(width, height);
    let surfacePixels = null;
    if (moonSurfaceImage.complete && moonSurfaceImage.naturalWidth > 0) {
      const surfaceCanvas = document.createElement("canvas");
      surfaceCanvas.width = width;
      surfaceCanvas.height = height;
      const surfaceContext = surfaceCanvas.getContext("2d", {willReadFrequently: true});
      if (surfaceContext) {
        surfaceContext.drawImage(moonSurfaceImage, 0, 0, width, height);
        surfacePixels = surfaceContext.getImageData(0, 0, width, height).data;
      }
    }

    for (let pixelY = 0; pixelY < height; pixelY += 1) {
      for (let pixelX = 0; pixelX < width; pixelX += 1) {
        const x = (pixelX + 0.5 - centerX) / radius;
        const y = (centerY - pixelY - 0.5) / radius;
        const distanceSquared = x * x + y * y;
        if (distanceSquared > 1.025) continue;

        const z = Math.sqrt(Math.max(0, 1 - Math.min(1, distanceSquared)));
        const sunlight = x * lightX + y * lightY + z * lightDepth;
        const terminator = Math.max(0, Math.min(1, (sunlight + 0.018) / 0.036));
        const texture = 0.92 + 0.045 * Math.sin(pixelX * 0.31 + pixelY * 0.17)
          + 0.025 * Math.sin(pixelX * 0.08 - pixelY * 0.23);
        const index = (pixelY * width + pixelX) * 4;
        const textureX = rotationCosine * x - rotationSine * y;
        const textureY = rotationSine * x + rotationCosine * y;
        const sourceX = Math.max(0, Math.min(width - 1, Math.round(centerX + textureX * radius)));
        const sourceY = Math.max(0, Math.min(height - 1, Math.round(centerY - textureY * radius)));
        const sourceIndex = (sourceY * width + sourceX) * 4;
        const sourceRed = surfacePixels ? surfacePixels[sourceIndex] : Math.round(224 * texture);
        const sourceGreen = surfacePixels ? surfacePixels[sourceIndex + 1] : Math.round(211 * texture);
        const sourceBlue = surfacePixels ? surfacePixels[sourceIndex + 2] : Math.round(170 * texture);
        const brightness = 0.035 + terminator * (0.9 + z * 0.065);
        pixels.data[index] = Math.min(255, Math.round(sourceRed * brightness));
        pixels.data[index + 1] = Math.min(255, Math.round(sourceGreen * brightness));
        pixels.data[index + 2] = Math.min(255, Math.round(sourceBlue * brightness + (1 - terminator) * 5));
        pixels.data[index + 3] = distanceSquared <= 1 ? 255 : Math.round((1.025 - distanceSquared) / 0.025 * 255);
      }
    }
    context.putImageData(pixels, 0, 0);
    context.beginPath();
    context.arc(centerX, centerY, radius, 0, Math.PI * 2);
    context.strokeStyle = "rgba(255, 240, 198, 0.28)";
    context.lineWidth = 1.5;
    context.stroke();
    canvas.dataset.illumination = String(illuminationPercent);
    canvas.dataset.brightLimbAngle = String(moon.bright_limb_angle || 0);
    canvas.dataset.diskRotation = String(moon.disk_rotation || 0);
    canvas.setAttribute("aria-label", `Observer-local view of the ${moon.name}, ${illuminationPercent} percent illuminated`);
    canvas.title = moon.representative_date
      ? `${moon.name} · local view near lunar transit on ${moon.representative_date}`
      : `${moon.name} · local view now`;
  }

  function renderLocalMoon(moon) {
    renderMoonDisk(document.getElementById("currentMoonDisk"), moon);
  }

  function pairedPhaseCycle(phases) {
    const paired = phases.map((phase) => ({...phase}));
    [[1, 7], [2, 6], [3, 5]].forEach(([waxingIndex, waningIndex]) => {
      const waxing = paired.find((phase) => Number(phase.index) === waxingIndex);
      const waning = paired.find((phase) => Number(phase.index) === waningIndex);
      if (!waxing || !waning) return;
      const waxingAngle = Number(waxing.bright_limb_angle);
      const waningAsWaxing = (Number(waning.bright_limb_angle) + 180) % 360;
      if (!Number.isFinite(waxingAngle) || !Number.isFinite(waningAsWaxing)) return;
      const waxingRadians = waxingAngle * Math.PI / 180;
      const waningRadians = waningAsWaxing * Math.PI / 180;
      const pairedAngle = (Math.atan2(
        Math.sin(waxingRadians) + Math.sin(waningRadians),
        Math.cos(waxingRadians) + Math.cos(waningRadians),
      ) * 180 / Math.PI + 360) % 360;
      waxing.bright_limb_angle = pairedAngle;
      waning.bright_limb_angle = (pairedAngle + 180) % 360;
    });
    return paired;
  }

  moonSurfaceImage.addEventListener("load", () => {
    moonRenders.forEach((moon, canvas) => renderMoonDisk(canvas, moon));
  });
  moonSurfaceImage.src = "/static/moon-surface.png?v=1";

  function updateDaylightTrack(progressValue) {
    const sunMarker = document.getElementById("daylightSun");
    if (!sunMarker) return;
    const progress = Math.max(0, Math.min(100, Number(progressValue) || 0));
    sunMarker.style.setProperty("--daylight-progress", `${5 + progress * 0.9}%`);
    sunMarker.style.setProperty("--sun-rise", String(Math.sin(Math.PI * progress / 100)));
    sunMarker.dataset.daylightProgress = String(progress);
  }

  function formatSolarTime(value) {
    const match = String(value || "").match(/^(\d{1,2}):(\d{2})$/);
    if (!match) return "—";
    const hour24 = Number(match[1]);
    if (!Number.isFinite(hour24) || hour24 > 23) return "—";
    const hour12 = (hour24 % 12) || 12;
    return `${hour12}:${match[2]} ${hour24 < 12 ? "AM" : "PM"}`;
  }

  const initialMoonDisk = document.getElementById("currentMoonDisk");
  if (initialMoonDisk) {
    renderLocalMoon({
      illumination: initialMoonDisk.dataset.illumination,
      bright_limb_angle: initialMoonDisk.dataset.brightLimbAngle,
      disk_rotation: initialMoonDisk.dataset.diskRotation,
      name: document.getElementById("currentMoonName")?.textContent || "Moon",
    });
  }
  const initialPhaseCycle = Array.from(document.querySelectorAll("[data-phase-moon]")).map((canvas) => ({
      index: Number(canvas.dataset.phaseIndex),
      illumination: canvas.dataset.illumination,
      bright_limb_angle: canvas.dataset.brightLimbAngle,
      disk_rotation: canvas.dataset.diskRotation,
      name: canvas.getAttribute("aria-label")?.replace("Local view of the ", "") || "Moon phase",
  }));
  pairedPhaseCycle(initialPhaseCycle).forEach((phase) => {
    renderMoonDisk(document.querySelector(`[data-phase-index="${phase.index}"]`), phase);
  });
  updateDaylightTrack(document.getElementById("daylightSun")?.dataset.daylightProgress || 0);

  const windyFrame = document.querySelector("[data-windy-map]");
  const windyResetButton = document.querySelector("[data-reset-windy]");
  const windyInteraction = document.querySelector("[data-windy-interaction]");
  const windyGuard = document.querySelector("[data-windy-guard]");
  if (windyFrame && windyInteraction && windyGuard) {
    const setWindyActive = (active) => {
      windyInteraction.classList.toggle("is-active", active);
      windyFrame.setAttribute("tabindex", active ? "0" : "-1");
    };
    windyGuard.addEventListener("click", () => {
      setWindyActive(true);
      windyFrame.focus();
    });
    windyInteraction.addEventListener("mouseleave", () => setWindyActive(false));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && windyInteraction.classList.contains("is-active")) {
        setWindyActive(false);
        windyGuard.focus();
      }
    });
  }
  if (windyFrame && windyResetButton) {
    windyResetButton.addEventListener("click", () => {
      const mapUrl = windyFrame.getAttribute("src");
      if (!mapUrl) return;
      windyResetButton.disabled = true;
      windyResetButton.textContent = "Resetting…";
      windyFrame.addEventListener("load", () => {
        windyResetButton.disabled = false;
        windyResetButton.textContent = "× Close forecast";
      }, {once: true});
      windyFrame.setAttribute("src", mapUrl);
    });
  }

  function metricDate(value) {
    const text = String(value || "");
    return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(text) ? text : `${text}Z`);
  }

  function metricValue(value, decimals, unit) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "—";
    return `${numeric.toFixed(Number(decimals) || 0)}${unit ? ` ${unit}` : ""}`;
  }

  function metricTime(value, timezoneName) {
    const date = metricDate(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(undefined, {
      timeZone: timezoneName,
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  }

  function drawMetricGraph(canvas, metric, generatedAt, timezoneName) {
    const context = canvas.getContext("2d");
    const width = Math.max(320, Math.round(canvas.clientWidth || 520));
    const height = 190;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);

    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--accent-2").trim() || "#55d5c7";
    const muted = styles.getPropertyValue("--muted").trim() || "rgba(235,247,240,.7)";
    const line = styles.getPropertyValue("--line").trim() || "rgba(196,235,220,.28)";
    const left = 12;
    const right = width - 12;
    const top = 12;
    const bottom = height - 28;
    const end = metricDate(generatedAt).getTime();
    const start = end - (24 * 60 * 60 * 1000);
    const points = (metric.series || []).map((point) => ({
      time: metricDate(point.timestamp).getTime(),
      value: Number(point.value),
    })).filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));
    if (!points.length) return;
    let low = Math.min(...points.map((point) => point.value));
    let high = Math.max(...points.map((point) => point.value));
    if (high === low) {
      const padding = Math.max(Math.abs(high) * 0.05, 1);
      low -= padding;
      high += padding;
    }
    const x = (time) => left + ((time - start) / (end - start)) * (right - left);
    const y = (value) => bottom - ((value - low) / (high - low)) * (bottom - top);

    context.strokeStyle = line;
    context.fillStyle = muted;
    context.lineWidth = 1;
    context.font = "10px Inter, sans-serif";
    context.textAlign = "center";
    for (let hour = 0; hour <= 24; hour += 3) {
      const tickTime = start + hour * 60 * 60 * 1000;
      const tickX = x(tickTime);
      context.beginPath();
      context.moveTo(tickX, top);
      context.lineTo(tickX, bottom);
      context.stroke();
      const tickDate = new Date(tickTime);
      const parts = new Intl.DateTimeFormat(undefined, {
        timeZone: timezoneName,
        hour: "numeric",
        hour12: true,
      }).formatToParts(tickDate);
      const hourText = parts.find((part) => part.type === "hour")?.value || "";
      const period = parts.find((part) => part.type === "dayPeriod")?.value?.slice(0, 1) || "";
      context.fillText(`${hourText}${period}`, tickX, height - 9);
    }

    const average = Number(metric.stats?.avg);
    if (Number.isFinite(average)) {
      context.save();
      context.setLineDash([5, 4]);
      context.strokeStyle = muted;
      context.beginPath();
      context.moveTo(left, y(average));
      context.lineTo(right, y(average));
      context.stroke();
      context.restore();
    }

    context.strokeStyle = accent;
    context.lineWidth = 2.25;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.beginPath();
    points.forEach((point, index) => {
      const pointX = Math.max(left, Math.min(right, x(point.time)));
      const pointY = y(point.value);
      if (index === 0) context.moveTo(pointX, pointY);
      else context.lineTo(pointX, pointY);
    });
    context.stroke();
    if (points.length === 1) {
      context.fillStyle = accent;
      context.beginPath();
      context.arc(x(points[0].time), y(points[0].value), 3, 0, Math.PI * 2);
      context.fill();
    }
  }

  function createMetricCard(metric, generatedAt, timezoneName) {
    const card = document.createElement("article");
    card.className = "glass-card weather-metric-card";
    card.dataset.metricKey = metric.key;
    const heading = document.createElement("header");
    const titleBlock = document.createElement("div");
    const eyebrow = document.createElement("p");
    const title = document.createElement("h3");
    const current = document.createElement("strong");
    eyebrow.className = "eyebrow";
    eyebrow.textContent = "24hr graph";
    title.textContent = metric.label;
    current.className = "metric-current";
    current.textContent = metricValue(metric.current, metric.decimals, metric.unit);
    titleBlock.append(eyebrow, title);
    heading.append(titleBlock, current);

    const canvas = document.createElement("canvas");
    canvas.className = "weather-metric-graph";
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `24-hour graph of ${metric.label}`);

    const stats = document.createElement("dl");
    stats.className = "weather-metric-stats";
    [
      ["Min", metric.stats?.min, metric.stats?.min_at],
      ["Avg", metric.stats?.avg, null],
      ["Max", metric.stats?.max, metric.stats?.max_at],
    ].forEach(([label, value, timestamp]) => {
      const item = document.createElement("div");
      const term = document.createElement("dt");
      const definition = document.createElement("dd");
      term.textContent = label;
      definition.textContent = metricValue(value, metric.decimals, metric.unit);
      item.append(term, definition);
      if (timestamp) {
        const time = document.createElement("time");
        time.dateTime = timestamp;
        time.textContent = metricTime(timestamp, timezoneName);
        item.append(time);
      }
      stats.append(item);
    });
    card.append(heading, canvas, stats);
    requestAnimationFrame(() => drawMetricGraph(canvas, metric, generatedAt, timezoneName));
    if (window.ResizeObserver) {
      new ResizeObserver(() => drawMetricGraph(canvas, metric, generatedAt, timezoneName)).observe(canvas);
    }
    return card;
  }

  async function loadWeatherHistory() {
    const section = document.querySelector("[data-weather-history]");
    const grid = document.querySelector("[data-weather-metric-grid]");
    if (!section || !grid) return;
    try {
      const response = await fetch("/api/metrics/24h", {cache: "no-store"});
      if (!response.ok) throw new Error("history unavailable");
      const payload = await response.json();
      const metrics = Array.isArray(payload.metrics) ? payload.metrics : [];
      grid.replaceChildren();
      if (!metrics.length) {
        const empty = document.createElement("p");
        empty.className = "metric-loading";
        empty.textContent = "No valid Ecowitt readings have been stored in the last 24 hours.";
        grid.append(empty);
        return;
      }
      const timezoneName = payload.timezone || section.dataset.timezone || "UTC";
      metrics.forEach((metric) => {
        grid.append(createMetricCard(metric, payload.generated_at, timezoneName));
      });
    } catch (_error) {
      grid.replaceChildren();
      const error = document.createElement("p");
      error.className = "metric-loading metric-error";
      error.textContent = "The 24-hour weather history could not be loaded.";
      grid.append(error);
    }
  }

  loadWeatherHistory();

  function renderCurrentReading(reading, observationTime) {
    const available = reading && Object.keys(reading).length > 0;
    document.querySelectorAll("[data-reading-field]").forEach((element) => {
      const value = reading?.[element.dataset.readingField];
      element.textContent = value == null ? "—" : `${value}${element.dataset.readingSuffix || ""}`;
    });
    const observationStatus = document.querySelector("[data-observation-status]");
    if (observationStatus) {
      observationStatus.replaceChildren();
      if (available) {
        observationStatus.append("Last observation ");
        const time = document.createElement("time");
        time.dateTime = String(reading.timestamp || "");
        time.textContent = observationTime || "just now";
        observationStatus.append(time);
      } else {
        observationStatus.textContent = "Waiting for the first gateway observation";
      }
    }
    const stationState = document.querySelector("[data-station-state]");
    stationState?.classList.toggle("is-live", available);
    stationState?.classList.toggle("is-waiting", !available);
    const stationStateLabel = document.querySelector("[data-station-state-label]");
    if (stationStateLabel) stationStateLabel.textContent = available ? "Station reporting" : "Gateway standing by";
  }

  async function refreshEcowittDashboard() {
    if (document.hidden) return;
    try {
      const response = await fetch("/api/readings/current", {cache: "no-store"});
      if (!response.ok) throw new Error("current reading unavailable");
      const payload = await response.json();
      renderCurrentReading(payload.reading, payload.latest_observation_time);
      setDashboardRefreshInterval(Number(payload.poll_interval_seconds), false);
    } catch (_error) {
      // Keep the last displayed reading when a transient refresh fails.
    }
    await loadWeatherHistory();
  }

  let dashboardRefreshTimer = null;
  let dashboardRefreshSeconds = 0;
  function setDashboardRefreshInterval(seconds, restart = true) {
    const safeSeconds = Math.min(3600, Math.max(60, Number(seconds) || 300));
    if (!restart && safeSeconds === dashboardRefreshSeconds) return;
    dashboardRefreshSeconds = safeSeconds;
    if (dashboardRefreshTimer) window.clearInterval(dashboardRefreshTimer);
    dashboardRefreshTimer = window.setInterval(refreshEcowittDashboard, safeSeconds * 1000);
  }
  setDashboardRefreshInterval(Number(body.dataset.pollIntervalSeconds));

  let forecastRefreshDue = false;
  async function refreshForecastOnTheHour() {
    if (document.hidden) {
      forecastRefreshDue = true;
      return;
    }
    forecastRefreshDue = false;
    try {
      await fetch("/api/forecast?force=true", {cache: "no-store"});
    } finally {
      window.location.reload();
    }
  }

  function scheduleForecastRefresh() {
    const now = new Date();
    const nextHour = new Date(now);
    nextHour.setMinutes(60, 1, 0);
    window.setTimeout(refreshForecastOnTheHour, nextHour.getTime() - now.getTime());
  }
  scheduleForecastRefresh();

  async function refreshAstronomy() {
    if (document.hidden) return;
    try {
      const response = await fetch("/api/astronomy", {cache: "no-store"});
      if (!response.ok) return;
      const moon = await response.json();
      renderLocalMoon(moon);
      pairedPhaseCycle(moon.cycle || []).forEach((phase) => {
        renderMoonDisk(document.querySelector(`[data-phase-index="${phase.index}"]`), phase);
      });
      document.getElementById("currentMoonName").textContent = moon.name;
      document.getElementById("currentMoonIllumination").textContent = `${moon.illumination}%`;
      document.getElementById("currentMoonAge").textContent = moon.age_days;
      document.getElementById("moonLocalView").textContent = moon.moon_altitude == null
        ? "Observer-local orientation"
        : `Observer-local orientation · ${moon.moon_altitude}° altitude${moon.moon_altitude < 0 ? " (below horizon)" : ""}`;
      document.getElementById("sunriseTime").textContent = moon.sunrise;
      document.getElementById("sunsetTime").textContent = moon.sunset;
      document.getElementById("mapSunriseTime").textContent = moon.sunrise_display || formatSolarTime(moon.sunrise);
      document.getElementById("mapSunsetTime").textContent = moon.sunset_display || formatSolarTime(moon.sunset);
      document.getElementById("solarNoonTime").textContent = moon.solar_noon_display || formatSolarTime(moon.solar_noon);
      document.getElementById("daylightDuration").textContent = moon.daylight_duration;
      document.getElementById("northPoleDaylight").textContent = moon.north_pole_daylight ?? "—";
      document.getElementById("southPoleDaylight").textContent = moon.south_pole_daylight ?? "—";
      document.getElementById("nextSeasonLabel").textContent = moon.next_season_label ?? "—";
      const nextSeasonDate = document.getElementById("nextSeasonDate");
      nextSeasonDate.textContent = moon.next_season_date ?? "—";
      nextSeasonDate.setAttribute("datetime", moon.next_season_at || "");
      const eclipseList = document.getElementById("nextEclipseList");
      eclipseList.replaceChildren();
      const eclipses = Array.isArray(moon.next_eclipses) ? moon.next_eclipses.slice(0, 3) : [];
      if (!eclipses.length) {
        const emptyItem = document.createElement("li");
        emptyItem.className = "eclipse-empty";
        emptyItem.textContent = moon.eclipse_calculation_available
          ? "No visible eclipses for the next 12 months"
          : "Eclipse calculations unavailable · rerun the Caelus installer";
        eclipseList.append(emptyItem);
      } else {
        eclipses.forEach((eclipse) => {
          const item = document.createElement("li");
          const kind = document.createElement("strong");
          const date = document.createElement("time");
          kind.textContent = eclipse.kind || "Eclipse";
          date.textContent = eclipse.date || "—";
          date.setAttribute("datetime", eclipse.at || "");
          item.append(kind, date);
          eclipseList.append(item);
        });
      }
      document.getElementById("sunState").textContent = moon.sun_is_up ? "Sun above horizon" : "Sun below horizon";
      updateDaylightTrack(moon.daylight_progress);
      document.getElementById("lunarUpdated").textContent = `Updated ${moon.updated_at.slice(11, 16)} UTC`;
    } catch (_error) {
      return;
    }
  }

  window.setInterval(refreshAstronomy, 5 * 60 * 1000);
  document.addEventListener("visibilitychange", () => {
    refreshAstronomy();
    refreshEcowittDashboard();
    if (!document.hidden && forecastRefreshDue) refreshForecastOnTheHour();
  });
})();

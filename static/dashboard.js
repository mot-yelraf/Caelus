(function () {
  const dialog = document.getElementById("settingsDialog");
  const form = document.getElementById("settingsForm");
  if (!dialog || !form) return;

  const body = document.body;
  const themeInputs = Array.from(form.querySelectorAll('input[name="theme"]'));
  const tabs = Array.from(dialog.querySelectorAll("[data-settings-pane]"));
  const panes = Array.from(dialog.querySelectorAll("[data-pane]"));
  const settingsStatus = form.querySelector("[data-settings-status]");
  const metricStyleInput = form.querySelector("[data-metric-styles-value]");
  const allMetricStyles = form.querySelector("[data-all-metric-styles]");
  const metricStyleSelects = Array.from(form.querySelectorAll("[data-metric-style-key]"));
  const metricDisplayStyles = Object.fromEntries(
    metricStyleSelects.map((select) => [select.dataset.metricStyleKey, select.value])
  );
  let originalTheme = themeInputs.find((input) => input.checked)?.value || "garden";

  function syncMetricStyleInput() {
    if (metricStyleInput) metricStyleInput.value = JSON.stringify(metricDisplayStyles);
  }

  function updateAllMetricStyles() {
    if (!allMetricStyles) return;
    const styles = new Set(metricStyleSelects.map((select) => select.value));
    allMetricStyles.value = styles.size === 1 ? metricStyleSelects[0]?.value || "" : "";
  }

  metricStyleSelects.forEach((select) => {
    select.addEventListener("change", () => {
      metricDisplayStyles[select.dataset.metricStyleKey] = select.value;
      syncMetricStyleInput();
      updateAllMetricStyles();
    });
  });
  allMetricStyles?.addEventListener("change", () => {
    if (!allMetricStyles.value) return;
    metricStyleSelects.forEach((select) => {
      select.value = allMetricStyles.value;
      metricDisplayStyles[select.dataset.metricStyleKey] = allMetricStyles.value;
    });
    syncMetricStyleInput();
  });
  syncMetricStyleInput();
  updateAllMetricStyles();

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
      if (paneName === "appearance") window.location.reload();
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
      ecowittDiscovery = result;
      renderEcowittInventory(result.inventory);
      if (ecowittStatus) {
        ecowittStatus.textContent = result.initial_reading_stored
          ? `${result.gateway_model} saved; the first reading was stored.`
          : `${result.gateway_model} saved, but its first reading could not be retrieved.`;
      }
      setDashboardRefreshInterval(Number(result.poll_interval_seconds));
      await refreshEcowittDashboard();
    } catch (error) {
      if (ecowittStatus) ecowittStatus.textContent = error.message || "Gateway could not be saved.";
    } finally {
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

  const graphDialog = document.getElementById("graphDialog");
  const fullScreenGraph = graphDialog?.querySelector("[data-full-screen-graph]");
  const graphMetricInputs = Array.from(graphDialog?.querySelectorAll("[data-graph-metric]") || []);
  const graphRangeButtons = Array.from(graphDialog?.querySelectorAll("[data-graph-hours]") || []);
  const graphSelectionCount = graphDialog?.querySelector("[data-graph-selection-count]");
  const graphSelectionStatus = graphDialog?.querySelector("[data-graph-selection-status]");
  const graphStageTitle = graphDialog?.querySelector("#graphStageTitle");
  const graphStageMeta = graphDialog?.querySelector("[data-graph-stage-meta]");
  const graphStageMessage = graphDialog?.querySelector("[data-graph-stage-message]");
  let selectedGraphHours = 24;
  let renderedGraphPayload = null;
  let renderedGraphKeys = [];
  let fullGraphRequestSequence = 0;

  const graphRangeLabels = new Map([
    [1, "Last hour"], [6, "Last 6 hours"], [12, "Last 12 hours"], [24, "Last 24 hours"],
    [72, "Last 3 days"], [168, "Last 7 days"], [336, "Last 14 days"], [696, "Last 29 days"],
  ]);

  function updateGraphSelectionState(message = "") {
    const count = graphMetricInputs.filter((input) => input.checked).length;
    if (graphSelectionCount) graphSelectionCount.textContent = `${count} of 4`;
    if (graphSelectionStatus) {
      graphSelectionStatus.textContent = message || "Select up to four metrics.";
      graphSelectionStatus.classList.toggle("is-error", Boolean(message));
    }
  }

  graphMetricInputs.forEach((input) => {
    input.addEventListener("change", () => {
      const selected = graphMetricInputs.filter((item) => item.checked);
      if (selected.length > 4) {
        input.checked = false;
        updateGraphSelectionState("A maximum of four metrics can be graphed.");
        return;
      }
      updateGraphSelectionState();
      renderSelectedFullGraph();
    });
  });
  graphRangeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      selectedGraphHours = Number(button.dataset.graphHours) || 24;
      graphRangeButtons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
      renderSelectedFullGraph();
    });
  });

  function fullGraphValue(value, decimals) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "—";
    const precision = Math.min(2, Math.max(0, Number(decimals) || 0));
    return numeric.toLocaleString(undefined, {minimumFractionDigits: precision, maximumFractionDigits: precision});
  }

  function drawFullScreenGraph(canvas, metrics, payload) {
    if (!canvas || !metrics.length) return;
    const context = canvas.getContext("2d");
    const width = Math.max(720, Math.round(canvas.clientWidth || 1100));
    const height = Math.max(420, Math.round(canvas.clientHeight || 650));
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);

    const colors = ["#5eead4", "#7dd3fc", "#fbbf24", "#fb7185"];
    const plotLeft = 132;
    const plotRight = width - 132;
    const plotTop = 42;
    const plotBottom = height - 68;
    const axes = metrics.map((metric, index) => {
      const points = (metric.series || []).map((point) => ({time: metricDate(point.timestamp).getTime(), value: Number(point.value)}))
        .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));
      let minimum = points.length ? Math.min(...points.map((point) => point.value)) : 0;
      let maximum = points.length ? Math.max(...points.map((point) => point.value)) : 1;
      const padding = maximum === minimum ? Math.max(Math.abs(maximum) * 0.05, 1) : (maximum - minimum) * 0.06;
      minimum -= padding;
      maximum += padding;
      const side = index < 2 ? "left" : "right";
      const sideIndex = index % 2;
      const axisX = side === "left" ? plotLeft - sideIndex * 62 : plotRight + sideIndex * 62;
      return {metric, points, minimum, maximum, side, sideIndex, axisX, color: colors[index]};
    });
    const requestedDuration = Math.max(1, Number(payload.hours) || 24) * 60 * 60 * 1000;
    const requestedEndTime = metricDate(payload.generated_at).getTime();
    const requestedStartTime = requestedEndTime - requestedDuration;
    const earliestDataTime = Math.min(...axes.flatMap((axis) => axis.points.map((point) => point.time)));
    const startTime = Number.isFinite(earliestDataTime) && earliestDataTime > requestedStartTime
      ? earliestDataTime
      : requestedStartTime;
    const endTime = startTime + requestedDuration;
    const x = (time) => plotLeft + Math.max(0, Math.min(1, (time - startTime) / requestedDuration)) * (plotRight - plotLeft);

    context.font = "10px Inter, sans-serif";
    context.strokeStyle = "rgba(185,226,211,.14)";
    context.fillStyle = "rgba(225,242,235,.66)";
    context.lineWidth = 1;
    const xTickCount = width < 1000 ? 5 : 8;
    for (let tick = 0; tick <= xTickCount; tick += 1) {
      const tickTime = startTime + (endTime - startTime) * tick / xTickCount;
      const tickX = x(tickTime);
      context.beginPath();
      context.moveTo(tickX, plotTop);
      context.lineTo(tickX, plotBottom);
      context.stroke();
      const options = payload.hours <= 24
        ? {timeZone: payload.timezone, hour: "numeric", minute: payload.hours <= 6 ? "2-digit" : undefined}
        : {timeZone: payload.timezone, month: "short", day: "numeric"};
      context.textAlign = tick === 0 ? "left" : tick === xTickCount ? "right" : "center";
      context.fillText(new Intl.DateTimeFormat(undefined, options).format(new Date(tickTime)).replace(" ", ""), tickX, plotBottom + 24);
    }

    axes.forEach((axis) => {
      const valueRange = axis.maximum - axis.minimum;
      const tickStep = valueRange / 4;
      const stepDecimals = tickStep < 1 ? 2 : Number.isInteger(tickStep) ? 0 : 1;
      const decimals = Math.min(2, Math.max(Number(axis.metric.decimals) || 0, stepDecimals));
      const y = (value) => plotBottom - ((value - axis.minimum) / valueRange) * (plotBottom - plotTop);
      context.strokeStyle = axis.color;
      context.fillStyle = axis.color;
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(axis.axisX, plotTop);
      context.lineTo(axis.axisX, plotBottom);
      context.stroke();
      for (let tick = 0; tick <= 4; tick += 1) {
        const value = axis.minimum + valueRange * tick / 4;
        const tickY = y(value);
        context.beginPath();
        context.moveTo(axis.axisX + (axis.side === "left" ? -5 : 5), tickY);
        context.lineTo(axis.axisX, tickY);
        context.stroke();
        context.textAlign = axis.side === "left" ? "right" : "left";
        context.textBaseline = "middle";
        context.fillText(fullGraphValue(value, decimals), axis.axisX + (axis.side === "left" ? -8 : 8), tickY);
      }
      context.save();
      context.translate(axis.axisX + (axis.side === "left" ? -46 : 46), (plotTop + plotBottom) / 2);
      context.rotate(axis.side === "left" ? -Math.PI / 2 : Math.PI / 2);
      context.textAlign = "center";
      context.font = "700 11px Inter, sans-serif";
      context.fillText(`${axis.metric.label}${axis.metric.unit ? ` (${axis.metric.unit})` : ""}`, 0, 0);
      context.restore();

      context.strokeStyle = axis.color;
      context.lineWidth = 2.5;
      context.lineJoin = "round";
      context.lineCap = "round";
      context.beginPath();
      axis.points.forEach((point, pointIndex) => {
        const pointX = x(point.time);
        const pointY = y(point.value);
        if (pointIndex === 0) context.moveTo(pointX, pointY);
        else context.lineTo(pointX, pointY);
      });
      context.stroke();
    });

    context.font = "700 10px Inter, sans-serif";
    context.textBaseline = "alphabetic";
    let legendX = plotLeft;
    axes.forEach((axis) => {
      const current = axis.metric.current;
      const label = `${axis.metric.label}: ${fullGraphValue(current, axis.metric.decimals)}${axis.metric.unit ? ` ${axis.metric.unit}` : ""}`;
      context.fillStyle = axis.color;
      context.fillRect(legendX, 12, 10, 10);
      context.fillText(label, legendX + 15, 21);
      legendX += context.measureText(label).width + 42;
    });
    canvas.setAttribute("aria-label", `${graphRangeLabels.get(Number(payload.hours)) || `${payload.hours} hours`} graph of ${metrics.map((metric) => metric.label).join(", ")}`);
  }

  async function renderSelectedFullGraph({silent = false} = {}) {
    const selectedKeys = graphMetricInputs.filter((input) => input.checked).map((input) => input.value);
    if (!selectedKeys.length) {
      fullGraphRequestSequence += 1;
      renderedGraphPayload = null;
      renderedGraphKeys = [];
      if (fullScreenGraph) fullScreenGraph.width = fullScreenGraph.width;
      if (graphStageTitle) graphStageTitle.textContent = graphRangeLabels.get(selectedGraphHours) || `${selectedGraphHours} hours`;
      if (graphStageMeta) graphStageMeta.textContent = "No metrics selected";
      if (graphStageMessage) {
        graphStageMessage.hidden = false;
        graphStageMessage.textContent = "Select at least one metric.";
      }
      updateGraphSelectionState("Select at least one metric.");
      return;
    }
    const requestSequence = ++fullGraphRequestSequence;
    if (!silent && graphStageMessage) {
      graphStageMessage.hidden = false;
      graphStageMessage.textContent = "Loading graph data…";
    }
    try {
      const response = await fetch(`/api/metrics/range?hours=${selectedGraphHours}`, {cache: "no-store"});
      if (!response.ok) throw new Error("Graph data is unavailable.");
      const payload = await response.json();
      if (requestSequence !== fullGraphRequestSequence) return;
      const metricsByKey = new Map((payload.metrics || []).map((metric) => [metric.key, metric]));
      const selectedMetrics = selectedKeys.map((key) => metricsByKey.get(key)).filter(Boolean);
      if (!selectedMetrics.length) throw new Error("No stored readings are available for the selected metrics.");
      renderedGraphPayload = payload;
      renderedGraphKeys = selectedMetrics.map((metric) => metric.key);
      if (graphStageTitle) graphStageTitle.textContent = graphRangeLabels.get(Number(payload.hours)) || `${payload.hours} hours`;
      if (graphStageMeta) graphStageMeta.textContent = selectedMetrics.map((metric) => metric.label).join(" · ");
      if (graphStageMessage) graphStageMessage.hidden = true;
      drawFullScreenGraph(fullScreenGraph, selectedMetrics, payload);
      updateGraphSelectionState(selectedMetrics.length < selectedKeys.length ? "Metrics without stored readings were omitted." : "");
    } catch (error) {
      if (requestSequence === fullGraphRequestSequence && !silent && graphStageMessage) {
        graphStageMessage.hidden = false;
        graphStageMessage.textContent = error.message || "Graph data is unavailable.";
      }
    }
  }

  document.querySelectorAll("[data-open-graph]").forEach((button) => {
    button.addEventListener("click", () => {
      graphDialog?.showModal();
      body.classList.add("modal-open");
      updateGraphSelectionState();
      renderSelectedFullGraph();
    });
  });
  graphDialog?.querySelectorAll("[data-close-graph]").forEach((button) => button.addEventListener("click", () => graphDialog.close()));
  graphDialog?.addEventListener("close", () => body.classList.remove("modal-open"));
  graphDialog?.addEventListener("click", (event) => {
    if (event.target === graphDialog) graphDialog.close();
  });
  if (window.ResizeObserver && fullScreenGraph) {
    new ResizeObserver(() => {
      if (!renderedGraphPayload || !graphDialog?.open) return;
      const metricsByKey = new Map((renderedGraphPayload.metrics || []).map((metric) => [metric.key, metric]));
      drawFullScreenGraph(fullScreenGraph, renderedGraphKeys.map((key) => metricsByKey.get(key)).filter(Boolean), renderedGraphPayload);
    }).observe(fullScreenGraph);
  }

  function drawMetricGraph(canvas, metric, generatedAt, timezoneName, hours = 24) {
    const context = canvas.getContext("2d");
    const width = Math.max(320, Math.round(canvas.clientWidth || 520));
    const height = 230;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);

    const styles = getComputedStyle(canvas.closest(".glass-card") || document.documentElement);
    const accent = styles.getPropertyValue("--metric-graph-accent").trim()
      || styles.getPropertyValue("--accent-2").trim() || "#55d5c7";
    const muted = styles.getPropertyValue("--muted").trim() || "rgba(235,247,240,.7)";
    const line = styles.getPropertyValue("--line").trim() || "rgba(196,235,220,.28)";
    const left = 52;
    const right = width - 12;
    const top = 12;
    const bottom = height - 28;
    const generatedTime = metricDate(generatedAt).getTime();
    const rollingStart = generatedTime - (hours * 60 * 60 * 1000);
    const points = (metric.series || []).map((point) => ({
      time: metricDate(point.timestamp).getTime(),
      value: Number(point.value),
    })).filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value))
      .filter((point) => point.time >= rollingStart && point.time <= generatedTime)
      .sort((a, b) => a.time - b.time);
    if (!points.length) return;
    const start = Math.max(rollingStart, points[0].time);
    const latestTime = points[points.length - 1].time;
    const end = latestTime > start ? latestTime : start + 1;
    const displayedDuration = end - start;
    let low = Math.min(...points.map((point) => point.value));
    let high = Math.max(...points.map((point) => point.value));
    if (high === low) {
      const padding = Math.max(Math.abs(high) * 0.05, 1);
      low -= padding;
      high += padding;
    }
    const x = (time) => left + ((time - start) / (end - start)) * (right - left);
    const y = (value) => bottom - ((value - low) / (high - low)) * (bottom - top);
    const valueRange = high - low;
    const yTickCount = 4;
    const tickStep = valueRange / yTickCount;
    const stepDecimals = tickStep < 1 ? 2 : Number.isInteger(tickStep) ? 0 : 1;
    const axisDecimals = Math.min(2, Math.max(Number(metric.decimals) || 0, stepDecimals));
    const formatAxisValue = (value) => Number(value).toLocaleString(undefined, {
      minimumFractionDigits: axisDecimals,
      maximumFractionDigits: axisDecimals,
    });

    context.strokeStyle = line;
    context.fillStyle = muted;
    context.lineWidth = 1;
    context.font = "10px Inter, sans-serif";
    context.textBaseline = "middle";
    context.textAlign = "right";
    for (let tick = 0; tick <= yTickCount; tick += 1) {
      const tickValue = low + (high - low) * tick / yTickCount;
      const tickY = y(tickValue);
      context.beginPath();
      context.moveTo(left - 5, tickY);
      context.lineTo(right, tickY);
      context.stroke();
      context.fillText(formatAxisValue(tickValue), left - 8, tickY);
    }
    context.beginPath();
    context.moveTo(left, top);
    context.lineTo(left, bottom);
    context.stroke();

    context.textBaseline = "alphabetic";
    context.textAlign = "center";
    const tickCount = width < 400 ? 4 : 8;
    for (let tick = 0; tick <= tickCount; tick += 1) {
      const tickTime = start + displayedDuration * tick / tickCount;
      const tickX = x(tickTime);
      context.beginPath();
      context.moveTo(tickX, top);
      context.lineTo(tickX, bottom);
      context.stroke();
      const tickDate = new Date(tickTime);
      const tickLabel = new Intl.DateTimeFormat(undefined, displayedDuration < 6 * 60 * 60 * 1000
        ? {timeZone: timezoneName, hour: "numeric", minute: "2-digit"}
        : {timeZone: timezoneName, hour: "numeric", hour12: true}
      ).format(tickDate);
      context.textAlign = tick === 0 ? "left" : tick === tickCount ? "right" : "center";
      context.fillText(tickLabel.replace(" ", ""), tickX, height - 9);
    }

    const average = points.reduce((sum, point) => sum + point.value, 0) / points.length;
    if (Number.isFinite(average)) {
      const averageY = y(average);
      context.save();
      context.setLineDash([5, 4]);
      context.strokeStyle = muted;
      context.beginPath();
      context.moveTo(left, averageY);
      context.lineTo(right, averageY);
      context.stroke();
      context.restore();

      const averageLabel = `AVG ${metricValue(average, metric.decimals, metric.unit)}`;
      context.font = "700 9px Inter, sans-serif";
      context.textAlign = "right";
      context.textBaseline = "middle";
      const labelWidth = context.measureText(averageLabel).width + 8;
      const labelY = Math.max(top + 7, Math.min(bottom - 7, averageY - 8));
      context.fillStyle = styles.getPropertyValue("--metric-graph-bg").trim()
        || styles.getPropertyValue("--glass-strong").trim() || "rgba(3,22,28,.82)";
      context.fillRect(right - labelWidth, labelY - 7, labelWidth, 14);
      context.fillStyle = accent;
      context.fillText(averageLabel, right - 4, labelY);
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

  const windDirections = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

  function drawWindRose(canvas, metric, generatedAt, hours) {
    const context = canvas.getContext("2d");
    const width = Math.max(320, Math.round(canvas.clientWidth || 520));
    const height = 230;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);

    const styles = getComputedStyle(canvas.closest(".glass-card") || document.documentElement);
    const muted = styles.getPropertyValue("--muted").trim() || "rgba(235,247,240,.7)";
    const line = styles.getPropertyValue("--line").trim() || "rgba(196,235,220,.28)";
    const ink = styles.getPropertyValue("--ink").trim() || "#eef8f4";
    const metricWind = metric.wind_speed?.unit === "km/h";
    const speedBands = metricWind ? [
      {maximum: 8, label: "0–8", color: "#b9e7fb"},
      {maximum: 24, label: "8–24", color: "#72c7ed"},
      {maximum: 48, label: "24–48", color: "#2e91ca"},
      {maximum: Infinity, label: "48+", color: "#164d80"},
    ] : [
      {maximum: 5, label: "0–5", color: "#b9e7fb"},
      {maximum: 15, label: "5–15", color: "#72c7ed"},
      {maximum: 30, label: "15–30", color: "#2e91ca"},
      {maximum: Infinity, label: "30+", color: "#164d80"},
    ];
    const end = metricDate(generatedAt).getTime();
    const start = end - hours * 60 * 60 * 1000;
    const bins = Array.from({length: 16}, () => ({bands: [0, 0, 0, 0], count: 0, speedTotal: 0}));
    (metric.wind_speed?.series || []).forEach((point) => {
      const time = metricDate(point.timestamp).getTime();
      const direction = Number(point.direction);
      const speed = Number(point.speed);
      if (!Number.isFinite(time) || time < start || time > end || !Number.isFinite(direction) || !Number.isFinite(speed)) return;
      const directionIndex = Math.round(((direction % 360) + 360) % 360 / 22.5) % 16;
      const bandIndex = speedBands.findIndex((band) => speed < band.maximum);
      bins[directionIndex].bands[Math.max(0, bandIndex)] += 1;
      bins[directionIndex].count += 1;
      bins[directionIndex].speedTotal += speed;
    });

    const total = bins.reduce((sum, bin) => sum + bin.count, 0);
    const maxCount = Math.max(...bins.map((bin) => bin.count), 1);
    const centerX = width / 2;
    const centerY = 101;
    const radius = 72;
    context.strokeStyle = line;
    context.lineWidth = 1;
    [0.25, 0.5, 0.75, 1].forEach((fraction) => {
      context.beginPath();
      context.arc(centerX, centerY, radius * fraction, 0, Math.PI * 2);
      context.stroke();
    });
    context.beginPath();
    context.moveTo(centerX - radius, centerY);
    context.lineTo(centerX + radius, centerY);
    context.moveTo(centerX, centerY - radius);
    context.lineTo(centerX, centerY + radius);
    context.stroke();

    bins.forEach((bin, directionIndex) => {
      let accumulated = 0;
      const centerAngle = directionIndex * Math.PI / 8 - Math.PI / 2;
      const halfWidth = Math.PI / 8 * 0.42;
      bin.bands.forEach((count, bandIndex) => {
        if (!count) return;
        const innerRadius = radius * accumulated / maxCount;
        accumulated += count;
        const outerRadius = radius * accumulated / maxCount;
        context.fillStyle = speedBands[bandIndex].color;
        context.beginPath();
        context.arc(centerX, centerY, outerRadius, centerAngle - halfWidth, centerAngle + halfWidth);
        context.arc(centerX, centerY, innerRadius, centerAngle + halfWidth, centerAngle - halfWidth, true);
        context.closePath();
        context.fill();
      });
    });

    context.fillStyle = ink;
    context.font = "700 11px Inter, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText("N", centerX, centerY - radius - 14);
    context.fillText("E", centerX + radius + 14, centerY);
    context.fillText("S", centerX, centerY + radius + 14);
    context.fillText("W", centerX - radius - 14, centerY);

    if (total) {
      const dominantIndex = bins.reduce((best, bin, index) => bin.count > bins[best].count ? index : best, 0);
      const dominantPercent = Math.round(bins[dominantIndex].count / total * 100);
      context.fillStyle = "rgba(6, 24, 33, 0.88)";
      context.beginPath();
      context.arc(centerX, centerY, 23, 0, Math.PI * 2);
      context.fill();
      context.fillStyle = "#ffffff";
      context.font = "700 11px Inter, sans-serif";
      context.fillText(windDirections[dominantIndex], centerX, centerY - 5);
      context.font = "700 9px Inter, sans-serif";
      context.fillText(`${dominantPercent}%`, centerX, centerY + 8);
    } else {
      context.fillStyle = muted;
      context.font = "10px Inter, sans-serif";
      context.fillText("No wind samples", centerX, centerY);
    }

    const legendWidth = Math.min(270, width - 24);
    const legendStart = centerX - legendWidth / 2;
    context.textAlign = "left";
    context.font = "700 9px Inter, sans-serif";
    speedBands.forEach((band, index) => {
      const x = legendStart + index * legendWidth / 4;
      context.fillStyle = band.color;
      context.fillRect(x, 211, 10, 10);
      context.fillStyle = muted;
      context.fillText(band.label, x + 14, 216);
    });
    context.textAlign = "right";
    context.fillText(metric.wind_speed?.unit || "mph", legendStart + legendWidth, 216);
    canvas.windRoseSummary = {bins, total, hours};
  }

  function gaugeConfig(metric) {
    const values = (metric.series || []).map((point) => Number(point.value)).filter(Number.isFinite);
    const observedMin = values.length ? Math.min(...values) : 0;
    const observedMax = values.length ? Math.max(...values) : 100;
    const configs = {
      temperature: [-20, 50, ["#2474c6", "#65b8e8", "#65b96e", "#f0c64e", "#cf4b3f"]],
      dew_point: [-20, 50, ["#2474c6", "#65b8e8", "#65b96e", "#f0c64e", "#cf4b3f"]],
      wind_chill: [-20, 50, ["#2474c6", "#65b8e8", "#65b96e", "#f0c64e", "#cf4b3f"]],
      heat_index: [-20, 50, ["#2474c6", "#65b8e8", "#65b96e", "#f0c64e", "#cf4b3f"]],
      humidity: [0, 100, ["#b47a16", "#e6bb38", "#9ed6e4", "#4a9fdf", "#174da8"]],
      indoor_humidity: [0, 100, ["#b47a16", "#e6bb38", "#9ed6e4", "#4a9fdf", "#174da8"]],
      pressure: [950, 1050, ["#9ed6e4"]],
      absolute_pressure: [950, 1050, ["#9ed6e4"]],
      indoor_pressure: [950, 1050, ["#9ed6e4"]],
      indoor_absolute_pressure: [950, 1050, ["#9ed6e4"]],
      uv: [0, 12, ["#65b96e", "#f0c64e", "#e88b35", "#cf4b3f", "#7a398f"]],
      wind_speed: [0, metric.unit === "km/h" ? 80 : 50, ["#9ed6e4", "#65b8e8", "#2474c6", "#174da8"]],
      wind_gust: [0, metric.unit === "km/h" ? 80 : 50, ["#9ed6e4", "#65b8e8", "#2474c6", "#174da8"]],
      daily_max_wind: [0, metric.unit === "km/h" ? 80 : 50, ["#9ed6e4", "#65b8e8", "#2474c6", "#174da8"]],
    };
    if (configs[metric.key]) {
      const config = configs[metric.key];
      if (metric.unit === "°F" && config[0] === -20 && config[1] === 50) return [0, 140, config[2]];
      if (metric.unit === "inHg" && config[0] === 950) return [28, 31, config[2]];
      return config;
    }
    const spread = Math.max(observedMax - observedMin, Math.abs(observedMax) * 0.2, 1);
    return [Math.min(0, observedMin - spread * 0.15), observedMax + spread * 0.2, ["#65b8e8", "#65b96e", "#f0c64e", "#cf4b3f"]];
  }

  function drawMetricGauge(canvas, metric) {
    const context = canvas.getContext("2d");
    const width = Math.max(320, Math.round(canvas.clientWidth || 520));
    const height = 230;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);
    const styles = getComputedStyle(canvas.closest(".glass-card") || document.documentElement);
    const ink = styles.getPropertyValue("--ink").trim() || "#eef8f4";
    const muted = styles.getPropertyValue("--muted").trim() || "rgba(235,247,240,.7)";
    const value = Number(metric.current);
    const [minimum, maximum, zones] = gaugeConfig(metric);
    const centerX = width / 2;
    const centerY = 133;
    const radius = 84;
    const start = Math.PI * 0.82;
    const end = Math.PI * 2.18;
    const angleFor = (number) => start + Math.max(0, Math.min(1, (number - minimum) / (maximum - minimum))) * (end - start);

    context.lineCap = "butt";
    context.lineWidth = 21;
    zones.forEach((color, index) => {
      context.strokeStyle = color;
      context.beginPath();
      context.arc(centerX, centerY, radius, start + (end - start) * index / zones.length, start + (end - start) * (index + 1) / zones.length);
      context.stroke();
    });
    context.fillStyle = muted;
    context.font = "700 10px Inter, sans-serif";
    context.textAlign = "center";
    for (let index = 0; index <= 5; index += 1) {
      const tickValue = minimum + (maximum - minimum) * index / 5;
      const angle = angleFor(tickValue);
      const tickX = centerX + Math.cos(angle) * (radius + 24);
      const tickY = centerY + Math.sin(angle) * (radius + 24);
      context.fillText(Math.abs(tickValue) >= 100 ? Math.round(tickValue) : Number(tickValue.toFixed(1)), tickX, tickY);
    }
    if (Number.isFinite(value)) {
      const needle = angleFor(value);
      context.strokeStyle = ink;
      context.lineWidth = 4;
      context.lineCap = "round";
      context.beginPath();
      context.moveTo(centerX - Math.cos(needle) * 13, centerY - Math.sin(needle) * 13);
      context.lineTo(centerX + Math.cos(needle) * radius * 0.72, centerY + Math.sin(needle) * radius * 0.72);
      context.stroke();
      context.fillStyle = ink;
      context.beginPath();
      context.arc(centerX, centerY, 7, 0, Math.PI * 2);
      context.fill();
    }
    context.fillStyle = ink;
    context.font = "700 15px Inter, sans-serif";
    context.fillText(metricValue(metric.current, metric.decimals, metric.unit), centerX, 205);
  }

  function drawCompassGauge(canvas, metric) {
    const context = canvas.getContext("2d");
    const width = Math.max(320, Math.round(canvas.clientWidth || 520));
    const height = 230;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);
    const styles = getComputedStyle(canvas.closest(".glass-card") || document.documentElement);
    const ink = styles.getPropertyValue("--ink").trim() || "#eef8f4";
    const line = styles.getPropertyValue("--line").trim() || "rgba(196,235,220,.28)";
    const centerX = width / 2;
    const centerY = 112;
    const radius = 82;
    context.fillStyle = "rgba(158, 214, 228, 0.5)";
    context.strokeStyle = line;
    context.lineWidth = 10;
    context.beginPath();
    context.arc(centerX, centerY, radius, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    for (let degrees = 0; degrees < 360; degrees += 15) {
      const angle = (degrees - 90) * Math.PI / 180;
      const major = degrees % 45 === 0;
      context.strokeStyle = ink;
      context.lineWidth = major ? 2 : 1;
      context.beginPath();
      context.moveTo(centerX + Math.cos(angle) * (radius - (major ? 13 : 8)), centerY + Math.sin(angle) * (radius - (major ? 13 : 8)));
      context.lineTo(centerX + Math.cos(angle) * radius, centerY + Math.sin(angle) * radius);
      context.stroke();
    }
    context.fillStyle = ink;
    context.font = "700 16px Inter, sans-serif";
    context.textAlign = "center";
    [["N", 0], ["E", 90], ["S", 180], ["W", 270]].forEach(([label, degrees]) => {
      const angle = (degrees - 90) * Math.PI / 180;
      context.fillText(label, centerX + Math.cos(angle) * 53, centerY + Math.sin(angle) * 53 + 5);
    });
    const value = Number(metric.current);
    if (Number.isFinite(value)) {
      const angle = (value - 90) * Math.PI / 180;
      context.fillStyle = ink;
      context.beginPath();
      context.moveTo(centerX + Math.cos(angle) * 67, centerY + Math.sin(angle) * 67);
      context.lineTo(centerX + Math.cos(angle + Math.PI / 2) * 7 - Math.cos(angle) * 16, centerY + Math.sin(angle + Math.PI / 2) * 7 - Math.sin(angle) * 16);
      context.lineTo(centerX + Math.cos(angle - Math.PI / 2) * 7 - Math.cos(angle) * 16, centerY + Math.sin(angle - Math.PI / 2) * 7 - Math.sin(angle) * 16);
      context.closePath();
      context.fill();
      context.beginPath();
      context.arc(centerX, centerY, 8, 0, Math.PI * 2);
      context.fill();
    }
  }

  async function persistMetricDisplayStyles() {
    syncMetricStyleInput();
    const formData = new FormData();
    formData.append("csrf_token", form.querySelector('input[name="csrf_token"]')?.value || "");
    formData.append("settings_pane", "appearance");
    formData.append("metric_display_styles", JSON.stringify(metricDisplayStyles));
    try {
      await fetch(form.action, {method: "POST", body: formData});
    } catch (_error) {
      // The card has already changed locally; the next Appearance save retries it.
    }
  }

  function createMetricCard(metric, generatedAt, timezoneName) {
    const card = document.createElement("article");
    card.className = "glass-card weather-metric-card";
    card.dataset.metricKey = metric.key;
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    const heading = document.createElement("header");
    const titleBlock = document.createElement("div");
    const eyebrow = document.createElement("p");
    const title = document.createElement("h3");
    const current = document.createElement("strong");
    eyebrow.className = "eyebrow";
    current.className = "metric-current";
    titleBlock.append(eyebrow, title);
    heading.append(titleBlock, current);
    const canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    const stats = document.createElement("dl");
    stats.className = "weather-metric-stats";
    const statElements = ["Min", "Avg", "Max"].map((label) => {
      const item = document.createElement("div");
      const term = document.createElement("dt");
      const definition = document.createElement("dd");
      const time = document.createElement("time");
      term.textContent = label;
      item.append(term, definition, time);
      stats.append(item);
      return {term, definition, time};
    });
    card.append(heading, canvas, stats);

    const isWindRose = metric.key === "wind_dir" && metric.wind_speed;
    let displayStyle = metricDisplayStyles[metric.key] || "graph24hr";

    function updateStats(displayedMetric, hours) {
      const end = metricDate(generatedAt).getTime();
      const start = end - hours * 60 * 60 * 1000;
      const points = (displayedMetric.series || []).map((point) => ({
        timestamp: point.timestamp,
        value: Number(point.value ?? point.speed),
      })).filter((point) => Number.isFinite(point.value) && metricDate(point.timestamp).getTime() >= start);
      if (!points.length) return;
      const minimum = points.reduce((best, point) => point.value < best.value ? point : best);
      const maximum = points.reduce((best, point) => point.value > best.value ? point : best);
      const average = points.reduce((sum, point) => sum + point.value, 0) / points.length;
      [[minimum.value, minimum.timestamp], [average, null], [maximum.value, maximum.timestamp]].forEach(([value, timestamp], index) => {
        statElements[index].term.textContent = isWindRose ? `${hours}h ${["Min", "Avg", "Max"][index]}` : ["Min", "Avg", "Max"][index];
        statElements[index].definition.textContent = metricValue(value, displayedMetric.decimals, displayedMetric.unit);
        statElements[index].time.textContent = timestamp ? metricTime(timestamp, timezoneName) : "";
        statElements[index].time.dateTime = timestamp || "";
      });
    }

    function render() {
      const hours = displayStyle === "graph6hr" ? 6 : 24;
      const gaugeMode = displayStyle === "gauge";
      const displayedMetric = isWindRose && !gaugeMode ? metric.wind_speed : metric;
      eyebrow.textContent = gaugeMode ? "Gauge" : `${hours}hr graph`;
      title.textContent = isWindRose ? (gaugeMode ? "Wind direction" : `${hours}-hour Wind-Rose`) : metric.label;
      current.textContent = metricValue(displayedMetric.current, displayedMetric.decimals, displayedMetric.unit);
      canvas.className = `weather-metric-graph${gaugeMode ? " weather-metric-gauge" : isWindRose ? " wind-rose-graph" : ""}`;
      canvas.setAttribute("aria-label", gaugeMode
        ? `Gauge for ${title.textContent}`
        : isWindRose ? `${hours}-hour wind rose with wind-speed bands` : `${hours}-hour graph of ${metric.label}`);
      card.setAttribute("aria-label", `${title.textContent}, ${eyebrow.textContent}. Click to change display style.`);
      updateStats(displayedMetric, gaugeMode ? 24 : hours);
      if (gaugeMode) {
        if (isWindRose) drawCompassGauge(canvas, metric);
        else drawMetricGauge(canvas, metric);
      } else if (isWindRose) {
        drawWindRose(canvas, metric, generatedAt, hours);
      } else {
        drawMetricGraph(canvas, metric, generatedAt, timezoneName, hours);
      }
    }

    function cycleDisplayStyle() {
      displayStyle = displayStyle === "graph24hr" ? "graph6hr" : displayStyle === "graph6hr" ? "gauge" : "graph24hr";
      metricDisplayStyles[metric.key] = displayStyle;
      const selector = metricStyleSelects.find((item) => item.dataset.metricStyleKey === metric.key);
      if (selector) selector.value = displayStyle;
      updateAllMetricStyles();
      render();
      persistMetricDisplayStyles();
    }

    card.addEventListener("click", cycleDisplayStyle);
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      cycleDisplayStyle();
    });
    canvas.addEventListener("mousemove", (event) => {
      const summary = canvas.windRoseSummary;
      if (!summary?.total || displayStyle === "gauge") return;
      const rect = canvas.getBoundingClientRect();
      const angle = (Math.atan2(event.clientY - rect.top - 101, event.clientX - rect.left - rect.width / 2) + Math.PI / 2 + Math.PI * 2) % (Math.PI * 2);
      const index = Math.round(angle / (Math.PI / 8)) % 16;
      const bin = summary.bins[index];
      const percent = Math.round(bin.count / summary.total * 100);
      const average = bin.count ? (bin.speedTotal / bin.count).toFixed(1) : "0.0";
      canvas.title = `${summary.hours} Hours wind rose — ${windDirections[index]} ${percent}% — average ${average} ${metric.wind_speed.unit}`;
    });
    requestAnimationFrame(render);
    if (window.ResizeObserver) new ResizeObserver(render).observe(canvas);
    return card;
  }

  async function loadWeatherHistory() {
    const section = document.querySelector("[data-weather-history]");
    const grid = document.querySelector("[data-weather-metric-grid]");
    const expansionToggle = section?.querySelector("[data-toggle-weather-metrics]");
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
      const cards = Array.from(grid.querySelectorAll(".weather-metric-card"));
      const setExpanded = (expanded) => {
        cards.forEach((card, index) => {
          card.hidden = !expanded && index >= 4;
        });
        if (!expansionToggle) return;
        expansionToggle.setAttribute("aria-expanded", String(expanded));
        expansionToggle.setAttribute("aria-label", expanded ? "Show fewer weather sensor metrics" : "Show all weather sensor metrics");
        const icon = expansionToggle.querySelector("span");
        if (icon) icon.textContent = expanded ? "▼" : "▶";
      };
      if (expansionToggle && cards.length > 4) {
        expansionToggle.hidden = false;
        expansionToggle.onclick = () => setExpanded(expansionToggle.getAttribute("aria-expanded") !== "true");
        setExpanded(false);
      } else if (expansionToggle) {
        expansionToggle.hidden = true;
      }
    } catch (_error) {
      grid.replaceChildren();
      const error = document.createElement("p");
      error.className = "metric-loading metric-error";
      error.textContent = "The 24-hour weather history could not be loaded.";
      grid.append(error);
    }
  }

  loadWeatherHistory();

  function renderSensorOnlineStatus(status) {
    const indicator = document.querySelector("[data-sensor-online-status]");
    const label = indicator?.querySelector("[data-sensor-online-label]");
    if (!indicator || !label) return;
    const online = status?.enabled === true && status?.state === "online";
    indicator.classList.toggle("is-online", online);
    label.textContent = online ? "Online" : status?.state === "offline" ? "Offline" : "Standing by";
  }

  async function refreshSensorOnlineStatus() {
    try {
      const response = await fetch("/api/ecowitt/status", {cache: "no-store"});
      if (!response.ok) throw new Error("gateway status unavailable");
      renderSensorOnlineStatus(await response.json());
    } catch (_error) {
      renderSensorOnlineStatus({state: "offline"});
    }
  }

  refreshSensorOnlineStatus();

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
      Object.entries(payload.display_units || {}).forEach(([field, unit]) => {
        const element = document.querySelector(`[data-reading-field="${field}"]`);
        if (element && field !== "temperature") element.dataset.readingSuffix = unit ? ` ${unit}` : "";
        const unitElement = document.querySelector(`[data-reading-unit="${field}"]`);
        if (unitElement) unitElement.textContent = unit;
      });
      renderCurrentReading(payload.reading, payload.latest_observation_time);
      setDashboardRefreshInterval(Number(payload.poll_interval_seconds), false);
    } catch (_error) {
      // Keep the last displayed reading when a transient refresh fails.
    }
    await refreshSensorOnlineStatus();
    await loadWeatherHistory();
    if (graphDialog?.open && renderedGraphPayload) {
      await renderSelectedFullGraph({silent: true});
    }
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

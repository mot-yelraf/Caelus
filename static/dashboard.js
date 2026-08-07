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
      document.getElementById("mapSunriseTime").textContent = moon.sunrise;
      document.getElementById("mapSunsetTime").textContent = moon.sunset;
      document.getElementById("solarNoonTime").textContent = moon.solar_noon;
      document.getElementById("daylightDuration").textContent = moon.daylight_duration;
      document.getElementById("daylightHours").textContent = moon.daylight_hours ?? "—";
      document.getElementById("sunState").textContent = moon.sun_is_up ? "Sun above horizon" : "Sun below horizon";
      updateDaylightTrack(moon.daylight_progress);
      document.getElementById("lunarUpdated").textContent = `Updated ${moon.updated_at.slice(11, 16)} UTC`;
    } catch (_error) {
      return;
    }
  }

  window.setInterval(refreshAstronomy, 5 * 60 * 1000);
  document.addEventListener("visibilitychange", refreshAstronomy);
})();

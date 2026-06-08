const config = window.FILEDROP_CONFIG;
const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const shareContext = window.FILEDROP_SHARE_CONTEXT || null;
const isShareMode = Boolean(shareContext?.token);
const canEdit = !isShareMode || shareContext.canEdit === true;
const rootLabel = document.body.dataset.rootLabel || "Files";

function logClientError(message, error, context = {}) {
  const details = {
    path: document.body.dataset.currentPath || "",
    url: window.location.href,
    shareMode: isShareMode,
    ...context,
  };
  if (console.groupCollapsed) {
    console.groupCollapsed(`[Filedrop] ${message}`);
    console.error(error);
    console.info("Context", details);
    console.groupEnd();
    return;
  }
  console.error(`[Filedrop] ${message}`, error, details);
}

window.addEventListener("error", (event) => {
  logClientError("Unhandled JavaScript error", event.error || event.message, {
    source: event.filename,
    line: event.lineno,
    column: event.colno,
  });
});

window.addEventListener("unhandledrejection", (event) => {
  logClientError("Unhandled promise rejection", event.reason || "Promise rejected without a reason.");
});

const originalFetch = window.fetch.bind(window);
window.fetch = async (resource, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  const url = typeof resource === "string" ? new URL(resource, window.location.href) : new URL(resource.url);
  if (csrfToken && url.origin === window.location.origin && ["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    options.headers = new Headers(options.headers || {});
    options.headers.set("X-CSRF-Token", csrfToken);
  }
  let response;
  try {
    response = await originalFetch(resource, options);
  } catch (error) {
    logClientError("API request failed before the server responded", error, {
      method,
      requestPath: url.pathname,
    });
    throw error;
  }
  if (url.origin === window.location.origin && url.pathname.startsWith("/api/")) {
    const contentType = response.headers.get("Content-Type") || "";
    if (response.redirected || contentType.includes("text/html")) {
      const message = response.redirected
        ? "Sign in again before using Filedrop."
        : `The server returned a page instead of data for ${url.pathname}.`;
      logClientError("API returned an unexpected page response", new Error(message), {
        method,
        requestPath: url.pathname,
        status: response.status,
        contentType,
        redirected: response.redirected,
      });
      return new Response(JSON.stringify({ message }), {
        status: response.redirected ? 401 : (response.status || 500),
        headers: { "Content-Type": "application/json" },
      });
    }
    if (!response.ok) {
      response.clone().text().then((body) => {
        let parsedBody = body;
        try {
          parsedBody = body ? JSON.parse(body) : {};
        } catch {
          parsedBody = body.slice(0, 1000);
        }
        logClientError("API request returned an error", new Error(`${method} ${url.pathname} returned ${response.status}`), {
          method,
          requestPath: url.pathname,
          status: response.status,
          response: parsedBody,
        });
      }).catch((error) => {
        logClientError("Could not read failed API response", error, {
          method,
          requestPath: url.pathname,
          status: response.status,
        });
      });
    }
  }
  return response;
};
const form = document.querySelector("#upload-form");
const input = document.querySelector("#file-input");
const chooseUploadButton = document.querySelector("#choose-upload-button");
const uploadChoiceMenu = document.querySelector("#upload-choice-menu");
const chooseFilesButton = document.querySelector("#choose-files-button");
const folderInput = document.querySelector("#folder-input");
const chooseFolderButton = document.querySelector("#choose-folder-button");
const status = document.querySelector("#status");
const uploadPanel = document.querySelector("#upload-panel");
const uploadElapsed = document.querySelector("#upload-elapsed");
const toggleUploadPanelButton = document.querySelector("#toggle-upload-panel-button");
const uploadPanelActions = document.querySelector("#upload-panel-actions");
const toastContainer = document.querySelector("#toast-container");
const stopUploadsButton = document.querySelector("#stop-uploads-button");
const clearFailedButton = document.querySelector("#clear-failed-button");
const uploadList = document.querySelector("#upload-list");
const list = document.querySelector("#file-list");
const progressWrap = document.querySelector("#overall-progress-wrap");
const overallLabel = document.querySelector("#overall-label");
const overallPercent = document.querySelector("#overall-percent");
const overallProgress = document.querySelector("#overall-progress");
const settingsToggle = document.querySelector("#settings-toggle");
const settingsPanel = document.querySelector("#settings-panel");
const parallelSlider = document.querySelector("#parallel-uploads");
const parallelValue = document.querySelector("#parallel-value");
const confirmSingleDelete = document.querySelector("#confirm-single-delete");
const confirmBulkDelete = document.querySelector("#confirm-bulk-delete");
const themeSelect = document.querySelector("#theme-select");
const conflictSelect = document.querySelector("#conflict-select");
const fullView = document.querySelector("#full-view");
const fileToolbar = document.querySelector("#file-toolbar");
const selectAllCheckbox = document.querySelector("#select-all-checkbox");
const sortButtons = Array.from(document.querySelectorAll(".sort-button"));
const selectionCount = document.querySelector("#selection-count");
const deleteSelectedButton = document.querySelector("#delete-selected-button");
const breadcrumbs = document.querySelector("#breadcrumbs");
const contextMenu = document.querySelector("#context-menu");
const pageDim = document.querySelector("#page-dim");
const deleteConfirmPopover = document.querySelector("#delete-confirm-popover");
const deleteConfirmTitle = document.querySelector("#delete-confirm-title");
const deleteConfirmMessage = document.querySelector("#delete-confirm-message");
const deleteConfirmCancel = document.querySelector("#delete-confirm-cancel");
const deleteConfirmDelete = document.querySelector("#delete-confirm-delete");
const accountToggle = document.querySelector("#account-toggle");
const accountPanel = document.querySelector("#account-panel");
const notificationsToggle = document.querySelector("#notifications-toggle");
const notificationsPanel = document.querySelector("#notifications-panel");
const notificationsList = document.querySelector("#notifications-list");
const notificationBadge = document.querySelector("#notification-badge");
const shareToggle = document.querySelector("#share-toggle");
const sharePanel = document.querySelector("#share-panel");
const shareAccessButtons = Array.from(document.querySelectorAll("[data-access-mode]"));
const shareEditorsGroup = document.querySelector("#share-editors-group");
const shareEditorsInput = document.querySelector("#share-editors-input");
const shareEditorChips = document.querySelector("#share-editor-chips");
const shareUserSuggestions = document.querySelector("#share-user-suggestions");
const folderPopover = document.querySelector("#folder-popover");
const folderPopoverLabel = document.querySelector("#folder-popover-label");
const folderNameInput = document.querySelector("#folder-name-input");
const folderPopoverCancel = document.querySelector("#folder-popover-cancel");
const renamePopover = document.querySelector("#rename-popover");
const renameInput = document.querySelector("#rename-input");
const renamePopoverCancel = document.querySelector("#rename-popover-cancel");
let renameItemPath;

const accountPreferences = window.FILEDROP_PREFERENCES || {};
const savedParallelUploads = Number.parseInt(accountPreferences.parallelUploads, 10);
const savedConfirmSingleDelete = accountPreferences.confirmSingleDelete;
const savedConfirmBulkDelete = accountPreferences.confirmBulkDelete;
const savedTheme = accountPreferences.theme;
const savedConflictMode = accountPreferences.conflictMode;
let parallelUploads = Number.isInteger(savedParallelUploads)
  ? Math.min(config.maxParallelUploads, Math.max(config.minParallelUploads, savedParallelUploads))
  : config.defaultParallelUploads;
let uploadPanelHideTimer;
let uploadStopwatchTimer;
let uploadStartedAt;
let uploadRunId = 0;
let selectedItems = new Set();
let lastSelectedPath = null;
let currentPath = document.body.dataset.currentPath || "";
let sortBy = ["manual", "name", "modified", "size", "extension"].includes(accountPreferences.sortBy)
  ? accountPreferences.sortBy
  : "manual";
let sortDirection = accountPreferences.sortDirection === "desc" ? "desc" : "asc";
const itemCache = new Map();
const pendingItemLoads = new Map();
const prefetchedFolderPages = new Set();
const pendingUploadItems = new Map();
let activeUploadRun;
let currentShare;
let shareAccessMode = "view";
let shareEditors = [];
let shareSuggestionAbort;
let shareSaveTimer;
let isPopulatingSharePanel = false;

if (!canEdit) {
  form.hidden = true;
  selectAllCheckbox.closest(".select-all-control").hidden = true;
  selectionCount.hidden = true;
  deleteSelectedButton.hidden = true;
}

function closeUploadChoiceMenu() {
  uploadChoiceMenu.hidden = true;
  chooseUploadButton.setAttribute("aria-expanded", "false");
}

chooseUploadButton.addEventListener("click", () => {
  const isOpen = uploadChoiceMenu.hidden;
  uploadChoiceMenu.hidden = !isOpen;
  chooseUploadButton.setAttribute("aria-expanded", String(isOpen));
});

chooseFilesButton.addEventListener("click", () => {
  closeUploadChoiceMenu();
  input.click();
});

chooseFolderButton.addEventListener("click", () => {
  closeUploadChoiceMenu();
  folderInput.click();
});

function updateToastPosition() {
  const bottom = uploadPanel.classList.contains("is-visible") ? uploadPanel.offsetHeight + 28 : 16;
  toastContainer.style.bottom = `${bottom}px`;
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "action-toast";
  toast.textContent = message;
  toastContainer.append(toast);
  updateToastPosition();
  window.requestAnimationFrame(() => toast.classList.add("is-visible"));
  window.setTimeout(() => {
    toast.classList.add("is-removing");
    window.setTimeout(() => toast.remove(), config.animationDurationMs);
  }, config.toastVisibleMs);
}

function showErrorPopup(message) {
  if (!message) {
    return;
  }
  const toast = document.createElement("div");
  toast.className = "action-toast error-toast";
  toast.textContent = message;
  toastContainer.append(toast);
  updateToastPosition();
  window.requestAnimationFrame(() => toast.classList.add("is-visible"));
  window.setTimeout(() => {
    toast.classList.add("is-removing");
    window.setTimeout(() => toast.remove(), config.animationDurationMs);
  }, Math.max(config.toastVisibleMs, 4200));
}

let statusMessage = "";
Object.defineProperty(status, "textContent", {
  get() {
    return statusMessage;
  },
  set(value) {
    statusMessage = String(value || "");
    if (!statusMessage) {
      return;
    }
    if (/could not|failed|required|invalid|error|sign in|missing|cannot|unable|denied|outside/i.test(statusMessage)) {
      showErrorPopup(statusMessage);
    } else {
      showToast(statusMessage);
    }
  },
});

async function responseJson(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    const url = response.url ? new URL(response.url, window.location.href).pathname : "the API";
    logClientError("API response was not valid JSON", new Error(`Could not parse JSON from ${url}`), {
      requestPath: url,
      status: response.status,
      response: text.slice(0, 1000),
    });
    return {
      htmlResponse: true,
      message: response.ok
        ? `The server returned a page instead of data for ${url}.`
        : `The server returned a page instead of data for ${url} (${response.status}).`,
    };
  }
}

new MutationObserver(updateToastPosition).observe(uploadPanel, { attributes: true, attributeFilter: ["class"] });
window.addEventListener("resize", updateToastPosition);

parallelSlider.min = String(config.minParallelUploads);
parallelSlider.max = String(config.maxParallelUploads);
parallelSlider.value = String(parallelUploads);
parallelValue.textContent = String(parallelUploads);
confirmSingleDelete.checked = !(savedConfirmSingleDelete ?? false);
confirmBulkDelete.checked = !(savedConfirmBulkDelete ?? false);
themeSelect.value = ["light", "dark", "system"].includes(savedTheme) ? savedTheme : "system";
conflictSelect.value = savedConflictMode === "replace" ? "replace" : "add";
fullView.checked = accountPreferences.fullView === true;
updateSortButtons();
document.body.classList.toggle("full-view", fullView.checked);
window.FILEDROP_THEME.apply(themeSelect.value);

settingsToggle.addEventListener("click", () => {
  const isOpen = settingsPanel.hidden;
  closeAccountPanel();
  closeSharePanel();
  closeNotificationsPanel();
  settingsPanel.hidden = !isOpen;
  settingsToggle.setAttribute("aria-expanded", String(isOpen));
});

if (accountToggle) {
  accountToggle.addEventListener("click", () => {
    const isOpen = accountPanel.hidden;
    closeSettingsPanel();
    closeSharePanel();
    closeNotificationsPanel();
    accountPanel.hidden = !isOpen;
    accountToggle.setAttribute("aria-expanded", String(isOpen));
  });
}

if (notificationsToggle) {
  notificationsToggle.addEventListener("click", () => {
    const isOpen = notificationsPanel.hidden;
    closeSettingsPanel();
    closeAccountPanel();
    closeSharePanel();
    notificationsPanel.hidden = !isOpen;
    notificationsToggle.setAttribute("aria-expanded", String(isOpen));
    if (isOpen) {
      markNotificationsRead();
    }
  });
}

if (shareToggle) {
  shareToggle.addEventListener("click", () => {
    const isOpen = sharePanel.hidden;
    closeSettingsPanel();
    closeAccountPanel();
    closeNotificationsPanel();
    sharePanel.hidden = !isOpen;
    shareToggle.setAttribute("aria-expanded", String(isOpen));
    if (isOpen) {
      loadCurrentShare();
    }
  });
}

function closeSettingsPanel() {
  settingsPanel.hidden = true;
  settingsToggle.setAttribute("aria-expanded", "false");
}

function closeAccountPanel() {
  if (!accountPanel || !accountToggle) {
    return;
  }
  accountPanel.hidden = true;
  accountToggle.setAttribute("aria-expanded", "false");
}

function closeSharePanel() {
  if (!sharePanel || !shareToggle) {
    return;
  }
  sharePanel.hidden = true;
  shareToggle.setAttribute("aria-expanded", "false");
}

function closeNotificationsPanel() {
  if (!notificationsPanel || !notificationsToggle) {
    return;
  }
  notificationsPanel.hidden = true;
  notificationsToggle.setAttribute("aria-expanded", "false");
}

async function savePreferences(preferences) {
  if (!csrfToken) {
    return;
  }
  try {
    const response = await fetch("/api/preferences", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(preferences),
    });
    if (!response.ok) {
      throw new Error("Preference save failed.");
    }
  } catch {
    status.textContent = "Could not save your preference.";
  }
}

function savePreference(name, value) {
  savePreferences({ [name]: value });
}

parallelSlider.addEventListener("input", () => {
  parallelUploads = Number.parseInt(parallelSlider.value, 10);
  parallelValue.textContent = String(parallelUploads);
  localStorage.setItem(config.storageKeys.parallelUploads, String(parallelUploads));
});

parallelSlider.addEventListener("change", () => {
  savePreference("parallelUploads", parallelUploads);
});

/*
  The account preferences remain mirrored locally where useful so the theme
  can be applied before an authenticated page finishes loading.
*/
confirmSingleDelete.addEventListener("change", () => {
  localStorage.setItem(config.storageKeys.confirmSingleDelete, String(confirmSingleDelete.checked));
  savePreference("confirmSingleDelete", !confirmSingleDelete.checked);
});

confirmBulkDelete.addEventListener("change", () => {
  localStorage.setItem(config.storageKeys.confirmBulkDelete, String(confirmBulkDelete.checked));
  savePreference("confirmBulkDelete", !confirmBulkDelete.checked);
});

themeSelect.addEventListener("change", () => {
  window.FILEDROP_THEME.setPreference(themeSelect.value);
  savePreference("theme", themeSelect.value);
});

conflictSelect.addEventListener("change", () => {
  localStorage.setItem(config.storageKeys.conflictMode, conflictSelect.value);
  savePreference("conflictMode", conflictSelect.value);
});

fullView.addEventListener("change", () => {
  document.body.classList.toggle("full-view", fullView.checked);
  savePreference("fullView", fullView.checked);
});

sortButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const selectedSort = button.dataset.sort;
    if (sortBy === selectedSort && sortDirection === "asc") {
      sortDirection = "desc";
    } else if (sortBy === selectedSort) {
      sortBy = "manual";
      sortDirection = "asc";
    } else {
      sortBy = selectedSort;
      sortDirection = "asc";
    }
    updateSortButtons();
    savePreferences({ sortBy, sortDirection });
    rerenderCurrentItems();
  });
});

function updateSortButtons() {
  sortButtons.forEach((button) => {
    const isActive = button.dataset.sort === sortBy;
    const direction = isActive ? (sortDirection === "asc" ? " ascending" : " descending") : "";
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
    button.textContent = `${button.dataset.label}${direction ? (sortDirection === "asc" ? " ↑" : " ↓") : ""}`;
    button.setAttribute("aria-label", `${button.dataset.label}${direction}`);
  });
}

let currentNotifications = [];

function updateNotificationBadge(unreadCount) {
  if (!notificationBadge || !notificationsToggle) {
    return;
  }
  notificationBadge.hidden = unreadCount <= 0;
  notificationBadge.textContent = String(Math.min(unreadCount, 99));
  notificationsToggle.classList.toggle("has-unread", unreadCount > 0);
}

function renderNotifications(data) {
  if (!notificationsList) {
    return;
  }
  currentNotifications = data.notifications || [];
  notificationsList.innerHTML = "";
  updateNotificationBadge(data.unreadCount || 0);
  if (!currentNotifications.length) {
    const empty = document.createElement("div");
    empty.className = "notification-empty";
    empty.textContent = "No notifications";
    notificationsList.append(empty);
    return;
  }
  currentNotifications.forEach((notification) => {
    const item = document.createElement("div");
    const link = document.createElement("a");
    const title = document.createElement("span");
    const message = document.createElement("span");
    const dismiss = document.createElement("button");
    item.className = "notification-item";
    item.classList.toggle("is-unread", !notification.read);
    link.href = notification.url;
    title.className = "notification-title";
    title.textContent = notification.title;
    message.className = "notification-message";
    message.textContent = notification.message;
    dismiss.type = "button";
    dismiss.className = "notification-dismiss";
    dismiss.textContent = "×";
    dismiss.setAttribute("aria-label", `Dismiss ${notification.title}`);
    dismiss.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await dismissNotification(notification.key);
    });
    link.append(title, message);
    item.append(link, dismiss);
    notificationsList.append(item);
  });
}

async function loadNotifications() {
  if (!notificationsList) {
    return;
  }
  try {
    const response = await fetch("/api/notifications");
    const data = await responseJson(response);
    if (!response.ok) {
      return;
    }
    renderNotifications(data);
  } catch {
    updateNotificationBadge(0);
  }
}

async function markNotificationsRead() {
  const keys = currentNotifications.filter((notification) => !notification.read).map((notification) => notification.key);
  if (!keys.length) {
    updateNotificationBadge(0);
    return;
  }
  currentNotifications = currentNotifications.map((notification) => ({ ...notification, read: true }));
  renderNotifications({ notifications: currentNotifications, unreadCount: 0 });
  try {
    await fetch("/api/notifications/read", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys }),
    });
  } catch {
    loadNotifications();
  }
}

async function dismissNotification(key) {
  try {
    const response = await fetch(`/api/notifications/${encodeURIComponent(key)}`, { method: "DELETE" });
    if (!response.ok) {
      const data = await responseJson(response);
      status.textContent = data.message || "Could not dismiss notification.";
      return;
    }
    currentNotifications = currentNotifications.filter((notification) => notification.key !== key);
    const unreadCount = currentNotifications.reduce((total, notification) => total + (notification.read ? 0 : notification.count || 1), 0);
    renderNotifications({ notifications: currentNotifications, unreadCount });
  } catch {
    status.textContent = "Could not dismiss notification.";
  }
}

function setShareAccessMode(mode, options = {}) {
  const showActive = options.showActive !== false;
  shareAccessMode = mode;
  shareAccessButtons.forEach((button) => {
    const isActive = showActive && button.dataset.accessMode === mode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
  if (shareEditorsGroup) {
    shareEditorsGroup.hidden = mode !== "restricted_edit";
  }
}

function scheduleShareSave() {
  if (!shareToggle || isShareMode || isPopulatingSharePanel) {
    return;
  }
  const path = currentPath;
  const token = currentShare?.token;
  window.clearTimeout(shareSaveTimer);
  shareSaveTimer = window.setTimeout(() => {
    saveShareSettings({ path, token });
  }, 450);
}

function updateShareButtonState() {
  if (!shareToggle) {
    return;
  }
  shareToggle.classList.toggle("is-shared", Boolean(currentShare));
  shareToggle.setAttribute("aria-label", currentShare ? "Manage shared folder" : "Share folder");
}

function renderShareEditors() {
  if (!shareEditorChips) {
    return;
  }
  shareEditorChips.innerHTML = "";
  shareEditors.forEach((editor) => {
    const chip = document.createElement("span");
    const label = document.createElement("span");
    const remove = document.createElement("button");
    chip.className = "share-editor-chip";
    label.textContent = editor.username;
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Remove ${editor.username}`);
    remove.addEventListener("click", () => {
      shareEditors = shareEditors.filter((candidate) => candidate.username.toLowerCase() !== editor.username.toLowerCase());
      renderShareEditors();
      scheduleShareSave();
    });
    chip.append(label, remove);
    shareEditorChips.append(chip);
  });
}

function addShareEditor(user) {
  if (!user?.username || shareEditors.some((editor) => editor.username.toLowerCase() === user.username.toLowerCase())) {
    shareEditorsInput.value = "";
    shareUserSuggestions.hidden = true;
    return;
  }
  shareEditors.push({ id: user.id, username: user.username });
  shareEditorsInput.value = "";
  shareUserSuggestions.hidden = true;
  renderShareEditors();
  scheduleShareSave();
}

async function loadShareSuggestions(query) {
  if (!shareUserSuggestions) {
    return;
  }
  shareSuggestionAbort?.abort();
  if (!query.trim()) {
    shareUserSuggestions.hidden = true;
    shareUserSuggestions.innerHTML = "";
    return;
  }
  const controller = new AbortController();
  shareSuggestionAbort = controller;
  try {
    const response = await fetch(`/api/users/search?q=${encodeURIComponent(query.trim())}`, { signal: controller.signal });
    const data = await responseJson(response);
    if (!response.ok) {
      return;
    }
    const selected = new Set(shareEditors.map((editor) => editor.username.toLowerCase()));
    const users = (data.users || []).filter((user) => !selected.has(user.username.toLowerCase()));
    shareUserSuggestions.innerHTML = "";
    users.forEach((user) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = user.username;
      button.addEventListener("click", () => addShareEditor(user));
      shareUserSuggestions.append(button);
    });
    shareUserSuggestions.hidden = users.length === 0;
  } catch (error) {
    if (error.name !== "AbortError") {
      shareUserSuggestions.hidden = true;
    }
  }
}

function populateSharePanel(share) {
  isPopulatingSharePanel = true;
  currentShare = share || null;
  setShareAccessMode(currentShare?.accessMode || "view", { showActive: Boolean(currentShare) });
  shareEditors = currentShare?.editors ? [...currentShare.editors] : [];
  renderShareEditors();
  updateShareButtonState();
  isPopulatingSharePanel = false;
}

async function loadCurrentShare() {
  if (!shareToggle || isShareMode) {
    return;
  }
  try {
    const response = await fetch(`/api/shares/current?path=${encodeURIComponent(currentPath)}`);
    const data = await responseJson(response);
    if (!response.ok) {
      return;
    }
    populateSharePanel(data.share);
  } catch {
    updateShareButtonState();
  }
}

shareAccessButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const selectedMode = button.dataset.accessMode;
    if (currentShare && shareAccessMode === selectedMode) {
      removeCurrentShare();
      return;
    }
    window.clearTimeout(shareSaveTimer);
    shareSaveTimer = undefined;
    setShareAccessMode(selectedMode);
    saveShareSettings();
  });
});

if (shareEditorsInput) {
  shareEditorsInput.addEventListener("input", () => loadShareSuggestions(shareEditorsInput.value));
  shareEditorsInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const firstSuggestion = shareUserSuggestions.querySelector("button");
      if (firstSuggestion) {
        firstSuggestion.click();
      }
    } else if (event.key === "Backspace" && !shareEditorsInput.value && shareEditors.length) {
      shareEditors.pop();
      renderShareEditors();
      scheduleShareSave();
    }
  });
}

async function saveShareSettings(options = {}) {
  const path = options.path ?? currentPath;
  const token = options.token ?? currentShare?.token;
  const wasExistingShare = Boolean(token);
  if (wasExistingShare && currentShare?.token !== token) {
    return;
  }
  try {
    const body = JSON.stringify({
      path,
      accessMode: shareAccessMode,
      editors: shareEditors.map((editor) => editor.username),
    });
    const response = await fetch(wasExistingShare ? `/api/shares/${encodeURIComponent(token)}` : "/api/shares", {
      method: wasExistingShare ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    const data = await responseJson(response);
    if (!response.ok) {
      status.textContent = data.message || "Could not save share settings.";
      return;
    }
    if (path === currentPath) {
      populateSharePanel(data);
    } else {
      loadCurrentShare();
    }
    status.textContent = wasExistingShare ? "Share settings saved." : "Share link created.";
  } catch {
    status.textContent = "Could not save share settings.";
  }
}

async function removeCurrentShare() {
  if (!currentShare) {
    return;
  }
  window.clearTimeout(shareSaveTimer);
  shareSaveTimer = undefined;
  const token = currentShare.token;
  try {
    const response = await fetch(`/api/shares/${encodeURIComponent(token)}`, { method: "DELETE" });
    if (!response.ok) {
      const data = await responseJson(response);
      status.textContent = data.message || "Could not remove share link.";
      return;
    }
    populateSharePanel(null);
    status.textContent = "Share link removed.";
  } catch {
    status.textContent = "Could not remove share link.";
  }
}

deleteSelectedButton.addEventListener("click", () => {
  deleteSelectedItems(deleteSelectedButton);
});

selectAllCheckbox.addEventListener("change", () => {
  const paths = visibleItemPaths();
  selectedItems = selectAllCheckbox.checked ? new Set(paths) : new Set();
  lastSelectedPath = paths.length ? paths[paths.length - 1] : null;
  updateSelectionControls();
});

clearFailedButton.addEventListener("click", () => {
  uploadList.querySelectorAll(".upload-item.is-failed").forEach((row, index) => {
    window.setTimeout(() => {
      removeWithSwipe(row, () => {
        updateFailedControls();
        hideUploadPanelIfEmpty(uploadRunId);
      });
    }, index * 70);
  });
});

stopUploadsButton.addEventListener("click", () => {
  if (activeUploadRun) {
    stopUploadRun(activeUploadRun);
  }
});

toggleUploadPanelButton.addEventListener("click", () => {
  setUploadPanelCollapsed(!uploadPanel.classList.contains("is-collapsed"));
});

function updateBreadcrumbs() {
  breadcrumbs.innerHTML = "";
  const segments = currentPath ? currentPath.split("/") : [];
  const crumbs = [{ label: rootLabel, path: "" }];

  segments.forEach((segment, index) => {
    crumbs.push({ label: segment, path: segments.slice(0, index + 1).join("/") });
  });

  crumbs.forEach((crumb, index) => {
    if (index) {
      const separator = document.createElement("span");
      separator.className = "breadcrumb-separator";
      separator.textContent = "/";
      breadcrumbs.append(separator);
    }

    if (index === crumbs.length - 1) {
      const current = document.createElement("span");
      current.className = "breadcrumb-current";
      current.textContent = crumb.label;
      addFolderDropTarget(current, crumb.path);
      breadcrumbs.append(current);
      return;
    }

    const link = document.createElement("button");
    link.type = "button";
    link.className = "breadcrumb-link";
    link.textContent = crumb.label;
    link.addEventListener("click", () => navigateToFolder(crumb.path));
    link.addEventListener("mouseenter", () => preloadFolderForNavigation(crumb.path));
    link.addEventListener("focus", () => preloadFolderForNavigation(crumb.path));
    link.addEventListener("pointerdown", () => preloadFolderForNavigation(crumb.path));
    addFolderDropTarget(link, crumb.path);
    breadcrumbs.append(link);
  });

}

function folderUrl(path) {
  if (isShareMode) {
    const base = `/s/${encodeURIComponent(shareContext.token)}`;
    if (!path) {
      return base;
    }
    return `${base}/browse/${path.split("/").map(encodeURIComponent).join("/")}`;
  }
  if (!path) {
    return "/";
  }

  return `/browse/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function apiBase(path) {
  if (!isShareMode) {
    return `/api${path}`;
  }
  return `/api/shares/${encodeURIComponent(shareContext.token)}${path}`;
}

function encodedPath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

function navigateToFolder(path) {
  if (path === currentPath) {
    return;
  }
  currentPath = path;
  document.body.dataset.currentPath = currentPath;
  window.history.pushState({ path }, "", folderUrl(path));
  loadCurrentShare();
  loadItems();
}

function hideContextMenu() {
  contextMenu.hidden = true;
  contextMenu.classList.remove("is-open");
  contextMenu.innerHTML = "";
}

let activeDeleteConfirmation;

function closeDeleteConfirmation(result = false) {
  if (!activeDeleteConfirmation) {
    return;
  }
  const { resolve } = activeDeleteConfirmation;
  activeDeleteConfirmation = undefined;
  if (deleteConfirmPopover) {
    deleteConfirmPopover.hidden = true;
  }
  if (pageDim) {
    pageDim.hidden = true;
  }
  resolve(result);
}

function positionDeleteConfirmation(anchor) {
  if (!deleteConfirmPopover || !anchor) {
    return;
  }
  const rect = anchor.getBoundingClientRect();
  const margin = 10;
  const width = deleteConfirmPopover.offsetWidth;
  const height = deleteConfirmPopover.offsetHeight;
  const rightSide = rect.right + margin;
  const leftSide = rect.left - width - margin;
  const left = rightSide + width <= window.innerWidth - margin ? rightSide : Math.max(margin, leftSide);
  const centeredTop = rect.top + (rect.height / 2) - (height / 2);
  const top = Math.min(Math.max(margin, centeredTop), window.innerHeight - height - margin);
  deleteConfirmPopover.style.left = `${left}px`;
  deleteConfirmPopover.style.top = `${top}px`;
}

function confirmDeleteAction({ anchor, title, message, deleteLabel = "Delete" }) {
  closeDeleteConfirmation(false);
  if (!pageDim || !deleteConfirmPopover || !deleteConfirmTitle || !deleteConfirmMessage || !deleteConfirmDelete) {
    const error = new Error("Delete confirmation markup is missing. Refresh the page and try again.");
    logClientError("Delete confirmation could not open", error, {
      missingMarkup: true,
    });
    status.textContent = error.message;
    return Promise.resolve(false);
  }
  return new Promise((resolve) => {
    activeDeleteConfirmation = { resolve };
    deleteConfirmTitle.textContent = title;
    deleteConfirmMessage.textContent = message;
    deleteConfirmDelete.textContent = deleteLabel;
    pageDim.hidden = false;
    deleteConfirmPopover.hidden = false;
    positionDeleteConfirmation(anchor);
    deleteConfirmDelete.focus();
  });
}

deleteConfirmCancel?.addEventListener("click", () => closeDeleteConfirmation(false));
deleteConfirmDelete?.addEventListener("click", () => closeDeleteConfirmation(true));
pageDim?.addEventListener("click", () => closeDeleteConfirmation(false));

function showContextMenu(item, x, y) {
  hideContextMenu();
  const actions = [];
  const selectedCount = selectedItems.size;

  if (canEdit) {
    if (selectedCount) {
      actions.push({ label: `New folder (${selectedCount})`, action: (button) => { openFolderPopover(button, true); } });
    } else {
      actions.push({ label: "New folder", action: (button) => { openFolderPopover(button, false); } });
    }
  }

  if (item?.type === "folder") {
    actions.push({ label: "Open", action: () => { navigateToFolder(item.path); } });
  } else if (item?.type === "file") {
    actions.push({
      label: "Download",
      action: () => {
        showToast(`Download started for ${item.name}.`);
        window.location.assign(fileUrl(item.path));
      },
    });
  }

  if (item && canEdit) {
    actions.push({ label: "Rename", action: (button) => { openRenamePopover(button, item); } });
    actions.push({ label: "Delete", action: (button) => { deleteItem(item, button); }, className: "delete" });
  }

  if (!actions.length) {
    return;
  }

  actions.forEach((action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = action.label;
    button.className = action.className || "";
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      action.action(button);
      hideContextMenu();
    });
    contextMenu.append(button);
  });

  contextMenu.hidden = false;
  contextMenu.classList.add("is-open");
  const width = contextMenu.offsetWidth || config.contextMenuFallbackWidth;
  const height = contextMenu.offsetHeight || config.contextMenuFallbackHeight;
  const maxX = Math.max(config.contextMenuMargin, window.innerWidth - width - config.contextMenuMargin);
  const maxY = Math.max(config.contextMenuMargin, window.innerHeight - height - config.contextMenuMargin);

  contextMenu.style.left = `${Math.min(x, maxX)}px`;
  contextMenu.style.top = `${Math.min(y, maxY)}px`;
}

function setSelectedItems(nextSelectedItems, nextLastSelectedPath = lastSelectedPath) {
  selectedItems = nextSelectedItems;
  lastSelectedPath = nextLastSelectedPath;
  updateSelectionControls();
}

function rowSelectionMode(path, index, event, options = {}) {
  const isRangeSelection = event.shiftKey && lastSelectedPath !== null;
  const isCheckboxSelection = Boolean(options.checkbox);
  const isToggleSelection = event.metaKey || event.ctrlKey;

  if (isRangeSelection) {
    const anchor = document.querySelector(`li[data-path="${CSS.escape(lastSelectedPath)}"]`);
    if (!anchor) {
      selectedItems = new Set([path]);
      lastSelectedPath = path;
      updateSelectionControls();
      return;
    }
    const start = Number(anchor.dataset.index);
    const end = index;
    const rows = Array.from(list.querySelectorAll("li.file-row"));
    const startIndex = Math.min(start, end);
    const endIndex = Math.max(start, end);

    rows.forEach((row) => {
      const rowIndex = Number(row.dataset.index);
      if (rowIndex >= startIndex && rowIndex <= endIndex) {
        selectedItems.add(row.dataset.path);
      }
    });
  } else if (isToggleSelection) {
    if (selectedItems.has(path)) {
      selectedItems.delete(path);
    } else {
      selectedItems.add(path);
    }
    lastSelectedPath = path;
  } else if (isCheckboxSelection) {
    if (options.checked) {
      selectedItems.add(path);
    } else {
      selectedItems.delete(path);
    }
    lastSelectedPath = path;
  } else if (selectedItems.has(path)) {
    selectedItems.delete(path);
    lastSelectedPath = selectedItems.size ? Array.from(selectedItems).at(-1) : null;
  } else {
    selectedItems = new Set([path]);
    lastSelectedPath = path;
  }

  updateSelectionControls();
}

function itemRequestUrl(path) {
  const query = path ? `?path=${encodeURIComponent(path)}` : "";
  return `${apiBase("/items")}${query}`;
}

async function fetchItems(path, options = {}) {
  const force = Boolean(options.force);

  if (!force && itemCache.has(path)) {
    return itemCache.get(path);
  }

  if (!force && pendingItemLoads.has(path)) {
    return pendingItemLoads.get(path);
  }

  const request = fetch(itemRequestUrl(path))
    .then(async (response) => {
      const data = await responseJson(response);

      if (!response.ok) {
        throw new Error(data.message || "Could not load items.");
      }

      itemCache.set(path, data);
      return data;
    })
    .finally(() => {
      pendingItemLoads.delete(path);
    });

  pendingItemLoads.set(path, request);
  return request;
}

function preloadFolder(path) {
  if (itemCache.has(path) || pendingItemLoads.has(path)) {
    return;
  }

  fetchItems(path).catch(() => {});
}

function prefetchFolderPage(path) {
  const url = folderUrl(path);
  if (prefetchedFolderPages.has(url)) {
    return;
  }
  prefetchedFolderPages.add(url);
  fetch(url, {
    cache: "force-cache",
    credentials: "same-origin",
    headers: { "X-Filedrop-Prefetch": "1" },
  }).catch(() => {
    prefetchedFolderPages.delete(url);
  });
}

function preloadFolderForNavigation(path) {
  prefetchFolderPage(path);
  preloadFolder(path);
}

function parentFolderPaths(path) {
  const segments = path ? path.split("/") : [];
  const parents = [""];
  segments.slice(0, -1).forEach((_segment, index) => {
    parents.push(segments.slice(0, index + 1).join("/"));
  });
  return parents;
}

function preloadParentFoldersAfterRender() {
  const parents = parentFolderPaths(currentPath);
  const preloadParents = () => {
    parents.forEach(preloadFolder);
  };
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(preloadParents);
  } else {
    window.setTimeout(preloadParents, config.parentPreloadFallbackDelayMs);
  }
}

function folderPathsFromSelection() {
  return Array.from(selectedItems).filter((path) => {
    return list.querySelector(`li[data-path="${CSS.escape(path)}"][data-type="folder"]`);
  });
}

function preloadSelectedFolders() {
  folderPathsFromSelection().forEach(preloadFolder);
}

function preloadVisibleFolders(items) {
  const folders = items.filter((item) => item.type === "folder" && !item.pendingUpload);
  if (folders.length < config.preloadAllFolderLimit) {
    folders.forEach((item) => preloadFolder(item.path));
  } else {
    preloadSelectedFolders();
  }
}

function preloadFolderForHover(path) {
  prefetchFolderPage(path);
  const selectedFolders = folderPathsFromSelection();
  if (selectedFolders.length) {
    selectedFolders.forEach(preloadFolder);
  } else {
    preloadFolder(path);
  }
}

function invalidateFolder(path) {
  itemCache.delete(path || "");
}

function uploadParentPath(path) {
  const segments = path ? path.split("/") : [];
  return segments.slice(0, -1).join("/");
}

function pendingChildren(path) {
  return Array.from(pendingUploadItems.values()).filter((item) => uploadParentPath(item.path) === path);
}

function mergedFolderItems(data) {
  const items = new Map(data.items.map((item) => [item.path, item]));
  const pending = pendingChildren(data.path || "");
  pending
    .sort((left, right) => {
      if (left.type !== right.type) {
        return left.type === "folder" ? -1 : 1;
      }
      return left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" });
    })
    .forEach((item) => items.set(item.path, item));
  return { ...data, items: Array.from(items.values()) };
}

function renderCurrentFolder() {
  const data = itemCache.get(currentPath) || { items: [], path: currentPath, parent: uploadParentPath(currentPath) };
  list.innerHTML = "";
  list.className = "";
  renderItems(data);
}

function renderItems(data) {
  status.textContent = "";
  data = mergedFolderItems(data);

  if (!data.items.length) {
    showEmptyFileList();
    return;
  }

  const items = sortedItems(data.items);

  items.forEach((item, index) => {
    const row = document.createElement("li");
    const checkbox = document.createElement("input");
    const preview = document.createElement("div");
    const label = document.createElement("div");
    const name = document.createElement("span");
    const actions = document.createElement("div");

    row.className = "file-row";
    row.dataset.path = item.path;
    row.dataset.index = String(index);
    row.dataset.type = item.type;
    row.classList.toggle("is-pending-upload", Boolean(item.pendingUpload));
    row.draggable = canEdit && !item.pendingUpload;
    row.addEventListener("dragstart", (event) => {
      if (!canEdit) {
        event.preventDefault();
        return;
      }
      if (!selectedItems.has(item.path)) {
        setSelectedItems(new Set([item.path]), item.path);
      }
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData(config.draggedItemsType, JSON.stringify(Array.from(selectedItems)));
    });

    checkbox.type = "checkbox";
    checkbox.className = "select-file-checkbox";
    checkbox.disabled = !canEdit || Boolean(item.pendingUpload);
    checkbox.hidden = !canEdit;
    checkbox.setAttribute("aria-label", `Select ${item.name}`);
    checkbox.addEventListener("click", (event) => {
      event.stopPropagation();
      rowSelectionMode(item.path, index, event, { checkbox: true, checked: checkbox.checked });
    });

    name.className = "item-name";
    name.textContent = item.name;
    label.className = "item-label";
    label.append(name);
    const detailText = item.pendingUpload ? "Pending upload" : sortDetail(item);
    if (detailText) {
      const detail = document.createElement("span");
      detail.className = "item-sort-detail";
      detail.textContent = detailText;
      label.append(detail);
    }

    actions.className = "item-actions";

    if (item.type === "folder") {
      const openButton = document.createElement("button");
      openButton.type = "button";
      openButton.className = "item-action-button open";
      openButton.textContent = "Open";
      openButton.addEventListener("click", (event) => {
        event.stopPropagation();
        navigateToFolder(item.path);
      });
      openButton.addEventListener("mouseenter", () => {
        if (!item.pendingUpload) {
          preloadFolderForNavigation(item.path);
        }
      });
      openButton.addEventListener("focus", () => {
        if (!item.pendingUpload) {
          preloadFolderForNavigation(item.path);
        }
      });
      openButton.addEventListener("pointerdown", () => {
        if (!item.pendingUpload) {
          preloadFolderForNavigation(item.path);
        }
      });
      actions.append(openButton);

      if (!item.pendingUpload) {
        row.addEventListener("mouseenter", () => {
          preloadFolderForHover(item.path);
        });

        row.addEventListener("focusin", () => {
          preloadFolderForHover(item.path);
        });
      }

    } else if (!item.pendingUpload) {
      const downloadLink = document.createElement("a");
      downloadLink.className = "item-action-link";
      downloadLink.href = fileUrl(item.path);
      downloadLink.textContent = "Download";
      downloadLink.addEventListener("click", (event) => {
        event.stopPropagation();
        showToast(`Download started for ${item.name}.`);
      });
      actions.append(downloadLink);
    }

    if (canEdit) {
      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "item-action-button delete";
      removeButton.textContent = "×";
      removeButton.setAttribute("aria-label", `${item.pendingUpload ? "Cancel upload" : "Delete"} ${item.name}`);
      removeButton.addEventListener("click", (event) => {
        event.stopPropagation();
        if (item.pendingUpload) {
          cancelPendingUploadPath(item.path);
        } else {
          deleteItem(item, removeButton);
        }
      });
      actions.append(removeButton);
    }

    row.addEventListener("click", (event) => {
      if (event.target.closest(".item-action-button, .item-action-link")) {
        return;
      }
      if (item.pendingUpload) {
        return;
      }
      rowSelectionMode(item.path, index, event);
    });

    preview.className = "item-preview";
    if (item.type === "folder") {
      preview.classList.add("folder");
      preview.setAttribute("aria-label", "Folder");
    } else if (item.preview === "image") {
      const image = document.createElement("img");
      image.loading = "lazy";
      image.alt = "";
      image.src = previewUrl(item.path);
      image.addEventListener("error", () => showFilePreviewFallback(preview));
      preview.append(image);
    } else if (item.preview === "video") {
      const video = document.createElement("video");
      video.preload = "metadata";
      video.muted = true;
      video.src = previewUrl(item.path);
      video.addEventListener("error", () => showFilePreviewFallback(preview));
      preview.append(video);
    } else {
      preview.classList.add("file");
      preview.textContent = "·";
    }

    row.addEventListener("dblclick", (event) => {
      if (event.target.closest(".item-action-button, .item-action-link, .select-file-checkbox")) {
        return;
      }
      if (item.type === "folder") {
        navigateToFolder(item.path);
      } else {
        showToast(`Download started for ${item.name}.`);
        window.location.assign(fileUrl(item.path));
      }
    });

    row.addEventListener("contextmenu", (event) => {
      if (item.pendingUpload) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      if (!selectedItems.has(item.path)) {
        setSelectedItems(new Set([item.path]), item.path);
      }
      showContextMenu(item, event.clientX, event.clientY);
    });

    if (canEdit && !item.pendingUpload) {
      addRowDropTarget(row, item);
    }
    row.append(checkbox, preview, label, actions);
    list.append(row);
  });

  updateSelectionControls();
  preloadVisibleFolders(items);
  preloadParentFoldersAfterRender();
}

function rerenderCurrentItems() {
  const data = itemCache.get(currentPath);
  if (!data) {
    return;
  }
  list.innerHTML = "";
  list.className = "";
  renderItems(data);
}

function compareNames(left, right) {
  return left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" });
}

function compareOptional(left, right, compare) {
  const leftMissing = left === null || left === undefined || left === "";
  const rightMissing = right === null || right === undefined || right === "";
  if (leftMissing || rightMissing) {
    return leftMissing === rightMissing ? 0 : (leftMissing ? 1 : -1);
  }
  return compare(left, right) * (sortDirection === "desc" ? -1 : 1);
}

function sortedItems(items) {
  if (sortBy === "manual") {
    return [...items].sort((left, right) => {
      if (left.type === right.type) {
        return 0;
      }
      return left.type === "folder" ? -1 : 1;
    });
  }
  return [...items].sort((left, right) => {
    if (left.type !== right.type) {
      return left.type === "folder" ? -1 : 1;
    }
    let comparison = 0;
    if (sortBy === "name") {
      comparison = compareOptional(left.name, right.name, (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
    } else if (sortBy === "modified") {
      comparison = compareOptional(left.modifiedAt, right.modifiedAt, (a, b) => a - b);
    } else if (left.type === "file" && sortBy === "size") {
      comparison = compareOptional(left.size, right.size, (a, b) => a - b);
    } else if (left.type === "file" && sortBy === "extension") {
      comparison = compareOptional(left.extension, right.extension, (a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
    }
    if (comparison) {
      return comparison;
    }
    return compareNames(left, right) * (sortDirection === "desc" ? -1 : 1);
  });
}

function formatBytes(bytes) {
  if (bytes === 0) {
    return "0 bytes";
  }
  const units = ["bytes", "KB", "MB", "GB", "TB"];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / (1024 ** unitIndex);
  return `${value.toFixed(unitIndex ? 1 : 0)} ${units[unitIndex]}`;
}

function sortDetail(item) {
  if (sortBy === "modified" && item.modifiedAt !== null && item.modifiedAt !== undefined) {
    return new Date(item.modifiedAt * 1000).toLocaleString();
  }
  if (sortBy === "size" && item.type === "file" && item.size !== null && item.size !== undefined) {
    return formatBytes(item.size);
  }
  if (sortBy === "extension" && item.type === "file" && item.extension) {
    return `.${item.extension}`;
  }
  return "";
}

function previewUrl(path) {
  return `${apiBase("/previews")}/${encodedPath(path)}`;
}

function fileUrl(path) {
  return `${apiBase("/files")}/${encodedPath(path)}`;
}

function showFilePreviewFallback(preview) {
  preview.replaceChildren();
  preview.classList.add("file");
  preview.textContent = "·";
}

async function saveVisibleOrder() {
  if (sortBy !== "manual") {
    return;
  }
  const paths = visibleItemPaths();
  const cachedItems = itemCache.get(currentPath)?.items || [];
  const itemsByPath = new Map(cachedItems.map((item) => [item.path, item]));
  try {
    const response = await fetch(apiBase("/items/order"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentPath, paths }),
    });
    if (!response.ok) {
      const data = await responseJson(response);
      status.textContent = data.message || "Could not save item order.";
      await loadItems({ force: true });
      return;
    }
    invalidateFolder(currentPath);
    itemCache.set(currentPath, { items: paths.map((path) => itemsByPath.get(path)).filter(Boolean), path: currentPath });
    status.textContent = "Saved item order.";
  } catch {
    status.textContent = "Could not save item order.";
  }
}

function rowDropMode(row, item, event) {
  const rect = row.getBoundingClientRect();
  const position = (event.clientY - rect.top) / rect.height;
  if (position < config.reorderEdgeRatio) {
    return "before";
  }
  if (position > 1 - config.reorderEdgeRatio) {
    return "after";
  }
  return item.type === "folder" ? "folder" : "after";
}

function clearRowDropTarget(row) {
  row.classList.remove("is-reorder-before", "is-reorder-after");
  clearDropTarget(row);
}

function clearAllRowDropTargets() {
  list.querySelectorAll(".is-reorder-before, .is-reorder-after").forEach((row) => {
    row.classList.remove("is-reorder-before", "is-reorder-after");
  });
}

function addRowDropTarget(row, item) {
  row.addEventListener("dragover", (event) => {
    if (!hasDraggedFiles(event) && !hasDraggedItems(event)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    clearAllRowDropTargets();
    const mode = sortBy === "manual" ? rowDropMode(row, item, event) : (item.type === "folder" ? "folder" : "sorted");
    if (mode === "folder") {
      setDropTarget(row);
    } else {
      clearDropTarget();
      if (hasDraggedItems(event) && mode !== "sorted") {
        row.classList.add(mode === "before" ? "is-reorder-before" : "is-reorder-after");
      }
    }
    event.dataTransfer.dropEffect = hasDraggedItems(event) ? "move" : "copy";
  });
  row.addEventListener("dragleave", (event) => {
    if (event.relatedTarget && row.contains(event.relatedTarget)) {
      return;
    }
    clearRowDropTarget(row);
  });
  row.addEventListener("drop", (event) => {
    const paths = draggedItemPaths(event);
    const uploadSelection = paths.length ? null : uploadSelectionFromDrop(event);
    if (!paths.length && !hasDraggedFiles(event)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const mode = sortBy === "manual" ? rowDropMode(row, item, event) : (item.type === "folder" ? "folder" : "sorted");
    clearRowDropTarget(row);
    if (mode === "folder") {
      if (paths.length) {
        moveItems(paths, item.path);
      } else {
        startDroppedUploads(uploadSelection, item.path);
      }
      return;
    }
    if (!paths.length) {
      startDroppedUploads(uploadSelection, currentPath);
      return;
    }
    if (mode === "sorted") {
      return;
    }
    if (paths.includes(row.dataset.path)) {
      return;
    }
    const draggedPaths = new Set(paths);
    const draggedRows = Array.from(list.querySelectorAll("li.file-row"))
      .filter((candidate) => draggedPaths.has(candidate.dataset.path));
    let reference = mode === "after" ? row.nextElementSibling : row;
    while (reference && draggedPaths.has(reference.dataset.path)) {
      reference = reference.nextElementSibling;
    }
    draggedRows.forEach((draggedRow) => list.insertBefore(draggedRow, reference));
    updateRowIndexes();
    saveVisibleOrder();
  });
}

function updateRowIndexes() {
  list.querySelectorAll("li.file-row").forEach((row, index) => {
    row.dataset.index = String(index);
  });
}

async function loadItems(options = {}) {
  const requestedPath = currentPath;
  updateBreadcrumbs();
  list.innerHTML = "";
  list.className = "";
  selectedItems = new Set();
  lastSelectedPath = null;
  updateSelectionControls();

  if (!options.force && itemCache.has(requestedPath)) {
    renderItems(itemCache.get(requestedPath));
    return;
  }

  try {
    const data = await fetchItems(requestedPath, options);

    if (requestedPath !== currentPath) {
      return;
    }

    renderItems(data);
  } catch (error) {
    if (pendingChildren(requestedPath).length) {
      renderItems({ items: [], path: requestedPath, parent: uploadParentPath(requestedPath) });
    } else {
      status.textContent = error.message || "Could not load items.";
      showEmptyFileList();
    }
  }
}

function syncItemSelectionView() {
  const rows = Array.from(list.querySelectorAll("li.file-row"));

  rows.forEach((row) => {
    const isSelected = selectedItems.has(row.dataset.path);
    const checkbox = row.querySelector(".select-file-checkbox");

    row.classList.toggle("is-selected", isSelected);

    if (checkbox) {
      checkbox.checked = isSelected;
    }
  });

  const selectedVisibleCount = rows.filter((row) => selectedItems.has(row.dataset.path)).length;
  selectAllCheckbox.disabled = rows.length === 0;
  selectAllCheckbox.checked = rows.length > 0 && selectedVisibleCount === rows.length;
  selectAllCheckbox.indeterminate = selectedVisibleCount > 0 && selectedVisibleCount < rows.length;
}

function visibleItemPaths() {
  return Array.from(list.querySelectorAll("li.file-row:not(.is-pending-upload)")).map((row) => row.dataset.path);
}

function visibleItemNames() {
  return new Set(
    Array.from(list.querySelectorAll("li.file-row:not(.is-pending-upload) .item-name"))
      .map((element) => element.textContent)
      .filter(Boolean)
  );
}

function updateSelectionControls() {
  syncItemSelectionView();
  selectionCount.textContent = `${selectedItems.size} selected`;
  deleteSelectedButton.disabled = selectedItems.size === 0;
  preloadSelectedFolders();
}

function showEmptyFileList() {
  const empty = document.createElement("li");
  empty.className = "empty";
  empty.textContent = currentPath ? "This folder is empty." : "No files or folders uploaded yet.";
  list.className = "empty-list";
  list.append(empty);
}

function closeFolderPopover() {
  folderPopover.hidden = true;
  folderPopover.removeAttribute("data-selection");
}

function closeRenamePopover() {
  renamePopover.hidden = true;
  renameItemPath = undefined;
}

function positionFolderPopover(anchor) {
  positionPopover(folderPopover, anchor);
}

function openFolderPopover(anchor, includeSelection) {
  folderPopover.dataset.selection = String(includeSelection);
  folderPopoverLabel.textContent = includeSelection ? "Create a folder for selected items" : "Create a new folder";
  folderNameInput.value = availableFolderName();
  folderPopover.hidden = false;
  positionFolderPopover(anchor);
  folderNameInput.focus();
  folderNameInput.select();
}

function openRenamePopover(anchor, item) {
  renameItemPath = item.path;
  renameInput.value = item.name;
  renamePopover.hidden = false;
  positionPopover(renamePopover, anchor);
  renameInput.focus();
  renameInput.select();
}

function positionPopover(popover, anchor) {
  const rect = anchor.getBoundingClientRect();
  const margin = 8;
  const width = popover.offsetWidth;
  const height = popover.offsetHeight;
  const left = Math.min(rect.left, window.innerWidth - width - margin);
  const below = rect.bottom + margin;
  const top = below + height <= window.innerHeight ? below : Math.max(margin, rect.top - height - margin);
  popover.style.left = `${Math.max(margin, left)}px`;
  popover.style.top = `${top}px`;
}

function availableFolderName() {
  const names = new Set(
    Array.from(list.querySelectorAll("li.file-row")).map((row) => row.querySelector(".item-name")?.textContent)
  );
  if (!names.has("New folder")) {
    return "New folder";
  }
  let counter = 1;
  while (names.has(`New folder (${counter})`)) {
    counter += 1;
  }
  return `New folder (${counter})`;
}

async function createFolder(folderName) {
  const trimmedName = folderName.trim();

  if (!trimmedName) {
    status.textContent = "Folder names must include at least one visible character.";
    return;
  }

  try {
    const response = await fetch(apiBase("/folders"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name: trimmedName, path: currentPath }),
    });

    const data = await responseJson(response);

    if (!response.ok) {
      status.textContent = data.message || "Could not create folder.";
      return;
    }

    invalidateFolder(currentPath);
    status.textContent = `Created ${data.name}.`;
    showToast(`Created folder ${data.name}.`);
    closeFolderPopover();
    await loadItems({ force: true });
  } catch {
    status.textContent = "Could not create folder.";
  }
}

async function createFolderFromSelection(folderName) {
  const trimmedName = folderName.trim();
  if (!trimmedName) {
    status.textContent = "Folder names must include at least one visible character.";
    return;
  }
  try {
    const response = await fetch(apiBase("/folders/from-selection"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: trimmedName,
        path: currentPath,
        paths: Array.from(selectedItems),
        replace: conflictSelect.value === "replace",
      }),
    });
    const data = await responseJson(response);
    if (!response.ok) {
      status.textContent = data.message || "Could not create folder.";
      return;
    }
    invalidateFolder(currentPath);
    selectedItems = new Set();
    status.textContent = `Created ${data.folder.name} with ${data.moved} item${data.moved === 1 ? "" : "s"}.`;
    showToast(`Created folder ${data.folder.name} with ${data.moved} item${data.moved === 1 ? "" : "s"}.`);
    closeFolderPopover();
    invalidateFolder(data.folder.path);
    await loadItems({ force: true });
  } catch {
    status.textContent = "Could not create folder.";
  }
}

folderPopover.addEventListener("submit", (event) => {
  event.preventDefault();
  if (folderPopover.dataset.selection === "true") {
    createFolderFromSelection(folderNameInput.value);
  } else {
    createFolder(folderNameInput.value);
  }
});

folderPopoverCancel.addEventListener("click", closeFolderPopover);

renamePopover.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = renameInput.value.trim();
  if (!name) {
    status.textContent = "Names must include at least one visible character.";
    return;
  }
  try {
    const response = await fetch(apiBase("/items"), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: renameItemPath, name }),
    });
    const data = await responseJson(response);
    if (!response.ok) {
      status.textContent = data.message || "Could not rename item.";
      return;
    }
    closeRenamePopover();
    invalidateFolder(currentPath);
    status.textContent = `Renamed item to ${data.name}.`;
    await loadItems({ force: true });
  } catch {
    status.textContent = "Could not rename item.";
  }
});

renamePopoverCancel.addEventListener("click", closeRenamePopover);

async function deleteItemRequest(path) {
  const response = await fetch(`${apiBase("/items")}?path=${encodeURIComponent(path)}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    let data = {};

    try {
      data = await responseJson(response);
    } catch {
      data = {};
    }

    return { ok: false, message: data.message || `Could not delete ${path}.` };
  }

  return { ok: true };
}

function selectedDeleteSummary(paths) {
  return paths.reduce((summary, path) => {
    const row = list.querySelector(`li[data-path="${CSS.escape(path)}"]`);
    if (row?.dataset.type === "folder") {
      summary.folders += 1;
    } else {
      summary.files += 1;
    }
    return summary;
  }, { files: 0, folders: 0 });
}

async function confirmDeleteIfNeeded({ anchor, item, paths }) {
  if (item) {
    const isFolder = item.type === "folder";
    if (!isFolder && confirmSingleDelete.checked) {
      return true;
    }
    return confirmDeleteAction({
      anchor,
      title: `Delete ${isFolder ? "folder" : "file"}?`,
      message: isFolder
        ? `Delete folder "${item.name}" and everything inside it?`
        : `Delete file "${item.name}"?`,
      deleteLabel: `Delete ${isFolder ? "folder" : "file"}`,
    });
  }

  const summary = selectedDeleteSummary(paths);
  const hasFolders = summary.folders > 0;
  const hasFiles = summary.files > 0;
  if (!hasFolders && hasFiles && confirmBulkDelete.checked) {
    return true;
  }
  const pieces = [];
  if (summary.files) {
    pieces.push(`${summary.files} file${summary.files === 1 ? "" : "s"}`);
  }
  if (summary.folders) {
    pieces.push(`${summary.folders} folder${summary.folders === 1 ? "" : "s"}`);
  }
  return confirmDeleteAction({
    anchor,
    title: "Delete selected items?",
    message: hasFolders
      ? `Delete ${pieces.join(" and ")}? Folder contents will be deleted too.`
      : `Delete ${pieces.join(" and ")}?`,
    deleteLabel: "Delete selected",
  });
}

async function deleteItem(item, anchor) {
  if (!(await confirmDeleteIfNeeded({ anchor, item }))) {
    return;
  }

  const result = await deleteItemRequest(item.path);

  if (!result.ok) {
    status.textContent = result.message;
    return;
  }

  status.textContent = `Deleted ${item.name}.`;
  invalidateFolder(currentPath);
  invalidateFolder(item.path);
  selectedItems.delete(item.path);
  updateSelectionControls();
  await loadItems({ force: true });
}

async function deleteSelectedItems(anchor) {
  const items = Array.from(selectedItems);

  if (!items.length) {
    return;
  }

  if (!(await confirmDeleteIfNeeded({ anchor, paths: items }))) {
    return;
  }

  deleteSelectedButton.disabled = true;
  deleteSelectedButton.textContent = "Deleting...";

  let deleted = 0;
  let failed = 0;

  for (const path of items) {
    const result = await deleteItemRequest(path);

    if (result.ok) {
      deleted += 1;
      invalidateFolder(path);
    } else {
      failed += 1;
      status.textContent = result.message;
    }
  }

  invalidateFolder(currentPath);
  selectedItems = new Set();
  status.textContent = failed
    ? `Deleted ${deleted} item${deleted === 1 ? "" : "s"}; ${failed} failed.`
    : `Deleted ${deleted} item${deleted === 1 ? "" : "s"}.`;

  deleteSelectedButton.textContent = "Delete selected";
  updateSelectionControls();
  await loadItems({ force: true });
}

function joinUploadPath(...parts) {
  return parts
    .flatMap((part) => (part || "").replaceAll("\\", "/").split("/"))
    .filter(Boolean)
    .join("/");
}

function availableUploadFolderName(name, usedNames) {
  if (!usedNames.has(name)) {
    usedNames.add(name);
    return name;
  }
  let counter = 1;
  while (usedNames.has(`${name}_${counter}`)) {
    counter += 1;
  }
  const nextName = `${name}_${counter}`;
  usedNames.add(nextName);
  return nextName;
}

function uniquedFolderSelection(selection) {
  if (!selection.directories.length && !selection.entries.some((entry) => entry.parentPath)) {
    return selection;
  }
  const usedNames = visibleItemNames();
  const rootNames = new Map();
  const renameRoot = (path) => {
    const parts = path.split("/").filter(Boolean);
    if (!parts.length) {
      return path;
    }
    if (!rootNames.has(parts[0])) {
      rootNames.set(parts[0], availableUploadFolderName(parts[0], usedNames));
    }
    parts[0] = rootNames.get(parts[0]);
    return parts.join("/");
  };
  return {
    directories: selection.directories.map(renameRoot),
    entries: selection.entries.map((entry) => ({
      ...entry,
      parentPath: renameRoot(entry.parentPath),
      displayName: renameRoot(entry.displayName),
    })),
  };
}

function addPendingUploadTree(selection, targetPath, run) {
  const addFolder = (relativePath) => {
    const path = joinUploadPath(targetPath, relativePath);
    if (!path) {
      return;
    }
    pendingUploadItems.set(path, {
      name: path.split("/").at(-1),
      path,
      type: "folder",
      pendingUpload: true,
      uploadRunId: run.id,
    });
  };

  selection.directories.forEach(addFolder);
  selection.entries.forEach((entry) => {
    const path = joinUploadPath(targetPath, entry.parentPath, entry.file.name);
    entry.fullPath = path;
    entry.uploadId = createUploadId();
    entry.canceled = false;
    entry.request = null;
    pendingUploadItems.set(path, {
      name: entry.file.name,
      path,
      type: "file",
      size: entry.file.size,
      pendingUpload: true,
      uploadRunId: run.id,
      entry,
    });
  });
  renderCurrentFolder();
}

function removePendingUploadPath(path) {
  pendingUploadItems.delete(path);
  renderCurrentFolder();
}

function cleanupPendingFolders(run) {
  let removedFolder;
  do {
    removedFolder = false;
    const pendingPaths = Array.from(pendingUploadItems.keys());
    Array.from(pendingUploadItems.values()).forEach((item) => {
      if (item.uploadRunId !== run.id || item.type !== "folder") {
        return;
      }
      if (!pendingPaths.some((path) => path !== item.path && path.startsWith(`${item.path}/`))) {
        pendingUploadItems.delete(item.path);
        removedFolder = true;
      }
    });
  } while (removedFolder);
}

function cancelPendingUploadPath(path) {
  const canceledPaths = Array.from(pendingUploadItems.keys()).filter((candidate) => candidate === path || candidate.startsWith(`${path}/`));
  canceledPaths.forEach((candidate) => {
    const item = pendingUploadItems.get(candidate);
    if (item?.entry) {
      item.entry.canceled = true;
      item.entry.request?.abort();
      item.entry.stackRow?.remove();
    }
    pendingUploadItems.delete(candidate);
  });
  if (currentPath === path || currentPath.startsWith(`${path}/`)) {
    currentPath = uploadParentPath(path);
    window.history.pushState({ path: currentPath }, "", folderUrl(currentPath));
    loadItems();
  } else {
    renderCurrentFolder();
  }
}

function stopUploadRun(run) {
  run.stopped = true;
  run.entries.forEach((entry) => {
    entry.canceled = true;
    entry.request?.abort();
    entry.stackRow?.remove();
  });
  const removedPaths = Array.from(pendingUploadItems.values())
    .filter((item) => item.uploadRunId === run.id)
    .map((item) => item.path);
  removedPaths.forEach((path) => pendingUploadItems.delete(path));
  while (removedPaths.includes(currentPath)) {
    currentPath = uploadParentPath(currentPath);
  }
  if (activeUploadRun === run) {
    activeUploadRun = null;
  }
  updateFailedControls();
  window.history.pushState({ path: currentPath }, "", folderUrl(currentPath));
  loadItems();
}

function uploadSelectionFromFiles(files) {
  const directories = new Set();
  const entries = Array.from(files).map((file) => {
    const parts = (file.webkitRelativePath || file.name).replaceAll("\\", "/").split("/").filter(Boolean);
    const parentPath = parts.slice(0, -1).join("/");
    for (let index = 1; index < parts.length; index += 1) {
      directories.add(parts.slice(0, index).join("/"));
    }
    return { file, parentPath, displayName: parts.join("/") };
  });
  return { directories: Array.from(directories), entries };
}

function readEntryFile(entry) {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

function readDirectoryEntries(reader) {
  return new Promise((resolve, reject) => {
    const entries = [];
    function readBatch() {
      reader.readEntries((batch) => {
        if (!batch.length) {
          resolve(entries);
          return;
        }
        entries.push(...batch);
        readBatch();
      }, reject);
    }
    readBatch();
  });
}

async function walkDroppedEntry(entry, parentPath, selection) {
  const relativePath = joinUploadPath(parentPath, entry.name);
  if (entry.isFile) {
    selection.entries.push({ file: await readEntryFile(entry), parentPath, displayName: relativePath });
    return;
  }
  if (!entry.isDirectory) {
    return;
  }
  selection.directories.push(relativePath);
  const children = await readDirectoryEntries(entry.createReader());
  await Promise.all(children.map((child) => walkDroppedEntry(child, relativePath, selection)));
}

async function uploadSelectionFromDrop(event) {
  const items = Array.from(event.dataTransfer?.items || []);
  const entries = items.map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
  if (!entries.length) {
    return uploadSelectionFromFiles(filesFromDrop(event));
  }
  const selection = { directories: [], entries: [] };
  await Promise.all(entries.map((entry) => walkDroppedEntry(entry, "", selection)));
  return selection;
}

async function createUploadDirectories(directories, targetPath) {
  if (!directories.length) {
    return;
  }
  const response = await fetch(apiBase("/folders/tree"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: targetPath, directories }),
  });
  if (!response.ok) {
    const data = await responseJson(response);
    throw new Error(data.message || "Could not create uploaded folders.");
  }
}

function emptyUploadDirectories(selection) {
  return selection.directories.filter((directory) => {
    return !selection.entries.some((entry) => entry.parentPath === directory || entry.parentPath.startsWith(`${directory}/`));
  });
}

async function startDroppedUploads(selection, targetPath) {
  try {
    const resolvedSelection = await selection;
    await startUploads(uniquedFolderSelection(resolvedSelection), targetPath);
  } catch {
    status.textContent = "Could not read the dropped folder.";
  }
}

function parseRetryAfter(value) {
  if (!value) {
    return null;
  }
  const seconds = Number.parseInt(value, 10);
  if (Number.isInteger(seconds)) {
    return Math.max(0, seconds * 1000);
  }
  const date = Date.parse(value);
  return Number.isNaN(date) ? null : Math.max(0, date - Date.now());
}

function createUploadId() {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${crypto.getRandomValues(new Uint32Array(2)).join("-")}`;
}

function uploadFile(entry, targetPath, run, onProgress) {
  return new Promise((resolve) => {
    const { file } = entry;
    const request = new XMLHttpRequest();
    const body = new FormData();

    body.append("file", file);
    body.append("path", joinUploadPath(targetPath, entry.parentPath));
    body.append("replace", String(conflictSelect.value === "replace"));

    const finish = (result) => {
      if (entry.request !== request) {
        return;
      }
      entry.request = null;
      run.requests.delete(request);
      resolve(result);
    };

    entry.request = request;
    run.requests.add(request);

    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(event.loaded);
      }
    });

    request.addEventListener("load", () => {
      let data = {};
      const responseText = request.responseText || "";

      try {
        data = JSON.parse(responseText);
      } catch {
        const isHtml = responseText.trimStart().startsWith("<");
        data = {
          htmlResponse: isHtml,
          message: isHtml
            ? "The upload endpoint returned a page instead of data. Sign in again and retry the upload."
            : "",
        };
      }

      if (data.htmlResponse) {
        finish({ ok: false, message: data.message, retryable: false });
        return;
      }

      if (request.status >= 200 && request.status < 300) {
        onProgress(file.size);
        finish({ ok: true, filename: data.filename || file.name });
        return;
      }

      finish({
        ok: false,
        message: data.message || "Upload failed.",
        retryAfterMs: parseRetryAfter(request.getResponseHeader("Retry-After")),
        retryable: [408, 425, 429, 500, 502, 503, 504].includes(request.status),
      });
    });

    request.addEventListener("error", () => {
      finish({ ok: false, message: "Network error.", retryable: true });
    });

    request.addEventListener("abort", () => {
      finish({ ok: false, message: "Upload canceled.", retryable: false, canceled: true });
    });

    request.open("POST", apiBase("/files"));
    if (csrfToken) {
      request.setRequestHeader("X-CSRF-Token", csrfToken);
    }
    request.setRequestHeader("X-Upload-ID", entry.uploadId);
    request.send(body);
  });
}

function formatElapsed(milliseconds) {
  const totalSeconds = Math.floor(milliseconds / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const base = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return hours ? `${String(hours).padStart(2, "0")}:${base}` : base;
}

function updateUploadElapsed() {
  uploadElapsed.textContent = `Elapsed ${formatElapsed(Date.now() - uploadStartedAt)}`;
}

function startUploadStopwatch() {
  window.clearInterval(uploadStopwatchTimer);
  uploadStartedAt = Date.now();
  updateUploadElapsed();
  uploadStopwatchTimer = window.setInterval(updateUploadElapsed, 1000);
}

function stopUploadStopwatch() {
  window.clearInterval(uploadStopwatchTimer);
  uploadStopwatchTimer = null;
  if (uploadStartedAt) {
    updateUploadElapsed();
  }
}

function setUploadPanelCollapsed(collapsed) {
  uploadPanel.classList.toggle("is-collapsed", collapsed);
  toggleUploadPanelButton.textContent = collapsed ? "Show" : "Hide";
  toggleUploadPanelButton.setAttribute("aria-expanded", String(!collapsed));
}

function hideUploadPanel() {
  uploadPanel.classList.remove("is-visible");
  progressWrap.classList.remove("is-visible");
  uploadPanelActions.classList.remove("is-visible");
}

function hideUploadPanelIfEmpty(runId) {
  if (runId === uploadRunId && !uploadList.querySelector(".upload-item")) {
    hideUploadPanel();
  }
}

function removeWithSwipe(element, afterRemove) {
  element.style.maxHeight = `${element.offsetHeight}px`;
  element.offsetHeight;
  element.classList.add("is-removing");

  window.setTimeout(() => {
    element.remove();
    if (afterRemove) {
      afterRemove();
    }
  }, config.animationDurationMs);
}

function updateFailedControls() {
  const hasFailedUploads = Boolean(uploadList.querySelector(".upload-item.is-failed"));
  const hasActiveRun = Boolean(activeUploadRun);
  stopUploadsButton.hidden = !hasActiveRun;
  clearFailedButton.hidden = !hasFailedUploads;
  uploadPanelActions.classList.toggle("is-visible", hasFailedUploads || hasActiveRun);
}

async function uploadQueue(entries, targetPath, run) {
  const totalBytes = entries.reduce((total, entry) => total + entry.file.size, 0);
  const loadedBytes = new Array(entries.length).fill(0);
  const rows = entries.map((entry, index) => {
    const { file } = entry;
    const row = document.createElement("div");
    const name = document.createElement("div");
    const state = document.createElement("div");
    const progress = document.createElement("progress");

    row.className = "upload-item";
    name.className = "upload-name";
    state.className = "upload-state";
    name.textContent = entry.displayName;
    state.textContent = "Queued";
    progress.value = 0;
      progress.max = config.progressMaximum;

    row.append(name, state, progress);
    uploadList.append(row);
    entry.stackRow = row;

    return { entry, file, index, row, state, progress };
  });

  let completed = 0;
  let succeeded = 0;
  let failed = 0;
  let nextIndex = 0;

  function updateOverall() {
    const loadedTotal = loadedBytes.reduce((total, loaded) => total + loaded, 0);
    const percent = totalBytes ? Math.round((loadedTotal / totalBytes) * 100) : 100;

    overallProgress.value = percent;
    overallPercent.textContent = `${percent}%`;
    overallLabel.textContent = `Uploading ${completed} of ${entries.length} files`;
  }

  async function worker() {
    while (nextIndex < rows.length) {
      const row = rows[nextIndex];
      nextIndex += 1;
      if (row.entry.canceled || run.stopped) {
        completed += 1;
        loadedBytes[row.index] = row.file.size;
        removePendingUploadPath(row.entry.fullPath);
        row.row.remove();
        updateOverall();
        continue;
      }

      let result;
      let retries = 0;
      while (true) {
        if (row.entry.canceled || run.stopped) {
          result = { ok: false, canceled: true };
          break;
        }
        row.state.textContent = "Uploading 0%";
        result = await uploadFile(row.entry, targetPath, run, (loaded) => {
          loadedBytes[row.index] = loaded;
          const percent = row.file.size ? Math.round((loaded / row.file.size) * 100) : 100;
          row.progress.value = percent;
          row.state.textContent = `Uploading ${percent}%`;
          updateOverall();
        });
        if (result.ok || result.canceled || !result.retryable || retries >= config.maxUploadRetries) {
          break;
        }
        retries += 1;
        loadedBytes[row.index] = 0;
        row.progress.value = 0;
        updateOverall();
        const retryDelay = Math.min(
          result.retryAfterMs ?? config.retryBaseDelayMs * (2 ** (retries - 1)),
          config.maxRetryDelayMs,
        );
        row.state.textContent = `Retrying in ${formatElapsed(retryDelay)} (${retries}/${config.maxUploadRetries})`;
        await new Promise((resolve) => window.setTimeout(resolve, retryDelay));
      }

      completed += 1;

      if (result.ok) {
        succeeded += 1;
        removePendingUploadPath(row.entry.fullPath);
        cleanupPendingFolders(run);
        invalidateFolder(uploadParentPath(row.entry.fullPath));
        if (currentPath === uploadParentPath(row.entry.fullPath)) {
          loadItems({ force: true });
        }
        row.state.textContent = "Uploaded";
        row.progress.value = 100;
        window.setTimeout(() => {
          removeWithSwipe(row.row, () => {
            hideUploadPanelIfEmpty(run.id);
          });
          }, config.uploadedRowVisibleMs);
      } else if (result.canceled) {
        loadedBytes[row.index] = row.file.size;
        removePendingUploadPath(row.entry.fullPath);
        cleanupPendingFolders(run);
        row.row.remove();
      } else {
        failed += 1;
        loadedBytes[row.index] = row.file.size;
        row.row.classList.add("is-failed");
        row.state.textContent = result.message;

        const dismiss = document.createElement("button");
        dismiss.className = "dismiss-upload-button";
        dismiss.type = "button";
        dismiss.setAttribute("aria-label", `Clear failed upload ${row.file.name}`);
        dismiss.textContent = "×";
        dismiss.addEventListener("click", () => {
          removeWithSwipe(row.row, () => {
            updateFailedControls();
            hideUploadPanelIfEmpty(run.id);
          });
        });
        row.row.insertBefore(dismiss, row.progress);
        updateFailedControls();
      }

      updateOverall();
    }
  }

  uploadPanel.classList.add("is-visible");
  progressWrap.classList.add("is-visible");
  updateOverall();

  const workerCount = Math.min(parallelUploads, rows.length);
  await Promise.all(Array.from({ length: workerCount }, worker));

  return { succeeded, failed };
}

async function startUploads(selection, targetPath = currentPath) {
  const normalizedSelection = Array.isArray(selection) ? uploadSelectionFromFiles(selection) : selection;
  const { directories, entries } = normalizedSelection;
  if (!directories.length && !entries.length) {
    return;
  }

  chooseUploadButton.classList.add("is-disabled");
  chooseUploadButton.setAttribute("aria-disabled", "true");
  chooseUploadButton.disabled = true;
  input.disabled = true;
  folderInput.disabled = true;
  window.clearTimeout(uploadPanelHideTimer);
  startUploadStopwatch();
  const runId = uploadRunId + 1;
  uploadRunId = runId;
  const run = {
    id: runId,
    directoryRequests: new Map(),
    entries,
    requests: new Set(),
    stopped: false,
  };
  activeUploadRun = run;
  addPendingUploadTree(normalizedSelection, targetPath, run);
  status.textContent = `Starting ${entries.length} upload${entries.length === 1 ? "" : "s"}...`;
  uploadList.innerHTML = "";
  updateFailedControls();
  uploadPanel.classList.add("is-visible");
  setUploadPanelCollapsed(false);
  overallProgress.value = 0;
  overallPercent.textContent = "0%";

  try {
    if (!entries.length) {
      await createUploadDirectories(directories, targetPath);
      cleanupPendingFolders(run);
      renderCurrentFolder();
      status.textContent = `Uploaded ${directories.length} empty folder${directories.length === 1 ? "" : "s"}.`;
      showToast(status.textContent);
      hideUploadPanel();
      invalidateFolder(targetPath);
      await loadItems({ force: true });
      return;
    }
    createUploadDirectories(emptyUploadDirectories(normalizedSelection), targetPath).catch((error) => {
      showToast(error.message || "Some empty folders could not be created.");
    });
    const result = await uploadQueue(entries, targetPath, run);

    if (run.stopped) {
      status.textContent = "Uploads stopped.";
    } else if (result.failed) {
      status.textContent = `Uploaded ${result.succeeded} file${result.succeeded === 1 ? "" : "s"}; ${result.failed} failed.`;
    } else {
      status.textContent = `Uploaded ${result.succeeded} file${result.succeeded === 1 ? "" : "s"}.`;
      input.value = "";
      uploadPanelHideTimer = window.setTimeout(() => {
        hideUploadPanelIfEmpty(runId);
        }, config.uploadedRowVisibleMs);
    }

    invalidateFolder(targetPath);
    await loadItems({ force: true });
  } catch {
    status.textContent = "Upload failed.";
    if (!uploadList.querySelector(".upload-item")) {
      hideUploadPanel();
    }
  } finally {
    if (activeUploadRun === run) {
      activeUploadRun = null;
    }
    cleanupPendingFolders(run);
    updateFailedControls();
    renderCurrentFolder();
    stopUploadStopwatch();
    input.disabled = false;
    folderInput.disabled = false;
    input.value = "";
    folderInput.value = "";
    chooseUploadButton.classList.remove("is-disabled");
    chooseUploadButton.removeAttribute("aria-disabled");
    chooseUploadButton.disabled = false;
  }
}

function filesFromDrop(event) {
  return Array.from(event.dataTransfer?.files || []);
}

function draggedItemPaths(event) {
  const encodedPaths = event.dataTransfer?.getData(config.draggedItemsType);
  if (!encodedPaths) {
    return [];
  }
  try {
    const paths = JSON.parse(encodedPaths);
    return Array.isArray(paths) ? paths : [];
  } catch {
    return [];
  }
}

function hasDraggedFiles(event) {
  return Array.from(event.dataTransfer?.types || []).includes("Files");
}

function hasDraggedItems(event) {
  return Array.from(event.dataTransfer?.types || []).includes(config.draggedItemsType);
}

async function moveItems(paths, targetPath) {
  try {
    const response = await fetch(apiBase("/items/move"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ paths, destination: targetPath, replace: conflictSelect.value === "replace" }),
    });
    const data = await responseJson(response);
    if (!response.ok) {
      status.textContent = data.message || "Could not move items.";
      return;
    }
    status.textContent = `Moved ${data.moved} item${data.moved === 1 ? "" : "s"}.`;
    showToast(`Moved ${data.moved} item${data.moved === 1 ? "" : "s"}.`);
    invalidateFolder(currentPath);
    invalidateFolder(targetPath);
    await loadItems({ force: true });
  } catch {
    status.textContent = "Could not move items.";
  }
}

let activeDropTarget;

function setDropTarget(element) {
  if (activeDropTarget && activeDropTarget !== element) {
    activeDropTarget.classList.remove("is-drop-target");
  }
  activeDropTarget = element;
  element.classList.add("is-drop-target");
}

function clearDropTarget(element = activeDropTarget) {
  if (!element) {
    return;
  }
  element.classList.remove("is-drop-target");
  if (activeDropTarget === element) {
    activeDropTarget = undefined;
  }
}

function addFolderDropTarget(element, targetPath) {
  element.addEventListener("dragenter", (event) => {
    if (!hasDraggedFiles(event) && !hasDraggedItems(event)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDropTarget(element);
  });
  element.addEventListener("dragover", (event) => {
    if (!hasDraggedFiles(event) && !hasDraggedItems(event)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = hasDraggedItems(event) ? "move" : "copy";
  });
  element.addEventListener("dragleave", (event) => {
    if (event.relatedTarget && element.contains(event.relatedTarget)) {
      return;
    }
    clearDropTarget(element);
  });
  element.addEventListener("drop", (event) => {
    const resolvedTargetPath = typeof targetPath === "function" ? targetPath() : targetPath;
    const paths = draggedItemPaths(event);
    const uploadSelection = paths.length ? null : uploadSelectionFromDrop(event);
    if (!paths.length && !hasDraggedFiles(event)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    clearDropTarget(element);
    if (paths.length) {
      moveItems(paths, resolvedTargetPath);
    } else {
      startDroppedUploads(uploadSelection, resolvedTargetPath);
    }
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
});

input.addEventListener("change", () => {
  startUploads(Array.from(input.files));
});

folderInput.addEventListener("change", () => {
  startUploads(uniquedFolderSelection(uploadSelectionFromFiles(folderInput.files)));
});

if (canEdit) {
  addFolderDropTarget(list, () => currentPath);
}

let autoScrollFrame;
let autoScrollSpeed = 0;

function autoScroll() {
  if (!autoScrollSpeed) {
    autoScrollFrame = undefined;
    return;
  }
  window.scrollBy({ top: autoScrollSpeed, behavior: "auto" });
  autoScrollFrame = window.requestAnimationFrame(autoScroll);
}

function updateAutoScroll(event) {
  const viewportHeight = window.innerHeight;
  if (event.clientY < config.autoScrollEdgeSize) {
    autoScrollSpeed = -config.autoScrollMaxSpeed * (1 - event.clientY / config.autoScrollEdgeSize);
  } else if (event.clientY > viewportHeight - config.autoScrollEdgeSize) {
    autoScrollSpeed = config.autoScrollMaxSpeed * (1 - (viewportHeight - event.clientY) / config.autoScrollEdgeSize);
  } else {
    autoScrollSpeed = 0;
  }
  if (autoScrollSpeed && !autoScrollFrame) {
    autoScrollFrame = window.requestAnimationFrame(autoScroll);
  }
}

function stopAutoScroll() {
  autoScrollSpeed = 0;
  if (autoScrollFrame) {
    window.cancelAnimationFrame(autoScrollFrame);
    autoScrollFrame = undefined;
  }
  clearDropTarget();
  clearAllRowDropTargets();
}

document.addEventListener("dragover", updateAutoScroll);
document.addEventListener("drop", stopAutoScroll);
document.addEventListener("dragend", stopAutoScroll);
document.addEventListener("contextmenu", (event) => {
  if (event.target.closest("button, a, input, select, textarea, label, form, .settings-panel, .account-panel, .notifications-panel, .share-panel, .upload-panel, .context-menu, .folder-popover, .rename-popover, li.file-row")) {
    return;
  }
  event.preventDefault();
  showContextMenu(null, event.clientX, event.clientY);
});

window.history.replaceState({ path: currentPath }, "", folderUrl(currentPath));
window.addEventListener("popstate", (event) => {
  currentPath = event.state?.path || "";
  document.body.dataset.currentPath = currentPath;
  loadCurrentShare();
  loadItems();
});

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (themeSelect.value === "system") {
    window.FILEDROP_THEME.apply("system");
  }
});

document.addEventListener("click", (event) => {
  if (!uploadChoiceMenu.hidden && !form.contains(event.target)) {
    closeUploadChoiceMenu();
  }
  if (!settingsPanel.hidden && !settingsPanel.contains(event.target) && !settingsToggle.contains(event.target)) {
    closeSettingsPanel();
  }
  if (notificationsPanel && !notificationsPanel.hidden && !notificationsPanel.contains(event.target) && !notificationsToggle.contains(event.target)) {
    closeNotificationsPanel();
  }
  if (sharePanel && !sharePanel.hidden && !sharePanel.contains(event.target) && !shareToggle.contains(event.target)) {
    closeSharePanel();
  }
  if (accountPanel && !accountPanel.hidden && !accountPanel.contains(event.target) && !accountToggle.contains(event.target)) {
    closeAccountPanel();
  }
  if (!contextMenu.hidden && !contextMenu.contains(event.target)) {
    hideContextMenu();
  }
  if (!folderPopover.hidden && !folderPopover.contains(event.target) && !contextMenu.contains(event.target)) {
    closeFolderPopover();
  }
  if (!renamePopover.hidden && !renamePopover.contains(event.target) && !contextMenu.contains(event.target)) {
    closeRenamePopover();
  }
});

window.addEventListener("keydown", (event) => {
  const isTyping = event.target.closest("input, textarea, select, [contenteditable='true']");
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a" && !isTyping) {
    event.preventDefault();
    const paths = visibleItemPaths();
    selectedItems = new Set(paths);
    lastSelectedPath = paths.length ? paths[paths.length - 1] : null;
    updateSelectionControls();
    return;
  }
  if (event.key === "Escape") {
    if (activeDeleteConfirmation) {
      closeDeleteConfirmation(false);
      return;
    }
    closeUploadChoiceMenu();
    hideContextMenu();
    closeNotificationsPanel();
    closeFolderPopover();
    closeRenamePopover();
  }
});

loadNotifications();
loadCurrentShare();
loadItems();

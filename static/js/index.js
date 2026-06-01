const config = window.FILEDROP_CONFIG;
const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const originalFetch = window.fetch.bind(window);
window.fetch = (resource, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  const url = typeof resource === "string" ? new URL(resource, window.location.href) : new URL(resource.url);
  if (url.origin === window.location.origin && ["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    options.headers = new Headers(options.headers || {});
    options.headers.set("X-CSRF-Token", csrfToken);
  }
  return originalFetch(resource, options);
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
const uploadPanelActions = document.querySelector("#upload-panel-actions");
const toastContainer = document.querySelector("#toast-container");
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
const accountToggle = document.querySelector("#account-toggle");
const accountPanel = document.querySelector("#account-panel");
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

new MutationObserver(updateToastPosition).observe(uploadPanel, { attributes: true, attributeFilter: ["class"] });
window.addEventListener("resize", updateToastPosition);

parallelSlider.min = String(config.minParallelUploads);
parallelSlider.max = String(config.maxParallelUploads);
parallelSlider.value = String(parallelUploads);
parallelValue.textContent = String(parallelUploads);
confirmSingleDelete.checked = savedConfirmSingleDelete ?? true;
confirmBulkDelete.checked = savedConfirmBulkDelete ?? true;
themeSelect.value = ["light", "dark", "system"].includes(savedTheme) ? savedTheme : "system";
conflictSelect.value = savedConflictMode === "replace" ? "replace" : "add";
fullView.checked = accountPreferences.fullView === true;
updateSortButtons();
document.body.classList.toggle("full-view", fullView.checked);
window.FILEDROP_THEME.apply(themeSelect.value);

settingsToggle.addEventListener("click", () => {
  const isOpen = settingsPanel.hidden;
  closeAccountPanel();
  settingsPanel.hidden = !isOpen;
  settingsToggle.setAttribute("aria-expanded", String(isOpen));
});

accountToggle.addEventListener("click", () => {
  const isOpen = accountPanel.hidden;
  closeSettingsPanel();
  accountPanel.hidden = !isOpen;
  accountToggle.setAttribute("aria-expanded", String(isOpen));
});

function closeSettingsPanel() {
  settingsPanel.hidden = true;
  settingsToggle.setAttribute("aria-expanded", "false");
}

function closeAccountPanel() {
  accountPanel.hidden = true;
  accountToggle.setAttribute("aria-expanded", "false");
}

async function savePreferences(preferences) {
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
  savePreference("confirmSingleDelete", confirmSingleDelete.checked);
});

confirmBulkDelete.addEventListener("change", () => {
  localStorage.setItem(config.storageKeys.confirmBulkDelete, String(confirmBulkDelete.checked));
  savePreference("confirmBulkDelete", confirmBulkDelete.checked);
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

deleteSelectedButton.addEventListener("click", () => {
  deleteSelectedItems();
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

function updateBreadcrumbs() {
  breadcrumbs.innerHTML = "";
  const segments = currentPath ? currentPath.split("/") : [];
  const crumbs = [{ label: "Root", path: "" }];

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
    addFolderDropTarget(link, crumb.path);
    breadcrumbs.append(link);
  });

}

function folderUrl(path) {
  if (!path) {
    return "/";
  }

  return `/browse/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function navigateToFolder(path) {
  if (path === currentPath) {
    return;
  }
  currentPath = path;
  window.history.pushState({ path }, "", folderUrl(path));
  loadItems();
}

function hideContextMenu() {
  contextMenu.hidden = true;
  contextMenu.classList.remove("is-open");
  contextMenu.innerHTML = "";
}

function showContextMenu(item, x, y) {
  hideContextMenu();
  const actions = [];
  const selectedCount = selectedItems.size;

  if (selectedCount) {
    actions.push({ label: `New folder (${selectedCount})`, action: (button) => { openFolderPopover(button, true); } });
  } else {
    actions.push({ label: "New folder", action: (button) => { openFolderPopover(button, false); } });
  }

  if (item?.type === "folder") {
    actions.push({ label: "Open", action: () => { navigateToFolder(item.path); } });
  } else if (item?.type === "file") {
    actions.push({
      label: "Download",
      action: () => {
        showToast(`Download started for ${item.name}.`);
        window.location.assign(`/api/files/${item.path.split("/").map(encodeURIComponent).join("/")}`);
      },
    });
  }

  if (item) {
    actions.push({ label: "Rename", action: (button) => { openRenamePopover(button, item); } });
    actions.push({ label: "Delete", action: () => { deleteItem(item); }, className: "delete" });
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
  } else {
    selectedItems = new Set([path]);
    lastSelectedPath = path;
  }

  updateSelectionControls();
}

function itemRequestUrl(path) {
  const query = path ? `?path=${encodeURIComponent(path)}` : "";
  return `/api/items${query}`;
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
      const data = await response.json();

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
  const folders = items.filter((item) => item.type === "folder");
  if (folders.length < config.preloadAllFolderLimit) {
    folders.forEach((item) => preloadFolder(item.path));
  } else {
    preloadSelectedFolders();
  }
}

function preloadFolderForHover(path) {
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

function renderItems(data) {
  status.textContent = "";

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
    row.draggable = true;
    row.addEventListener("dragstart", (event) => {
      if (!selectedItems.has(item.path)) {
        setSelectedItems(new Set([item.path]), item.path);
      }
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData(config.draggedItemsType, JSON.stringify(Array.from(selectedItems)));
    });

    checkbox.type = "checkbox";
    checkbox.className = "select-file-checkbox";
    checkbox.setAttribute("aria-label", `Select ${item.name}`);
    checkbox.addEventListener("click", (event) => {
      event.stopPropagation();
      rowSelectionMode(item.path, index, event, { checkbox: true, checked: checkbox.checked });
    });

    name.className = "item-name";
    name.textContent = item.name;
    label.className = "item-label";
    label.append(name);
    const detailText = sortDetail(item);
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
        preloadFolder(item.path);
      });
      openButton.addEventListener("focus", () => {
        preloadFolder(item.path);
      });
      openButton.addEventListener("pointerdown", () => {
        preloadFolder(item.path);
      });
      actions.append(openButton);

      row.addEventListener("mouseenter", () => {
        preloadFolderForHover(item.path);
      });

      row.addEventListener("focusin", () => {
        preloadFolderForHover(item.path);
      });

    } else {
      const downloadLink = document.createElement("a");
      downloadLink.className = "item-action-link";
      downloadLink.href = `/api/files/${item.path.split("/").map(encodeURIComponent).join("/")}`;
      downloadLink.textContent = "Download";
      downloadLink.addEventListener("click", (event) => {
        event.stopPropagation();
        showToast(`Download started for ${item.name}.`);
      });
      actions.append(downloadLink);
    }

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "item-action-button delete";
    deleteButton.textContent = "×";
    deleteButton.setAttribute("aria-label", `Delete ${item.name}`);
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteItem(item);
    });
    actions.append(deleteButton);

    row.addEventListener("click", (event) => {
      if (event.target.closest(".item-action-button, .item-action-link")) {
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
        window.location.assign(`/api/files/${item.path.split("/").map(encodeURIComponent).join("/")}`);
      }
    });

    row.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!selectedItems.has(item.path)) {
        setSelectedItems(new Set([item.path]), item.path);
      }
      showContextMenu(item, event.clientX, event.clientY);
    });

    addRowDropTarget(row, item);
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
    return items;
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
  return `/api/previews/${path.split("/").map(encodeURIComponent).join("/")}`;
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
    const response = await fetch("/api/items/order", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentPath, paths }),
    });
    if (!response.ok) {
      const data = await response.json();
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
    status.textContent = error.message || "Could not load items.";
    showEmptyFileList();
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
  return Array.from(list.querySelectorAll("li.file-row")).map((row) => row.dataset.path);
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
    const response = await fetch("/api/folders", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name: trimmedName, path: currentPath }),
    });

    const data = await response.json();

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
    const response = await fetch("/api/folders/from-selection", {
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
    const data = await response.json();
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
    const response = await fetch("/api/items", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: renameItemPath, name }),
    });
    const data = await response.json();
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
  const response = await fetch(`/api/items?path=${encodeURIComponent(path)}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    let data = {};

    try {
      data = await response.json();
    } catch {
      data = {};
    }

    return { ok: false, message: data.message || `Could not delete ${path}.` };
  }

  return { ok: true };
}

async function deleteItem(item) {
  if (confirmSingleDelete.checked && !window.confirm(`Delete ${item.name}?`)) {
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

async function deleteSelectedItems() {
  const items = Array.from(selectedItems);

  if (!items.length) {
    return;
  }

  if (confirmBulkDelete.checked && !window.confirm(`Delete ${items.length} selected item${items.length === 1 ? "" : "s"}?`)) {
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
  const response = await fetch("/api/folders/tree", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: targetPath, directories }),
  });
  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.message || "Could not create uploaded folders.");
  }
}

async function startDroppedUploads(selection, targetPath) {
  try {
    await startUploads(await selection, targetPath);
  } catch {
    status.textContent = "Could not read the dropped folder.";
  }
}

function uploadFile(entry, targetPath, onProgress) {
  return new Promise((resolve) => {
    const { file } = entry;
    const request = new XMLHttpRequest();
    const body = new FormData();

    body.append("file", file);
    body.append("path", joinUploadPath(targetPath, entry.parentPath));
    body.append("replace", String(conflictSelect.value === "replace"));

    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(event.loaded);
      }
    });

    request.addEventListener("load", () => {
      let data = {};

      try {
        data = JSON.parse(request.responseText);
      } catch {
        data = {};
      }

      if (request.status >= 200 && request.status < 300) {
        onProgress(file.size);
        resolve({ ok: true, filename: data.filename || file.name });
        return;
      }

      resolve({ ok: false, message: data.message || "Upload failed." });
    });

    request.addEventListener("error", () => {
      resolve({ ok: false, message: "Network error." });
    });

    request.addEventListener("abort", () => {
      resolve({ ok: false, message: "Upload canceled." });
    });

    request.open("POST", "/api/files");
    request.setRequestHeader("X-CSRF-Token", csrfToken);
    request.send(body);
  });
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
  uploadPanelActions.classList.toggle("is-visible", hasFailedUploads);
}

async function uploadQueue(entries, targetPath, runId) {
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

      row.state.textContent = "Uploading";

      const result = await uploadFile(row.entry, targetPath, (loaded) => {
        loadedBytes[row.index] = loaded;
        row.progress.value = row.file.size ? Math.round((loaded / row.file.size) * 100) : 100;
        updateOverall();
      });

      completed += 1;

      if (result.ok) {
        succeeded += 1;
        row.state.textContent = "Uploaded";
        row.progress.value = 100;
        window.setTimeout(() => {
          removeWithSwipe(row.row, () => {
            hideUploadPanelIfEmpty(runId);
          });
          }, config.uploadedRowVisibleMs);
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
            hideUploadPanelIfEmpty(runId);
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
  const runId = uploadRunId + 1;
  uploadRunId = runId;
  status.textContent = `Starting ${entries.length} upload${entries.length === 1 ? "" : "s"}...`;
  uploadList.innerHTML = "";
  updateFailedControls();
  uploadPanel.classList.add("is-visible");
  overallProgress.value = 0;
  overallPercent.textContent = "0%";

  try {
    await createUploadDirectories(directories, targetPath);
    if (!entries.length) {
      status.textContent = `Uploaded ${directories.length} empty folder${directories.length === 1 ? "" : "s"}.`;
      showToast(status.textContent);
      hideUploadPanel();
      invalidateFolder(targetPath);
      await loadItems({ force: true });
      return;
    }
    const result = await uploadQueue(entries, targetPath, runId);

    if (result.failed) {
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
    const response = await fetch("/api/items/move", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ paths, destination: targetPath, replace: conflictSelect.value === "replace" }),
    });
    const data = await response.json();
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
  startUploads(uploadSelectionFromFiles(folderInput.files));
});

addFolderDropTarget(list, () => currentPath);

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
  if (event.target.closest("button, a, input, select, textarea, label, form, .settings-panel, .account-panel, .upload-panel, .context-menu, .folder-popover, .rename-popover, li.file-row")) {
    return;
  }
  event.preventDefault();
  showContextMenu(null, event.clientX, event.clientY);
});

window.history.replaceState({ path: currentPath }, "", folderUrl(currentPath));
window.addEventListener("popstate", (event) => {
  currentPath = event.state?.path || "";
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
  if (!accountPanel.hidden && !accountPanel.contains(event.target) && !accountToggle.contains(event.target)) {
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
    closeUploadChoiceMenu();
    hideContextMenu();
    closeFolderPopover();
    closeRenamePopover();
  }
});

loadItems();

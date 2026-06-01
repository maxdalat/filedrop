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
const chooseFilesButton = document.querySelector("#choose-files-button");
const status = document.querySelector("#status");
const uploadPanel = document.querySelector("#upload-panel");
const uploadPanelActions = document.querySelector("#upload-panel-actions");
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
const fileToolbar = document.querySelector("#file-toolbar");
const selectAllCheckbox = document.querySelector("#select-all-checkbox");
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

const savedParallelUploads = Number.parseInt(localStorage.getItem(config.storageKeys.parallelUploads), 10);
const savedConfirmSingleDelete = localStorage.getItem(config.storageKeys.confirmSingleDelete);
const savedConfirmBulkDelete = localStorage.getItem(config.storageKeys.confirmBulkDelete);
const savedTheme = localStorage.getItem(config.storageKeys.theme);
const savedConflictMode = localStorage.getItem(config.storageKeys.conflictMode);
let parallelUploads = Number.isInteger(savedParallelUploads)
  ? Math.min(config.maxParallelUploads, Math.max(config.minParallelUploads, savedParallelUploads))
  : config.defaultParallelUploads;
let uploadPanelHideTimer;
let uploadRunId = 0;
let selectedItems = new Set();
let lastSelectedPath = null;
let currentPath = document.body.dataset.currentPath || "";
const itemCache = new Map();
const pendingItemLoads = new Map();

parallelSlider.min = String(config.minParallelUploads);
parallelSlider.max = String(config.maxParallelUploads);
parallelSlider.value = String(parallelUploads);
parallelValue.textContent = String(parallelUploads);
confirmSingleDelete.checked = savedConfirmSingleDelete === null ? true : savedConfirmSingleDelete === "true";
confirmBulkDelete.checked = savedConfirmBulkDelete === null ? true : savedConfirmBulkDelete === "true";
themeSelect.value = ["light", "dark", "system"].includes(savedTheme) ? savedTheme : "system";
conflictSelect.value = savedConflictMode === "replace" ? "replace" : "add";
window.FILEDROP_THEME.apply(themeSelect.value);

settingsToggle.addEventListener("click", () => {
  const isOpen = settingsPanel.hidden;
  settingsPanel.hidden = !isOpen;
  settingsToggle.setAttribute("aria-expanded", String(isOpen));
});

accountToggle.addEventListener("click", () => {
  const isOpen = accountPanel.hidden;
  accountPanel.hidden = !isOpen;
  accountToggle.setAttribute("aria-expanded", String(isOpen));
});

parallelSlider.addEventListener("input", () => {
  parallelUploads = Number.parseInt(parallelSlider.value, 10);
  parallelValue.textContent = String(parallelUploads);
  localStorage.setItem(config.storageKeys.parallelUploads, String(parallelUploads));
});

confirmSingleDelete.addEventListener("change", () => {
  localStorage.setItem(config.storageKeys.confirmSingleDelete, String(confirmSingleDelete.checked));
});

confirmBulkDelete.addEventListener("change", () => {
  localStorage.setItem(config.storageKeys.confirmBulkDelete, String(confirmBulkDelete.checked));
});

themeSelect.addEventListener("change", () => {
  window.FILEDROP_THEME.setPreference(themeSelect.value);
});

conflictSelect.addEventListener("change", () => {
  localStorage.setItem(config.storageKeys.conflictMode, conflictSelect.value);
});

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
        window.location.assign(`/api/files/${item.path.split("/").map(encodeURIComponent).join("/")}`);
      },
    });
  }

  if (item) {
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

  data.items.forEach((item, index) => {
    const row = document.createElement("li");
    const checkbox = document.createElement("input");
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

      addFolderDropTarget(row, item.path);
    } else {
      const downloadLink = document.createElement("a");
      downloadLink.className = "item-action-link";
      downloadLink.href = `/api/files/${item.path.split("/").map(encodeURIComponent).join("/")}`;
      downloadLink.textContent = "Download";
      downloadLink.addEventListener("click", (event) => {
        event.stopPropagation();
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

    row.addEventListener("dblclick", (event) => {
      if (event.target.closest(".item-action-button, .item-action-link, .select-file-checkbox")) {
        return;
      }
      if (item.type === "folder") {
        navigateToFolder(item.path);
      } else {
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

    row.append(checkbox, name, actions);
    list.append(row);
  });

  updateSelectionControls();
  preloadVisibleFolders(data.items);
  preloadParentFoldersAfterRender();
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

function positionFolderPopover(anchor) {
  const rect = anchor.getBoundingClientRect();
  const margin = 8;
  const width = folderPopover.offsetWidth;
  const height = folderPopover.offsetHeight;
  const left = Math.min(rect.left, window.innerWidth - width - margin);
  const below = rect.bottom + margin;
  const top = below + height <= window.innerHeight ? below : Math.max(margin, rect.top - height - margin);
  folderPopover.style.left = `${Math.max(margin, left)}px`;
  folderPopover.style.top = `${top}px`;
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
    closeFolderPopover();
    navigateToFolder(data.path);
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
    closeFolderPopover();
    invalidateFolder(data.folder.path);
    navigateToFolder(data.folder.path);
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

function uploadFile(file, targetPath, onProgress) {
  return new Promise((resolve) => {
    const request = new XMLHttpRequest();
    const body = new FormData();

    body.append("file", file);
    body.append("path", targetPath);
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

async function uploadQueue(files, targetPath, runId) {
  const totalBytes = files.reduce((total, file) => total + file.size, 0);
  const loadedBytes = new Array(files.length).fill(0);
  const rows = files.map((file, index) => {
    const row = document.createElement("div");
    const name = document.createElement("div");
    const state = document.createElement("div");
    const progress = document.createElement("progress");

    row.className = "upload-item";
    name.className = "upload-name";
    state.className = "upload-state";
    name.textContent = file.name;
    state.textContent = "Queued";
    progress.value = 0;
      progress.max = config.progressMaximum;

    row.append(name, state, progress);
    uploadList.append(row);

    return { file, index, row, state, progress };
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
    overallLabel.textContent = `Uploading ${completed} of ${files.length} files`;
  }

  async function worker() {
    while (nextIndex < rows.length) {
      const row = rows[nextIndex];
      nextIndex += 1;

      row.state.textContent = "Uploading";

      const result = await uploadFile(row.file, targetPath, (loaded) => {
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

async function startUploads(files, targetPath = currentPath) {

  if (!files.length) {
    return;
  }

  chooseFilesButton.classList.add("is-disabled");
  chooseFilesButton.setAttribute("aria-disabled", "true");
  input.disabled = true;
  window.clearTimeout(uploadPanelHideTimer);
  const runId = uploadRunId + 1;
  uploadRunId = runId;
  status.textContent = `Starting ${files.length} upload${files.length === 1 ? "" : "s"}...`;
  uploadList.innerHTML = "";
  updateFailedControls();
  uploadPanel.classList.add("is-visible");
  overallProgress.value = 0;
  overallPercent.textContent = "0%";

  try {
    const result = await uploadQueue(files, targetPath, runId);

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
  } finally {
    input.disabled = false;
    input.value = "";
    chooseFilesButton.classList.remove("is-disabled");
    chooseFilesButton.removeAttribute("aria-disabled");
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
    const files = filesFromDrop(event);
    if (!paths.length && !files.length) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    clearDropTarget(element);
    if (paths.length) {
      moveItems(paths, resolvedTargetPath);
    } else {
      startUploads(files, resolvedTargetPath);
    }
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
});

input.addEventListener("change", () => {
  startUploads(Array.from(input.files));
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
}

document.addEventListener("dragover", updateAutoScroll);
document.addEventListener("drop", stopAutoScroll);
document.addEventListener("dragend", stopAutoScroll);
document.addEventListener("contextmenu", (event) => {
  if (event.target.closest("button, a, input, select, textarea, label, form, .settings-panel, .account-panel, .upload-panel, .context-menu, .folder-popover, li.file-row")) {
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
  if (!contextMenu.hidden && !contextMenu.contains(event.target)) {
    hideContextMenu();
  }
  if (!folderPopover.hidden && !folderPopover.contains(event.target) && !contextMenu.contains(event.target)) {
    closeFolderPopover();
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
    hideContextMenu();
    closeFolderPopover();
  }
});

loadItems();

(function () {
  const storageKey = "theme";
  const storedTheme = localStorage.getItem(storageKey);
  let theme = ["light", "dark", "system"].includes(storedTheme) ? storedTheme : "system";

  function applyTheme(selectedTheme) {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = selectedTheme === "system"
      ? (prefersDark ? "dark" : "light")
      : selectedTheme;
  }

  window.FILEDROP_THEME = Object.freeze({
    apply: applyTheme,
    getPreference: () => theme,
    setPreference: (selectedTheme) => {
      theme = selectedTheme;
      localStorage.setItem(storageKey, selectedTheme);
      applyTheme(selectedTheme);
    },
  });

  applyTheme(theme);
}());

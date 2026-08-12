export function clearOrganizationScopedBrowserCaches() {
  if (typeof window === "undefined") {
    return;
  }

  for (let index = window.sessionStorage.length - 1; index >= 0; index -= 1) {
    const key = window.sessionStorage.key(index);
    if (key?.startsWith("labelos:")) {
      window.sessionStorage.removeItem(key);
    }
  }
}

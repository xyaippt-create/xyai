const CLIPBOARD_GUID_NAME_PATTERN =
  /^codex-clipboard-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?:[_.]|$)/i;
const URL_LIKE_PATTERN = /^(?:[a-z][a-z0-9+.-]*:)?\/\//i;

export function getFileIdentityName(value, fallback = "") {
  const rawValue = value === null || value === undefined ? "" : String(value);
  return rawValue === "" ? fallback : rawValue;
}

export function getFileNameFromPath(value, fallback = "") {
  const rawValue = value === null || value === undefined ? "" : String(value);
  if (rawValue === "") return fallback;
  return rawValue.split(/[\\/]/).pop() || fallback;
}

export function getFileNameFromUrl(value, fallback = "") {
  const rawValue = value === null || value === undefined ? "" : String(value);
  if (rawValue === "") return fallback;
  try {
    const parsed = new URL(rawValue, "http://hdde.local");
    const encodedName = parsed.pathname.split("/").pop() || "";
    return decodeURIComponent(encodedName) || fallback;
  } catch {
    return fallback;
  }
}

export function getFileDisplayName(value, fallback = "") {
  const rawValue = value === null || value === undefined ? "" : String(value);
  const fileName = URL_LIKE_PATTERN.test(rawValue) || rawValue.startsWith("/api/")
    ? getFileNameFromUrl(rawValue, fallback)
    : /[\\/]/.test(rawValue)
      ? getFileNameFromPath(rawValue, fallback)
      : getFileIdentityName(rawValue, fallback);

  if (CLIPBOARD_GUID_NAME_PATTERN.test(fileName)) {
    return "剪贴板图片";
  }

  return fileName;
}

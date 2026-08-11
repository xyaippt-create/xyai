const CLIPBOARD_GUID_NAME_PATTERN =
  /^codex-clipboard-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?:[_.]|$)/i;

export function getFileDisplayName(value, fallback = "") {
  const rawValue = String(value || "").trim();
  if (!rawValue) {
    return fallback;
  }

  const pathname = rawValue.split(/[?#]/, 1)[0];
  const fileName = pathname.split(/[\\/]/).pop() || rawValue;

  if (CLIPBOARD_GUID_NAME_PATTERN.test(fileName)) {
    return "剪贴板图片";
  }

  return fileName;
}

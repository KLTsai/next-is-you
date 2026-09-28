function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);
}

export function safeSourceUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

export function sourceLinkMarkup(value) {
  const url = safeSourceUrl(value);
  return url
    ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">開啟院方官方來源（新分頁）</a>`
    : "來源連結尚未提供";
}

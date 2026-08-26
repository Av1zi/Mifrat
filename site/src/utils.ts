/**
 * Escapes scraped/dynamic text before inserting it via innerHTML. Product
 * titles come from vendor sites and can contain "&", quotes (inch marks),
 * or stray angle brackets — none of it is trusted markup.
 */
export function esc(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

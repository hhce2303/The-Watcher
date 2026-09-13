/**
 * Builds URLs for the `watcher://` custom protocol (src-tauri/src/media_protocol.rs).
 *
 * Windows/WebView2 serves custom protocols at `http://<scheme>.localhost/...`
 * (this app targets Windows only — see docs/migration ADRs).
 */
const ORIGIN = "http://watcher.localhost";

/** Live preview JPEG for one monitor index, refreshed by the caller (~2 fps). */
export function previewUrl(monitorIndex: number): string {
  return `${ORIGIN}/preview/m${monitorIndex}`;
}

/** A clip/segment file path, Range-streamable for <video>. */
export function clipUrl(absolutePath: string): string {
  const encoded = base64UrlEncode(absolutePath);
  return `${ORIGIN}/clip/${encoded}`;
}

function base64UrlEncode(s: string): string {
  const b64 = btoa(unescape(encodeURIComponent(s)));
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// The only place the UI learns where its backend is. Components call apiFetch() for data and apiUrl() for addresses used in
// href/src attributes (downloads, the audio player); nothing else in the UI names a host or a transport.
//
// Today the UI is served by the local API itself, so every path is same-origin. A shell that serves the UI from somewhere else
// (the Tauri window, re-architecture G6) calls setApiBase() once at start-up; the UI code does not change.
let base = "";

export function setApiBase(value: string) { base = value.replace(/\/+$/, ""); }

export function apiUrl(path: string): string { return path.startsWith("/") ? base + path : path; }

export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(apiUrl(path), { credentials: "same-origin", ...init });
}

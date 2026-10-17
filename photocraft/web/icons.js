const paths = {
  offline:
    '<rect x="3" y="3" width="18" height="13" rx="2"/><path d="M8 21h8M12 16v5m-4-12 3 3 5-5"/>',
  add: '<path d="M12 5v14M5 12h14"/>',
  crop: '<path d="M6 3v15h15M3 6h15v15"/>',
  background:
    '<path d="m5 3 10 10M7 5l-4 8 8 8 9-9-8-8Z"/><path d="M3 13h17M21 16s-2 2-2 3a2 2 0 0 0 4 0c0-1-2-3-2-3Z"/>',
  rotate: '<path d="M3 10a9 9 0 1 1 2 8M3 4v6h6"/>',
  brush:
    '<path d="m14 4 6 6-9 9-6-6zM5 13c-5 1 1 6-3 8 8 1 8-4 9-4M14 4l2-2 6 6-2 2"/>',
  mosaic:
    '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  blur: '<path d="M12 2C10 6 5 10 5 15a7 7 0 0 0 14 0c0-5-5-9-7-13Z"/><path d="M8 15a4 4 0 0 0 4 4"/>',
  watermark: '<path d="M4 5h16M12 5v15M8 20h8"/>',
  enhance:
    '<path d="m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5z"/>',
  id: '<rect x="2" y="4" width="20" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="M5 17c0-5 8-5 8 0M16 9h3M16 13h3"/>',
  export: '<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
  compress:
    '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 12h6m-3-3 3 3-3 3M21 12h-6m3-3-3 3 3 3"/>',
  open: '<path d="M3 7V4h7l2 3h9v13H3zM3 11h18"/>',
  undo: '<path d="M4 10h10a6 6 0 0 1 0 12M4 10l5-5M4 10l5 5"/>',
  redo: '<path d="M20 10H10a6 6 0 0 0 0 12M20 10l-5-5M20 10l-5 5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 1v2M12 21v2M1 12h2M21 12h2M4 4l2 2M18 18l2 2M4 20l2-2M18 6l2-2"/>',
  compare:
    '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 2v20M6 15l3-4 3 4M12 15l4-5 2 3"/>',
  fit: '<path d="M3 9V3h6M15 3h6v6M21 15v6h-6M9 21H3v-6"/>',
  hand: '<path d="M8 12V5a2 2 0 0 1 4 0v6-8a2 2 0 0 1 4 0v9-6a2 2 0 0 1 4 0v10c0 7-10 7-12 4l-5-7c-2-4 2-5 5-1z"/>',
  check: '<path d="m4 12 5 5L20 6"/>',
  image:
    '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 18 6-6 4 4 4-6 4 7"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
  download: '<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
  settings:
    '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 1 1 5 2c-2 1-2 2-2 3m0 3h.01"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  chevron: '<path d="m8 5 7 7-7 7"/>',
  minus: '<path d="M5 12h14"/>',
  reset: '<path d="M3 10a9 9 0 1 1 2 8M3 4v6h6"/>',
  shield:
    '<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6z"/><path d="m8 12 3 3 5-6"/>',
};
export function icon(name, size = 20) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.image}</svg>`;
}

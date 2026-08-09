// Orion HUD — Tauri shell. The window is configured declaratively in
// tauri.conf.json (transparent, frameless, always-on-top, skip-taskbar).
//
// Plugins:
//  - global-shortcut: lets the frontend bind a hotkey to toggle click-through.
//  - websocket: runs the bridge connection natively in Rust, bypassing the
//    webview's private-network/mixed-content restrictions on ws://127.0.0.1.
// Monitor positioning and click-through are driven from JS (src/lib/overlay.js).

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_websocket::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


EDITOR_HTML = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Rich Content Editor</title>
  <style>
    :root {
      --bg: #f3f5f8;
      --panel: #ffffff;
      --line: #d7dce3;
      --text: #20252b;
      --muted: #5f6875;
      --accent: #0f62fe;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      font-family: "Segoe UI", system-ui, sans-serif;
      color: var(--text);
      background: linear-gradient(180deg, #eef2f7 0%, #f8fafc 100%);
      display: grid;
      grid-template-rows: auto auto 1fr auto;
      gap: 8px;
      padding: 10px;
    }
    .row, .toolbar, .footer {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px;
    }
    .row label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
    #title {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 10px;
      font: inherit;
      outline: none;
    }
    #title:focus, #editor:focus {
      border-color: #8fb0ff;
      box-shadow: 0 0 0 3px rgba(15, 98, 254, 0.12);
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }
    .toolbar button {
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
      padding: 6px 10px;
      cursor: pointer;
      font: inherit;
    }
    .toolbar button:hover { background: #f6f8fb; }
    .toolbar .sep {
      width: 1px;
      height: 22px;
      background: var(--line);
      margin: 0 2px;
    }
    #editorWrap {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      overflow: hidden;
      min-height: 280px;
      display: grid;
      grid-template-rows: 1fr;
    }
    #editor {
      min-height: 100%;
      padding: 14px;
      overflow: auto;
      outline: none;
      line-height: 1.4;
    }
    #editor img { max-width: 100%; height: auto; }
    #editor table { border-collapse: collapse; max-width: 100%; }
    #editor th, #editor td { border: 1px solid #d7dce3; padding: 4px 6px; }
    #editor p { margin: 0 0 0.75em 0; }
    #editor ul, #editor ol { margin: 0.3em 0 0.8em 1.4em; }
    .footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .hint { color: var(--muted); font-size: 12px; }
    .actions { display: flex; gap: 8px; }
    .actions button {
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #fff;
      padding: 8px 12px;
      cursor: pointer;
      font: inherit;
    }
    .actions button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      font-weight: 600;
    }
  </style>
</head>
<body>
  <div class="row">
    <label for="title">Block title (optional)</label>
    <input id="title" type="text" />
  </div>

  <div class="toolbar" aria-label="Formatting">
    <button type="button" data-cmd="bold"><b>B</b></button>
    <button type="button" data-cmd="italic"><i>I</i></button>
    <button type="button" data-cmd="underline"><u>U</u></button>
    <div class="sep"></div>
    <button type="button" data-cmd="insertUnorderedList">Bullets</button>
    <button type="button" data-cmd="insertOrderedList">Numbering</button>
    <div class="sep"></div>
    <button type="button" data-cmd="justifyLeft">Left</button>
    <button type="button" data-cmd="justifyCenter">Center</button>
    <button type="button" data-cmd="justifyRight">Right</button>
    <div class="sep"></div>
    <button type="button" id="btnClear">Clear formatting</button>
  </div>

  <div id="editorWrap">
    <div id="editor" contenteditable="true" spellcheck="true"></div>
  </div>

  <div class="footer">
    <div class="hint">
      Paste using normal right-click Paste or Ctrl+V. Images pasted from Word/web/clipboard are supported.
    </div>
    <div class="actions">
      <button type="button" id="btnCancel">Cancel</button>
      <button type="button" class="primary" id="btnSave">Save</button>
    </div>
  </div>

  <script>
    window.__DDP_INITIAL__ = __DDP_INITIAL_JSON__;
    const editor = document.getElementById('editor');
    const titleEl = document.getElementById('title');
    let dirty = false;

    function setDirty(v = true) { dirty = v; }

    function applyInitial(payload) {
      titleEl.value = payload.title || '';
      editor.innerHTML = payload.html || '';
    }

    function exec(cmd) {
      editor.focus();
      document.execCommand(cmd, false, null);
      setDirty();
    }

    async function normalizeImagesForSave() {
      const imgs = Array.from(editor.querySelectorAll('img'));
      for (const img of imgs) {
        const src = (img.getAttribute('src') || '').trim();
        if (!src) continue;
        if (src.startsWith('blob:')) {
          try {
            const res = await fetch(src);
            const blob = await res.blob();
            const dataUrl = await new Promise((resolve, reject) => {
              const reader = new FileReader();
              reader.onload = () => resolve(reader.result);
              reader.onerror = reject;
              reader.readAsDataURL(blob);
            });
            img.setAttribute('src', String(dataUrl));
          } catch (_e) {
          }
        }
      }
    }

    async function saveAndClose() {
      await normalizeImagesForSave();
      const payload = {
        title: titleEl.value || '',
        html: editor.innerHTML || '',
      };
      if (window.pywebview && window.pywebview.api && window.pywebview.api.save_content) {
        await window.pywebview.api.save_content(payload);
      }
    }

    async function cancelAndClose() {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.cancel) {
        await window.pywebview.api.cancel();
      }
    }

    document.querySelectorAll('[data-cmd]').forEach(btn => {
      btn.addEventListener('click', () => exec(btn.getAttribute('data-cmd')));
    });
    document.getElementById('btnClear').addEventListener('click', () => {
      editor.focus();
      document.execCommand('removeFormat', false, null);
      setDirty();
    });
    document.getElementById('btnSave').addEventListener('click', saveAndClose);
    document.getElementById('btnCancel').addEventListener('click', cancelAndClose);
    editor.addEventListener('input', () => setDirty());
    titleEl.addEventListener('input', () => setDirty());

    document.addEventListener('keydown', async (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        await saveAndClose();
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        await cancelAndClose();
      }
    });

    function bootstrap() {
      applyInitial(window.__DDP_INITIAL__ || {});
      editor.focus();
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', bootstrap, { once: true });
    } else {
      bootstrap();
    }
  </script>
</body>
</html>
"""


class _EditorApi:
    def __init__(self, initial_payload: dict[str, Any]) -> None:
        self.result: dict[str, Any] | None = None
        self.cancelled = False
        self.window = None

    def save_content(self, payload: Any) -> bool:
        if isinstance(payload, dict):
            self.result = payload
        else:
            self.result = {}
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
        return True

    def cancel(self) -> bool:
        self.cancelled = True
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
        return True


def run_editor(payload: dict[str, Any]) -> dict[str, Any]:
    import webview  # optional dependency

    api = _EditorApi(payload)
    initial_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html_doc = EDITOR_HTML.replace("__DDP_INITIAL_JSON__", initial_json)
    window = webview.create_window(
        "Report Content Editor",
        html=html_doc,
        js_api=api,
        width=980,
        height=760,
        resizable=True,
    )
    api.window = window

    # Prefer Edge/Chromium on Windows for best clipboard/Word paste behavior.
    start_kwargs: dict[str, Any] = {"debug": False}
    try:
        webview.start(gui="edgechromium", **start_kwargs)
    except TypeError:
        webview.start(**start_kwargs)
    except Exception:
        webview.start(**start_kwargs)

    if api.cancelled or api.result is None:
        return {"ok": False}
    return {
        "ok": True,
        "title": str(api.result.get("title", "") or ""),
        "html": str(api.result.get("html", "") or ""),
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("Usage: rich_html_editor.py <input_json> <output_json>", file=sys.stderr)
        return 2

    in_path = Path(argv[0])
    out_path = Path(argv[1])
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    result = run_editor(payload)
    out_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

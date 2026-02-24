from __future__ import annotations

import ctypes
import base64
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dashboard_data_plotter.utils.log import (
    RICH_EDITOR_LOG_PATH,
    log_event,
    log_exception,
)


def _win_clipboard_dlls():
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_int
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = ctypes.c_int
        user32.GetClipboardData.argtypes = [ctypes.c_uint]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
        user32.RegisterClipboardFormatW.restype = ctypes.c_uint

        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = ctypes.c_int
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.restype = ctypes.c_size_t
    except Exception:
        pass
    return user32, kernel32

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
    .ctx-menu {
      position: fixed;
      z-index: 9999;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 10px 24px rgba(0, 0, 0, 0.14);
      padding: 4px;
      min-width: 150px;
    }
    .ctx-menu[hidden] { display: none; }
    .ctx-menu button {
      width: 100%;
      text-align: left;
      border: 0;
      background: transparent;
      border-radius: 6px;
      padding: 7px 10px;
      font: inherit;
      cursor: pointer;
      color: var(--text);
    }
    .ctx-menu button:hover:not(:disabled) { background: #f1f5fb; }
    .ctx-menu button:disabled {
      color: #9aa3af;
      cursor: default;
    }
    .ctx-menu .sep {
      height: 1px;
      background: var(--line);
      margin: 4px 2px;
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

  <div id="ctxMenu" class="ctx-menu" hidden role="menu" aria-label="Edit menu">
    <button type="button" data-action="cut">Cut</button>
    <button type="button" data-action="copy">Copy</button>
    <button type="button" data-action="paste">Paste</button>
    <div class="sep" aria-hidden="true"></div>
    <button type="button" data-action="selectAll">Select All</button>
    <button type="button" data-action="clear">Clear</button>
  </div>

  <script>
    window.__DDP_INITIAL__ = __DDP_INITIAL_JSON__;
    const editor = document.getElementById('editor');
    const titleEl = document.getElementById('title');
    const ctxMenu = document.getElementById('ctxMenu');
    let dirty = false;
    let ctxTarget = null;
    let savedEditorRange = null;

    function setDirty(v = true) { dirty = v; }

    function applyInitial(payload) {
      titleEl.value = payload.title || '';
      editor.innerHTML = payload.html || '';
      debugLog('apply_initial', {
        title_len: (titleEl.value || '').length,
        html_len: (editor.innerHTML || '').length,
      });
    }

    function exec(cmd) {
      editor.focus();
      document.execCommand(cmd, false, null);
      setDirty();
      debugLog('format_cmd', { cmd });
    }

    async function debugLog(eventName, details) {
      try {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.debug_log) {
          await window.pywebview.api.debug_log(eventName, details || {});
        }
      } catch (_e) {
      }
    }

    function hideContextMenu() {
      ctxMenu.hidden = true;
      ctxTarget = null;
    }

    function cloneCurrentEditorRange() {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) return null;
      const range = sel.getRangeAt(0);
      const common = range.commonAncestorContainer;
      const container = common && common.nodeType === Node.ELEMENT_NODE ? common : common?.parentNode;
      if (!container || !editor.contains(container)) return null;
      return range.cloneRange();
    }

    function setEditorRangeFromPoint(x, y) {
      let range = null;
      if (document.caretRangeFromPoint) {
        range = document.caretRangeFromPoint(x, y);
      } else if (document.caretPositionFromPoint) {
        const pos = document.caretPositionFromPoint(x, y);
        if (pos) {
          range = document.createRange();
          range.setStart(pos.offsetNode, pos.offset);
          range.collapse(true);
        }
      }
      if (!range) {
        savedEditorRange = cloneCurrentEditorRange();
        return;
      }
      const node = range.startContainer && range.startContainer.nodeType === Node.ELEMENT_NODE
        ? range.startContainer
        : range.startContainer?.parentNode;
      if (!node || !editor.contains(node)) {
        savedEditorRange = cloneCurrentEditorRange();
        return;
      }
      savedEditorRange = range.cloneRange();
      try {
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(savedEditorRange);
      } catch (_e) {
      }
    }

    function restoreEditorRange() {
      if (!savedEditorRange) return false;
      try {
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(savedEditorRange);
        return true;
      } catch (_e) {
        return false;
      }
    }

    function getEditableTarget(node) {
      if (!node) return null;
      let el = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
      if (!el) return null;
      if (el === titleEl) return titleEl;
      if (el === editor || (el.closest && el.closest('#editor'))) return editor;
      if (el.matches && el.matches('input, textarea')) return el;
      if (el.closest) {
        const editable = el.closest('input, textarea, [contenteditable="true"]');
        if (editable) return editable;
      }
      return null;
    }

    function isTargetEditable(target) {
      if (!target) return false;
      if (target === editor) return true;
      if ('disabled' in target && target.disabled) return false;
      if ('readOnly' in target && target.readOnly) return false;
      return true;
    }

    function targetHasSelection(target) {
      if (!target) return false;
      if (target === editor || target.isContentEditable) {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed || sel.rangeCount === 0) return false;
        const anchor = sel.anchorNode;
        return !!anchor && editor.contains(anchor);
      }
      if (typeof target.selectionStart === 'number' && typeof target.selectionEnd === 'number') {
        return target.selectionEnd > target.selectionStart;
      }
      return false;
    }

    function updateContextMenuState() {
      const editable = isTargetEditable(ctxTarget);
      const hasSelection = targetHasSelection(ctxTarget);
      ctxMenu.querySelector('[data-action="cut"]').disabled = !(editable && hasSelection);
      ctxMenu.querySelector('[data-action="copy"]').disabled = !hasSelection;
      ctxMenu.querySelector('[data-action="paste"]').disabled = !editable;
      ctxMenu.querySelector('[data-action="selectAll"]').disabled = false;
      ctxMenu.querySelector('[data-action="clear"]').disabled = !editable;
    }

    function selectAllInTarget(target) {
      if (!target) return;
      if (target === editor || target.isContentEditable) {
        target.focus();
        const range = document.createRange();
        range.selectNodeContents(target);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        return;
      }
      if (typeof target.select === 'function') target.select();
    }

    function clearTarget(target) {
      if (!target) return;
      if (target === editor || target.isContentEditable) {
        target.innerHTML = '';
        target.dispatchEvent(new Event('input', { bubbles: true }));
        target.focus();
        return;
      }
      target.value = '';
      target.dispatchEvent(new Event('input', { bubbles: true }));
      target.focus();
    }

    function insertEditorText(text) {
      editor.focus();
      restoreEditorRange();
      const sel = window.getSelection();
      let range = (sel && sel.rangeCount > 0) ? sel.getRangeAt(0) : null;
      if (!range) {
        range = document.createRange();
        range.selectNodeContents(editor);
        range.collapse(false);
      }
      range.deleteContents();
      const node = document.createTextNode(text);
      range.insertNode(node);
      range.setStartAfter(node);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
      savedEditorRange = range.cloneRange();
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function insertEditorHtml(htmlValue) {
      editor.focus();
      restoreEditorRange();
      const sel = window.getSelection();
      let range = (sel && sel.rangeCount > 0) ? sel.getRangeAt(0) : null;
      if (!range) {
        range = document.createRange();
        range.selectNodeContents(editor);
        range.collapse(false);
      }
      range.deleteContents();
      const frag = range.createContextualFragment(String(htmlValue || ''));
      const lastNode = frag.lastChild;
      range.insertNode(frag);
      if (lastNode) {
        range.setStartAfter(lastNode);
      }
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
      savedEditorRange = range.cloneRange();
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function insertTextIntoTarget(target, text) {
      if (target === editor || target.isContentEditable) {
        insertEditorText(text);
        return;
      }
      if (typeof target.setRangeText === 'function') {
        const start = target.selectionStart ?? target.value.length;
        const end = target.selectionEnd ?? start;
        target.setRangeText(text, start, end, 'end');
      } else {
        target.value = (target.value || '') + text;
      }
      target.dispatchEvent(new Event('input', { bubbles: true }));
      target.focus();
    }

    function insertHtmlIntoTarget(target, htmlValue) {
      if (target === editor || target.isContentEditable) {
        insertEditorHtml(htmlValue);
        return true;
      }
      return false;
    }

    async function pasteIntoTarget(target) {
      if (!target) return;
      target.focus();
      await debugLog('paste_start', {
        target: (target === editor || target.isContentEditable) ? 'editor' : (target.id || target.tagName || 'field'),
      });
      try {
        if (navigator.clipboard && navigator.clipboard.readText) {
          const text = await navigator.clipboard.readText();
          if (typeof text === 'string' && text.length) {
            insertTextIntoTarget(target, text);
            await debugLog('paste_js_clipboard_text_ok', { text_len: text.length });
            return;
          }
          await debugLog('paste_js_clipboard_text_empty', {});
        }
      } catch (_e) {
        await debugLog('paste_js_clipboard_text_err', { error: String(_e) });
      }
      try {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.read_clipboard_payload) {
          const clip = await window.pywebview.api.read_clipboard_payload();
          if (clip && typeof clip === 'object') {
            await debugLog('paste_py_payload', {
              text_len: (clip.text || '').length,
              html_len: (clip.html || '').length,
              has_image: !!(clip.image_data_url || ''),
            });
            if ((target === editor || target.isContentEditable) && typeof clip.html === 'string' && clip.html) {
              if (insertHtmlIntoTarget(target, clip.html)) return;
            }
            if ((target === editor || target.isContentEditable) && typeof clip.image_data_url === 'string' && clip.image_data_url) {
              insertHtmlIntoTarget(target, `<img src="${clip.image_data_url}" alt="Pasted image" />`);
              return;
            }
            if (typeof clip.text === 'string' && clip.text.length) {
              insertTextIntoTarget(target, clip.text);
              return;
            }
          }
        } else if (window.pywebview && window.pywebview.api && window.pywebview.api.read_clipboard_text) {
          const text = await window.pywebview.api.read_clipboard_text();
          if (typeof text === 'string' && text.length) {
            insertTextIntoTarget(target, text);
            await debugLog('paste_py_text_ok', { text_len: text.length });
            return;
          }
        }
      } catch (_e) {
        await debugLog('paste_py_clipboard_err', { error: String(_e) });
      }
      try {
        document.execCommand('paste', false, null);
        await debugLog('paste_execCommand_attempt', {});
      } catch (_e) {
        await debugLog('paste_execCommand_err', { error: String(_e) });
      }
    }

    async function runContextAction(action) {
      const target = ctxTarget;
      hideContextMenu();
      if (!target) return;
      target.focus();
      if (action === 'cut') {
        document.execCommand('cut', false, null);
        return;
      }
      if (action === 'copy') {
        document.execCommand('copy', false, null);
        return;
      }
      if (action === 'paste') {
        await pasteIntoTarget(target);
        return;
      }
      if (action === 'selectAll') {
        selectAllInTarget(target);
        return;
      }
      if (action === 'clear') {
        clearTarget(target);
      }
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
        await debugLog('save_click', {
          title_len: (titleEl.value || '').length,
          html_len: (editor.innerHTML || '').length,
        });
        await window.pywebview.api.save_content(payload);
      }
    }

    async function cancelAndClose() {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.cancel) {
        await debugLog('cancel_click', {});
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
    ctxMenu.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        await runContextAction(btn.getAttribute('data-action'));
      });
    });

    document.addEventListener('contextmenu', (e) => {
      const target = getEditableTarget(e.target);
      if (!target) {
        hideContextMenu();
        return;
      }
      e.preventDefault();
      ctxTarget = target;
      if (target === editor || target.isContentEditable) {
        setEditorRangeFromPoint(e.clientX, e.clientY);
      }
      debugLog('contextmenu_open', {
        target: (target === editor || target.isContentEditable) ? 'editor' : (target.id || target.tagName || 'field'),
      });
      updateContextMenuState();
      ctxMenu.hidden = false;
      const pad = 6;
      const menuRect = ctxMenu.getBoundingClientRect();
      const maxLeft = Math.max(pad, window.innerWidth - menuRect.width - pad);
      const maxTop = Math.max(pad, window.innerHeight - menuRect.height - pad);
      ctxMenu.style.left = `${Math.min(e.clientX, maxLeft)}px`;
      ctxMenu.style.top = `${Math.min(e.clientY, maxTop)}px`;
    });
    document.addEventListener('click', (e) => {
      if (!ctxMenu.hidden && !ctxMenu.contains(e.target)) hideContextMenu();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !ctxMenu.hidden) {
        e.preventDefault();
        hideContextMenu();
      }
    }, true);
    window.addEventListener('blur', hideContextMenu);
    window.addEventListener('resize', hideContextMenu);
    editor.addEventListener('scroll', hideContextMenu);

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
        try:
            log_event(
                "rich_editor.init",
                f"title_len={len(str(initial_payload.get('title', '') or ''))} html_len={len(str(initial_payload.get('html', '') or ''))}",
                RICH_EDITOR_LOG_PATH,
            )
        except Exception:
            pass

    def save_content(self, payload: Any) -> bool:
        try:
            if isinstance(payload, dict):
                log_event(
                    "rich_editor.save_content",
                    f"title_len={len(str(payload.get('title', '') or ''))} html_len={len(str(payload.get('html', '') or ''))}",
                    RICH_EDITOR_LOG_PATH,
                )
            else:
                log_event("rich_editor.save_content", "payload_type=non_dict", RICH_EDITOR_LOG_PATH)
        except Exception:
            pass
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
        log_event("rich_editor.cancel", "user_cancelled", RICH_EDITOR_LOG_PATH)
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
        return True

    def debug_log(self, event: Any, details: Any = None) -> bool:
        try:
            event_name = str(event or "event")
            if isinstance(details, dict):
                bits = []
                for key in sorted(details.keys()):
                    bits.append(f"{key}={details.get(key)!r}")
                msg = ", ".join(bits)
            else:
                msg = repr(details)
            log_event(f"rich_editor.js.{event_name}", msg, RICH_EDITOR_LOG_PATH)
        except Exception:
            pass
        return True

    def read_clipboard_text(self) -> str:
        if os.name != "nt":
            return ""
        user32, kernel32 = _win_clipboard_dlls()
        CF_UNICODETEXT = 13
        if not user32.OpenClipboard(None):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                log_event("rich_editor.clipboard.text", "GlobalLock failed", RICH_EDITOR_LOG_PATH)
                return ""
            try:
                text = ctypes.wstring_at(ptr) or ""
                log_event("rich_editor.clipboard.text", f"len={len(text)}", RICH_EDITOR_LOG_PATH)
                return text
            except Exception:
                log_exception("rich_editor.read_clipboard_text decode failed", RICH_EDITOR_LOG_PATH)
                return ""
            finally:
                try:
                    kernel32.GlobalUnlock(handle)
                except Exception:
                    pass
        finally:
            try:
                user32.CloseClipboard()
            except Exception:
                pass

    def read_clipboard_payload(self) -> dict[str, str]:
        payload = {"text": "", "html": "", "image_data_url": ""}
        try:
            payload["html"] = _get_clipboard_html_fragment_windows()
        except Exception:
            payload["html"] = ""
            log_exception("rich_editor.read_clipboard_payload html failed", RICH_EDITOR_LOG_PATH)
        try:
            payload["text"] = self.read_clipboard_text()
        except Exception:
            payload["text"] = ""
            log_exception("rich_editor.read_clipboard_payload text failed", RICH_EDITOR_LOG_PATH)
        try:
            payload["image_data_url"] = _clipboard_image_data_url_windows()
        except Exception:
            payload["image_data_url"] = ""
            log_exception("rich_editor.read_clipboard_payload image failed", RICH_EDITOR_LOG_PATH)
        log_event(
            "rich_editor.clipboard.payload",
            f"text_len={len(payload['text'])} html_len={len(payload['html'])} has_image={bool(payload['image_data_url'])}",
            RICH_EDITOR_LOG_PATH,
        )
        return payload


def _cf_html_offset(header_text: str, key: str) -> int:
    match = re.search(rf"{re.escape(key)}:(\d+)", header_text)
    if not match:
        return -1
    try:
        return int(match.group(1))
    except Exception:
        return -1


def _get_clipboard_html_fragment_windows() -> str:
    if os.name != "nt":
        return ""
    try:
        user32, kernel32 = _win_clipboard_dlls()
        fmt_id = user32.RegisterClipboardFormatW("HTML Format")
    except Exception:
        log_exception("rich_editor.RegisterClipboardFormatW(HTML Format) failed", RICH_EDITOR_LOG_PATH)
        return ""
    if not fmt_id:
        log_event("rich_editor.clipboard.html", "fmt_id=0", RICH_EDITOR_LOG_PATH)
        return ""
    if not user32.OpenClipboard(None):
        log_event("rich_editor.clipboard.html", "OpenClipboard failed", RICH_EDITOR_LOG_PATH)
        return ""
    try:
        handle = user32.GetClipboardData(fmt_id)
        if not handle:
            log_event("rich_editor.clipboard.html", "GetClipboardData empty", RICH_EDITOR_LOG_PATH)
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            log_event("rich_editor.clipboard.html", "GlobalLock failed", RICH_EDITOR_LOG_PATH)
            return ""
        try:
            size = kernel32.GlobalSize(handle)
            if not size:
                return ""
            raw = ctypes.string_at(ptr, size)
        finally:
            try:
                kernel32.GlobalUnlock(handle)
            except Exception:
                pass
    finally:
        try:
            user32.CloseClipboard()
        except Exception:
            pass

    text = raw.decode("utf-8", errors="replace").rstrip("\x00")
    log_event("rich_editor.clipboard.html", f"raw_bytes={len(raw)} decoded_len={len(text)}", RICH_EDITOR_LOG_PATH)
    if not text:
        return ""
    if "StartFragment:" not in text:
        return text
    try:
        start_html = _cf_html_offset(text, "StartHTML")
        end_html = _cf_html_offset(text, "EndHTML")
        start_frag = _cf_html_offset(text, "StartFragment")
        end_frag = _cf_html_offset(text, "EndFragment")
        if min(start_html, end_html, start_frag, end_frag) < 0:
            return text
        html_bytes = raw[start_html:end_html]
        html_text = html_bytes.decode("utf-8", errors="replace")
        rel_start = max(0, start_frag - start_html)
        rel_end = max(rel_start, end_frag - start_html)
        fragment = html_text[rel_start:rel_end]
        return fragment.strip() or html_text.strip()
    except Exception:
        return text


def _clipboard_image_data_url_windows() -> str:
    if os.name != "nt":
        return ""
    try:
        from PIL import ImageGrab
    except Exception:
        log_event("rich_editor.clipboard.image", "PIL.ImageGrab unavailable", RICH_EDITOR_LOG_PATH)
        return ""
    try:
        clip = ImageGrab.grabclipboard()
    except Exception:
        log_exception("rich_editor.ImageGrab.grabclipboard failed", RICH_EDITOR_LOG_PATH)
        return ""
    if clip is None or isinstance(clip, list) or not hasattr(clip, "save"):
        clip_kind = type(clip).__name__ if clip is not None else "None"
        log_event("rich_editor.clipboard.image", f"clip_type={clip_kind}", RICH_EDITOR_LOG_PATH)
        return ""
    buffer = io.BytesIO()
    try:
        clip.save(buffer, format="PNG")
    except Exception:
        log_exception("rich_editor.clipboard.image save PNG failed", RICH_EDITOR_LOG_PATH)
        return ""
    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    log_event("rich_editor.clipboard.image", f"png_bytes={len(buffer.getvalue())}", RICH_EDITOR_LOG_PATH)
    return f"data:image/png;base64,{b64}"


def run_editor(payload: dict[str, Any]) -> dict[str, Any]:
    import webview  # optional dependency

    log_event("rich_editor.run", "start", RICH_EDITOR_LOG_PATH)
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
        log_event("rich_editor.run", "webview.start gui=edgechromium", RICH_EDITOR_LOG_PATH)
        webview.start(gui="edgechromium", **start_kwargs)
    except TypeError:
        log_event("rich_editor.run", "webview.start fallback TypeError", RICH_EDITOR_LOG_PATH)
        webview.start(**start_kwargs)
    except Exception:
        log_exception("rich_editor.webview.start edgechromium failed", RICH_EDITOR_LOG_PATH)
        webview.start(**start_kwargs)
    log_event(
        "rich_editor.run",
        f"webview.closed cancelled={api.cancelled} has_result={api.result is not None}",
        RICH_EDITOR_LOG_PATH,
    )

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

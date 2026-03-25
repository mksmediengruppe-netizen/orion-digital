"""
ORION Visual Browser Automation
================================
Extends browser_agent.py with Manus-style visual element tagging:
- Screenshots with numbered bounding boxes on interactive elements
- Coordinate-based clicking (like Manus browser_click)
- Element indexing for precise interaction
- Viewport-aware scrolling

Mirrors Manus AI browser tools:
  browser_navigate, browser_view, browser_click, browser_input,
  browser_scroll, browser_find_keyword, browser_save_image
"""

import logging
import json
import base64
import os
import time
from typing import Dict, List, Optional, Any

logger = logging.getLogger("visual_browser")

# Try to import Playwright
_playwright_available = False
try:
    from playwright.sync_api import sync_playwright
    _playwright_available = True
except ImportError:
    logger.warning("[VISUAL_BROWSER] Playwright not installed")


class VisualBrowser:
    """
    Visual browser automation with element tagging and bounding boxes.
    Each interactive element gets a numbered index for precise interaction.
    """

    def __init__(self):
        self._pw = None
        self._browser = None
        self._page = None
        self._elements: List[Dict] = []
        self._viewport = {"width": 1280, "height": 800}
        self._is_open = False

    def _ensure_browser(self):
        """Ensure browser is launched."""
        if self._is_open and self._page:
            return
        if not _playwright_available:
            raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")
        
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )
        ctx = self._browser.new_context(
            viewport=self._viewport,
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self._page = ctx.new_page()
        self._is_open = True
        logger.info("[VISUAL_BROWSER] Browser launched")

    def _tag_elements(self) -> List[Dict]:
        """
        Find all interactive elements and assign numbered indices.
        Returns list of {index, tag, text, bbox, selector}.
        """
        if not self._page:
            return []

        js_code = """
        () => {
            const interactiveSelectors = [
                'a[href]', 'button', 'input', 'select', 'textarea',
                '[role="button"]', '[role="link"]', '[role="tab"]',
                '[onclick]', '[tabindex]', 'summary',
                '[contenteditable="true"]'
            ];
            
            const elements = [];
            const seen = new Set();
            let index = 0;
            
            for (const selector of interactiveSelectors) {
                for (const el of document.querySelectorAll(selector)) {
                    if (seen.has(el)) continue;
                    seen.add(el);
                    
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    if (rect.top > window.innerHeight + 100) continue;
                    
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    if (parseFloat(style.opacity) < 0.1) continue;
                    
                    const text = (el.textContent || el.value || el.placeholder || 
                                  el.getAttribute('aria-label') || el.title || '').trim().slice(0, 80);
                    
                    elements.push({
                        index: index++,
                        tag: el.tagName.toLowerCase(),
                        type: el.type || '',
                        text: text,
                        bbox: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        },
                        selector: el.id ? '#' + el.id : 
                                  el.className ? el.tagName.toLowerCase() + '.' + el.className.split(' ')[0] : 
                                  el.tagName.toLowerCase(),
                        visible: rect.top >= 0 && rect.top < window.innerHeight
                    });
                }
            }
            return elements;
        }
        """
        try:
            self._elements = self._page.evaluate(js_code)
            return self._elements
        except Exception as e:
            logger.error(f"[VISUAL_BROWSER] Tag elements error: {e}")
            return []

    def _annotate_screenshot(self) -> Optional[str]:
        """
        Take screenshot and overlay numbered bounding boxes on interactive elements.
        Returns base64-encoded PNG.
        """
        if not self._page:
            return None

        try:
            # Draw bounding boxes via JS overlay
            self._page.evaluate("""
            () => {
                // Remove old overlays
                document.querySelectorAll('.orion-bbox-overlay').forEach(el => el.remove());
                
                const interactiveSelectors = [
                    'a[href]', 'button', 'input', 'select', 'textarea',
                    '[role="button"]', '[role="link"]', '[onclick]'
                ];
                
                const seen = new Set();
                let index = 0;
                
                for (const selector of interactiveSelectors) {
                    for (const el of document.querySelectorAll(selector)) {
                        if (seen.has(el)) continue;
                        seen.add(el);
                        
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) continue;
                        if (rect.top > window.innerHeight) continue;
                        
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') continue;
                        
                        // Create overlay box
                        const box = document.createElement('div');
                        box.className = 'orion-bbox-overlay';
                        box.style.cssText = `
                            position: fixed;
                            left: ${rect.x}px; top: ${rect.y}px;
                            width: ${rect.width}px; height: ${rect.height}px;
                            border: 2px solid #FF4444;
                            background: rgba(255, 68, 68, 0.1);
                            pointer-events: none;
                            z-index: 999999;
                        `;
                        
                        // Create label
                        const label = document.createElement('div');
                        label.className = 'orion-bbox-overlay';
                        label.textContent = index;
                        label.style.cssText = `
                            position: fixed;
                            left: ${rect.x - 2}px; top: ${rect.y - 16}px;
                            background: #FF4444; color: white;
                            font-size: 10px; font-weight: bold;
                            padding: 1px 4px; border-radius: 2px;
                            pointer-events: none; z-index: 1000000;
                            font-family: monospace;
                        `;
                        
                        document.body.appendChild(box);
                        document.body.appendChild(label);
                        index++;
                    }
                }
            }
            """)

            # Take screenshot
            screenshot = self._page.screenshot(full_page=False)
            
            # Remove overlays
            self._page.evaluate("""
            () => document.querySelectorAll('.orion-bbox-overlay').forEach(el => el.remove())
            """)

            return base64.b64encode(screenshot).decode("ascii")

        except Exception as e:
            logger.error(f"[VISUAL_BROWSER] Screenshot error: {e}")
            return None

    # ═══════════════════════════════════════════
    # PUBLIC API — mirrors Manus browser tools
    # ═══════════════════════════════════════════

    def navigate(self, url: str, focus: str = None) -> Dict:
        """Navigate to URL. Like Manus browser_navigate."""
        self._ensure_browser()
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(1)
            
            elements = self._tag_elements()
            screenshot_b64 = self._annotate_screenshot()
            
            # Extract page text
            text_content = self._page.evaluate("() => document.body?.innerText?.slice(0, 5000) || ''")
            
            return {
                "success": True,
                "url": self._page.url,
                "title": self._page.title(),
                "elements": [
                    f"{e['index']}[:]<{e['tag']}>{e['text']}</{e['tag']}>"
                    for e in elements if e.get("visible")
                ],
                "text_content": text_content,
                "screenshot_base64": screenshot_b64,
                "viewport": self._viewport,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def view(self) -> Dict:
        """View current page state. Like Manus browser_view."""
        if not self._page:
            return {"success": False, "error": "No page open"}
        
        elements = self._tag_elements()
        screenshot_b64 = self._annotate_screenshot()
        text_content = self._page.evaluate("() => document.body?.innerText?.slice(0, 5000) || ''")
        
        return {
            "success": True,
            "url": self._page.url,
            "title": self._page.title(),
            "elements": [
                f"{e['index']}[:]<{e['tag']}>{e['text']}</{e['tag']}>"
                for e in elements if e.get("visible")
            ],
            "text_content": text_content,
            "screenshot_base64": screenshot_b64,
        }

    def click(self, index: int = None, coordinate_x: float = None, 
              coordinate_y: float = None) -> Dict:
        """Click element by index or coordinates. Like Manus browser_click."""
        if not self._page:
            return {"success": False, "error": "No page open"}
        
        try:
            if index is not None:
                # Find element by index
                el = next((e for e in self._elements if e["index"] == index), None)
                if not el:
                    return {"success": False, "error": f"Element {index} not found"}
                
                cx = el["bbox"]["x"] + el["bbox"]["width"] / 2
                cy = el["bbox"]["y"] + el["bbox"]["height"] / 2
                self._page.mouse.click(cx, cy)
                
            elif coordinate_x is not None and coordinate_y is not None:
                self._page.mouse.click(coordinate_x, coordinate_y)
            else:
                return {"success": False, "error": "Provide index or coordinates"}
            
            time.sleep(0.5)
            return {"success": True, "action": "click"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    def input_text(self, text: str, index: int = None,
                   coordinate_x: float = None, coordinate_y: float = None,
                   press_enter: bool = False) -> Dict:
        """Input text into element. Like Manus browser_input."""
        if not self._page:
            return {"success": False, "error": "No page open"}
        
        try:
            if index is not None:
                el = next((e for e in self._elements if e["index"] == index), None)
                if not el:
                    return {"success": False, "error": f"Element {index} not found"}
                cx = el["bbox"]["x"] + el["bbox"]["width"] / 2
                cy = el["bbox"]["y"] + el["bbox"]["height"] / 2
            elif coordinate_x is not None and coordinate_y is not None:
                cx, cy = coordinate_x, coordinate_y
            else:
                return {"success": False, "error": "Provide index or coordinates"}
            
            self._page.mouse.click(cx, cy, click_count=3)  # select all
            self._page.keyboard.type(text)
            
            if press_enter:
                self._page.keyboard.press("Enter")
            
            return {"success": True, "action": "input", "text": text[:50]}
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    def scroll(self, direction: str = "down", target: str = "page") -> Dict:
        """Scroll page. Like Manus browser_scroll."""
        if not self._page:
            return {"success": False, "error": "No page open"}
        
        try:
            delta = {"down": 600, "up": -600, "left": -400, "right": 400}
            dx = delta.get(direction, 0) if direction in ("left", "right") else 0
            dy = delta.get(direction, 0) if direction in ("up", "down") else 0
            
            self._page.mouse.wheel(dx, dy)
            time.sleep(0.3)
            
            return {"success": True, "action": "scroll", "direction": direction}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def find_keyword(self, keyword: str) -> Dict:
        """Find text on page. Like Manus browser_find_keyword."""
        if not self._page:
            return {"success": False, "error": "No page open"}
        
        try:
            result = self._page.evaluate(f"""
            () => {{
                const text = document.body.innerText;
                const keyword = {json.dumps(keyword)};
                const idx = text.toLowerCase().indexOf(keyword.toLowerCase());
                if (idx === -1) return null;
                const start = Math.max(0, idx - 100);
                const end = Math.min(text.length, idx + keyword.length + 100);
                return {{
                    found: true,
                    context: text.slice(start, end),
                    position: idx
                }};
            }}
            """)
            
            if result:
                return {"success": True, **result}
            return {"success": False, "error": f"'{keyword}' not found on page"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    def close(self):
        """Close browser."""
        try:
            if self._page:
                self._page.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except:
            pass
        self._is_open = False
        self._page = None
        self._browser = None
        self._pw = None


# ── Tool schemas ──

VISUAL_BROWSER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navigate browser to a URL. Returns interactive elements with numbered indices, page text, and annotated screenshot with bounding boxes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to (include https://)"},
                    "focus": {"type": "string", "description": "Topic to focus on when reading the page"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_view",
            "description": "View current browser page state. Returns elements list, text content, and annotated screenshot.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element by its index number or by coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "Element index from the elements list"},
                    "coordinate_x": {"type": "number", "description": "X coordinate to click"},
                    "coordinate_y": {"type": "number", "description": "Y coordinate to click"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_input",
            "description": "Type text into an input field by index or coordinates. Clears existing text first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                    "index": {"type": "integer", "description": "Element index"},
                    "press_enter": {"type": "boolean", "description": "Press Enter after typing"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll the page in a direction (up, down, left, right).",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]}
                },
                "required": ["direction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_find_keyword",
            "description": "Search for a keyword on the current page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Text to search for"}
                },
                "required": ["keyword"]
            }
        }
    },
]

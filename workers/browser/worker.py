"""
ARCANE Browser Worker
Full browser automation via Playwright with LLM vision.

Capabilities:
  - Navigate to URLs, take screenshots
  - Click elements by index or coordinates
  - Fill forms, select dropdowns
  - Scroll pages, find text
  - Execute JavaScript in console
  - Upload files, save images
  - Takeover mode: hand control to user
  - Wizard navigator: autonomously walk through multi-step web wizards

The agent sees annotated screenshots with numbered interactive elements
and can interact with them by index or coordinates.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Any, Optional

from shared.utils.logger import get_logger, log_with_data

logger = get_logger("workers.browser")


class BrowserWorker:
    """
    Manages a Playwright browser instance for web automation.
    Provides screenshot-based interaction for the LLM agent.
    """

    def __init__(self, headless: bool = True, screenshots_dir: str = "/root/workspace/screenshots"):
        self._headless = headless
        self._screenshots_dir = screenshots_dir
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self._initialized = False
        self._elements_cache: list[dict] = []
        os.makedirs(screenshots_dir, exist_ok=True)

    async def initialize(self) -> None:
        """Initialize Playwright browser. Safe to call multiple times."""
        if self._initialized and self._browser is not None and self._page is not None:
            try:
                if not self._page.is_closed():
                    return
            except Exception:
                pass
            # Page is closed — reset and reinitialize
            self._initialized = False
            self._browser = None
            self._context = None
            self._page = None
            self._playwright = None

        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-zygote",
                    "--no-default-browser-check",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-hang-monitor",
                    "--disable-prompt-on-repost",
                    "--force-color-profile=srgb",
                    "--use-angle=swiftshader-webgl",
                    "--num-raster-threads=4",
                ],
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            self._page = await self._context.new_page()
            self._initialized = True
            logger.info("Browser initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            raise

    async def close(self) -> None:
        """Close the browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._initialized = False

    # ───────────────────────────────────────────────────────────────────────
    # Core navigation and interaction
    # ───────────────────────────────────────────────────────────────────────

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> dict:
        """Navigate to a URL and return page info with screenshot."""
        await self.initialize()

        try:
            response = await self._page.goto(url, wait_until=wait_until, timeout=90000)
            await asyncio.sleep(1)  # Wait for dynamic content

            elements = await self._get_interactive_elements()
            annotated = await self._take_annotated_screenshot(elements)
            content = await self._extract_content()
            return {
                "url": self._page.url,
                "title": await self._page.title(),
                "status": response.status if response else None,
                "screenshot": annotated["path"],
                "screenshot_b64": annotated["base64"],
                "elements": elements[:50],
                "content": content[:5000],
                "element_count": len(elements),
            }
        except Exception as e:
            return {"error": str(e), "url": url}

    async def click(self, index: int = None, x: float = None, y: float = None) -> dict:
        """Click an element by index or coordinates."""
        await self.initialize()

        try:
            if index is not None and index < len(self._elements_cache):
                element = self._elements_cache[index]
                selector = element.get("selector", "")
                if selector:
                    await self._page.click(selector, timeout=5000)
                else:
                    bbox = element.get("bbox", {})
                    await self._page.mouse.click(
                        bbox.get("x", 0) + bbox.get("width", 0) / 2,
                        bbox.get("y", 0) + bbox.get("height", 0) / 2,
                    )
            elif x is not None and y is not None:
                await self._page.mouse.click(x, y)
            else:
                return {"error": "Provide either index or coordinates"}

            await asyncio.sleep(0.5)
            elements_after = await self._get_interactive_elements()
            annotated = await self._take_annotated_screenshot(elements_after)

            return {
                "success": True,
                "screenshot": annotated["path"],
                "screenshot_b64": annotated["base64"],
                "elements": elements[:50],
                "url": self._page.url,
            }
        except Exception as e:
            return {"error": str(e)}

    async def input_text(
        self,
        text: str,
        index: int = None,
        x: float = None,
        y: float = None,
        press_enter: bool = False,
    ) -> dict:
        """Type text into an input field."""
        await self.initialize()

        try:
            if index is not None and index < len(self._elements_cache):
                element = self._elements_cache[index]
                selector = element.get("selector", "")
                if selector:
                    await self._page.fill(selector, text, timeout=5000)
                    if press_enter:
                        await self._page.press(selector, "Enter")
            elif x is not None and y is not None:
                await self._page.mouse.click(x, y)
                await self._page.keyboard.press("Control+a")
                await self._page.keyboard.type(text)
                if press_enter:
                    await self._page.keyboard.press("Enter")
            else:
                return {"error": "Provide either index or coordinates"}

            await asyncio.sleep(0.5)
            elements_after = await self._get_interactive_elements()
            annotated = await self._take_annotated_screenshot(elements_after)
            return {"success": True, "screenshot": annotated["path"], "screenshot_b64": annotated["base64"]}
        except Exception as e:
            return {"error": str(e)}

    async def scroll(self, direction: str = "down", amount: int = 500, to_end: bool = False) -> dict:
        """Scroll the page."""
        await self.initialize()

        try:
            if to_end:
                if direction == "down":
                    await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                elif direction == "up":
                    await self._page.evaluate("window.scrollTo(0, 0)")
            else:
                delta_x = 0
                delta_y = 0
                if direction == "down":
                    delta_y = amount
                elif direction == "up":
                    delta_y = -amount
                elif direction == "right":
                    delta_x = amount
                elif direction == "left":
                    delta_x = -amount
                await self._page.mouse.wheel(delta_x, delta_y)

            await asyncio.sleep(0.5)
            elements = await self._get_interactive_elements()
            annotated = await self._take_annotated_screenshot(elements)

            return {
                "success": True,
                "screenshot": annotated["path"],
                "screenshot_b64": annotated["base64"],
                "elements": elements[:50],
            }
        except Exception as e:
            return {"error": str(e)}

    async def find_text(self, keyword: str) -> dict:
        """Find text on the page."""
        await self.initialize()

        try:
            content = await self._page.content()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            text = soup.get_text()

            matches = []
            lower_text = text.lower()
            lower_keyword = keyword.lower()
            start = 0
            while True:
                idx = lower_text.find(lower_keyword, start)
                if idx == -1:
                    break
                context_start = max(0, idx - 50)
                context_end = min(len(text), idx + len(keyword) + 50)
                matches.append(text[context_start:context_end])
                start = idx + 1
                if len(matches) >= 10:
                    break

            return {
                "found": len(matches) > 0,
                "count": len(matches),
                "matches": matches,
            }
        except Exception as e:
            return {"error": str(e)}

    async def execute_js(self, javascript: str) -> dict:
        """Execute JavaScript in the browser console."""
        await self.initialize()

        try:
            result = await self._page.evaluate(javascript)
            return {"success": True, "result": str(result)[:5000]}
        except Exception as e:
            return {"error": str(e)}

    async def save_image(self, x: float, y: float, save_dir: str, base_name: str) -> dict:
        """Save an image from the page at the given coordinates."""
        await self.initialize()

        try:
            os.makedirs(save_dir, exist_ok=True)
            # Find image element near coordinates
            image_info = await self._page.evaluate(f"""
                (() => {{
                    const el = document.elementFromPoint({x}, {y});
                    if (el && el.tagName === 'IMG') {{
                        return {{ src: el.src, alt: el.alt }};
                    }}
                    return null;
                }})()
            """)

            if image_info and image_info.get("src"):
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.get(image_info["src"])
                    ext = ".png"
                    ct = resp.headers.get("content-type", "")
                    if "jpeg" in ct or "jpg" in ct:
                        ext = ".jpg"
                    elif "gif" in ct:
                        ext = ".gif"
                    elif "webp" in ct:
                        ext = ".webp"

                    filepath = os.path.join(save_dir, f"{base_name}{ext}")
                    with open(filepath, "wb") as f:
                        f.write(resp.content)
                    return {"success": True, "path": filepath}

            return {"error": "No image found at coordinates"}
        except Exception as e:
            return {"error": str(e)}

    async def get_view(self) -> dict:
        """Get current page state: screenshot + elements + content."""
        await self.initialize()

        elements = await self._get_interactive_elements()
        annotated = await self._take_annotated_screenshot(elements)
        content = await self._extract_content()

        return {
            "url": self._page.url,
            "title": await self._page.title(),
            "screenshot": annotated["path"],
            "screenshot_b64": annotated["base64"],
            "elements": elements[:50],
            "content": content[:5000],
        }

    async def get_current_url(self) -> str:
        """Get the current page URL."""
        if self._page:
            return self._page.url
        return ""

    async def get_page_text(self) -> str:
        """Get full text content of the current page."""
        return await self._extract_content()

    async def take_screenshot(self) -> str:
        """Public method to take a screenshot and return path."""
        return await self._take_screenshot()

    async def select_option(self, selector: str, value: str) -> dict:
        """Select an option in a dropdown by selector and value."""
        await self.initialize()
        try:
            await self._page.select_option(selector, value=value, timeout=5000)
            await asyncio.sleep(0.5)
            elements_after = await self._get_interactive_elements()
            annotated = await self._take_annotated_screenshot(elements_after)
            return {"success": True, "screenshot": annotated["path"], "screenshot_b64": annotated["base64"]}
        except Exception as e:
            return {"error": str(e)}

    async def type_text(self, selector: str, value: str) -> dict:
        """Type text into a field identified by CSS selector."""
        await self.initialize()
        try:
            await self._page.fill(selector, value, timeout=5000)
            await asyncio.sleep(0.3)
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ───────────────────────────────────────────────────────────────────────
    # Wizard Navigator — autonomous multi-step wizard completion
    # ───────────────────────────────────────────────────────────────────────

    async def navigate_wizard(
        self,
        start_url: str,
        wizard_data: dict,
        max_steps: int = 20,
        screenshot_each_step: bool = True,
        playbook_hints: list[str] | None = None,
        completion_markers: list[str] | None = None,
    ) -> dict:
        """
        Autonomously navigate a multi-step web wizard (CMS installer, setup flow, etc.).

        Cycle:
        1. Take screenshot of current page
        2. Send screenshot + page text to LLM (Vision)
        3. LLM determines: which fields to fill, which buttons to click
        4. Execute actions (input, click, select, wait)
        5. Wait for next step to load
        6. Repeat until final screen or max_steps

        Args:
            start_url: URL to begin the wizard
            wizard_data: Dict with data for form fields (db_host, admin_login, etc.)
            max_steps: Maximum steps before giving up
            screenshot_each_step: Whether to save screenshots at each step
            playbook_hints: Optional list of step hints from CMS playbook
            completion_markers: Text markers that indicate wizard completion

        Returns:
            Dict with success status, steps completed, and final URL
        """
        await self.initialize()
        await self.navigate(start_url)

        steps_completed = []
        completion_markers = completion_markers or [
            "успешно установлен", "установка завершена", "Installation complete",
            "Congratulations", "Поздравляем", "Success", "Готово", "Done",
        ]

        for step in range(max_steps):
            # 1. Screenshot
            screenshot_path = await self._take_screenshot()
            page_text = await self._extract_content()

            # 2. Check completion markers in page text
            for marker in completion_markers:
                if marker.lower() in page_text.lower():
                    logger.info(f"Wizard completed at step {step + 1}: found marker '{marker}'")
                    return {
                        "success": True,
                        "steps_completed": steps_completed,
                        "final_url": self._page.url,
                        "completion_marker": marker,
                    }

            # 3. Analyze wizard step via LLM
            analysis = await self._analyze_wizard_step(
                screenshot_path, page_text, wizard_data, steps_completed, playbook_hints
            )

            if not analysis:
                logger.warning(f"Wizard step {step + 1}: LLM analysis failed")
                return {
                    "success": False,
                    "reason": "analysis_failed",
                    "steps_completed": steps_completed,
                }

            # 4. Check if wizard is complete (LLM says so)
            if analysis.get("wizard_complete"):
                return {
                    "success": True,
                    "steps_completed": steps_completed,
                    "final_url": self._page.url,
                }

            # 5. Check if human intervention needed
            if analysis.get("needs_human"):
                return {
                    "success": False,
                    "reason": "needs_human",
                    "action": analysis.get("human_action", "take_over_browser"),
                    "message": analysis.get("human_message", "Manual intervention required"),
                    "steps_completed": steps_completed,
                }

            # 6. Execute actions
            actions = analysis.get("actions", [])
            action_results = []
            for action in actions:
                result = await self._execute_wizard_action(action)
                action_results.append(result)

            steps_completed.append({
                "step": step + 1,
                "url": self._page.url,
                "actions": actions,
                "results": action_results,
                "screenshot": screenshot_path if screenshot_each_step else None,
            })

            logger.info(f"Wizard step {step + 1}: executed {len(actions)} actions")

            # 7. Wait for page to load/update
            await asyncio.sleep(2)

        return {
            "success": False,
            "reason": "max_steps_exceeded",
            "steps_completed": steps_completed,
        }

    async def _execute_wizard_action(self, action: dict) -> dict:
        """Execute a single wizard action (input, click, select, wait, checkbox)."""
        action_type = action.get("type", "")
        selector = action.get("selector", "")
        value = action.get("value", "")

        try:
            if action_type == "input":
                # Try fill first, fall back to type
                try:
                    await self._page.fill(selector, value, timeout=5000)
                except Exception:
                    await self._page.click(selector, timeout=5000)
                    await self._page.keyboard.press("Control+a")
                    await self._page.keyboard.type(value)
                return {"success": True, "action": action_type, "selector": selector}

            elif action_type == "click":
                await self._page.click(selector, timeout=5000)
                await asyncio.sleep(0.5)
                return {"success": True, "action": action_type, "selector": selector}

            elif action_type == "select":
                await self._page.select_option(selector, value=value, timeout=5000)
                return {"success": True, "action": action_type, "selector": selector}

            elif action_type == "checkbox":
                is_checked = await self._page.is_checked(selector)
                if not is_checked:
                    await self._page.check(selector, timeout=5000)
                return {"success": True, "action": action_type, "selector": selector}

            elif action_type == "wait":
                seconds = action.get("seconds", 2)
                await asyncio.sleep(seconds)
                return {"success": True, "action": "wait", "seconds": seconds}

            else:
                return {"error": f"Unknown action type: {action_type}"}

        except Exception as e:
            logger.warning(f"Wizard action failed: {action_type} {selector} — {e}")
            return {"error": str(e), "action": action_type, "selector": selector}

    async def _analyze_wizard_step(
        self,
        screenshot_path: str,
        page_text: str,
        wizard_data: dict,
        history: list[dict],
        playbook_hints: list[str] | None = None,
    ) -> Optional[dict]:
        """
        Use LLM to analyze the current wizard step and decide what to do.
        Returns a dict with actions to perform, or None on failure.
        """
        hints_text = ""
        if playbook_hints:
            hints_text = f"\nPlaybook hints for this wizard:\n" + "\n".join(
                f"  - {h}" for h in playbook_hints
            )

        prompt = f"""You are navigating a web wizard (installer/setup flow).

Available data for filling forms:
{json.dumps(wizard_data, ensure_ascii=False, indent=2)}

Steps already completed: {len(history)}
{hints_text}

Current page text (first 3000 chars):
{page_text[:3000]}

Task:
1. Identify which form fields are visible on the page
2. Fill them with data from wizard_data (match field names/labels to data keys)
3. Find the "Next" / "Continue" / "Install" / "Submit" / "Далее" / "Продолжить" button
4. If you see a CAPTCHA or OAuth login — set needs_human: true
5. If the page shows a success/completion message — set wizard_complete: true

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "wizard_complete": false,
  "needs_human": false,
  "human_message": "",
  "actions": [
    {{"type": "input", "selector": "#field_id", "value": "data_value"}},
    {{"type": "checkbox", "selector": "#agree"}},
    {{"type": "click", "selector": "button[type=submit]"}}
  ]
}}

Action types: input, click, select, checkbox, wait
For selectors use: #id, [name=field], .class, button[type=submit], etc."""

        try:
            # Use the LLM router to analyze the wizard step
            # P1-3 FIX: ModelRouter requires (client, strategy, budget_limit) — was called bare
            from shared.llm.router import ModelRouter
            from shared.llm.client import UnifiedLLMClient
            from config.settings import get_config
            _cfg = get_config()
            _llm_client = UnifiedLLMClient(_cfg)
            router = ModelRouter(client=_llm_client, strategy="balance", budget_limit=5.0)

            response = await router.route(
                role="browser",
                messages=[
                    {"role": "system", "content": "You are a wizard navigator. Analyze web forms and return JSON actions."},
                    {"role": "user", "content": prompt},
                ],
            )

            # Parse the LLM response as JSON
            response_text = response.content if hasattr(response, "content") else response.get("content", "")
            # Clean up response — remove markdown code blocks if present
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            return json.loads(response_text.strip())

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse wizard analysis JSON: {e}")
            return None
        except Exception as e:
            logger.warning(f"Wizard analysis failed: {e}")
            return None

    # ───────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ───────────────────────────────────────────────────────────────────────

    async def _take_screenshot(self) -> str:
        """Take a screenshot and return the file path."""
        timestamp = int(time.time() * 1000)
        filepath = os.path.join(self._screenshots_dir, f"screenshot_{timestamp}.png")
        await self._page.screenshot(path=filepath, full_page=False)
        return filepath

    async def _take_annotated_screenshot(self, elements: list[dict] | None = None) -> dict:
        """
        Take a screenshot, annotate it with numbered boxes for interactive elements,
        and return both the file path and base64-encoded image.
        This gives the LLM vision — it can SEE the page, not just read its text.
        """
        timestamp = int(time.time() * 1000)
        filepath = os.path.join(self._screenshots_dir, f"screenshot_{timestamp}.png")
        await self._page.screenshot(path=filepath, full_page=False)

        # Annotate with PIL — draw numbered boxes on interactive elements
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.open(filepath)
            draw = ImageDraw.Draw(img)

            # Draw numbered boxes on each interactive element
            if elements:
                for el in elements[:30]:
                    bbox = el.get("bbox", {})
                    if not bbox:
                        continue
                    x, y = bbox.get("x", 0), bbox.get("y", 0)
                    w, h = bbox.get("width", 0), bbox.get("height", 0)
                    if w == 0 or h == 0:
                        continue
                    idx = el.get("index", 0)
                    # Draw rectangle
                    draw.rectangle([x, y, x + w, y + h], outline="#FF3B30", width=2)
                    # Draw index label
                    label = str(idx)
                    draw.rectangle([x, y - 16, x + len(label) * 8 + 4, y], fill="#FF3B30")
                    try:
                        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
                    except Exception:
                        font = ImageFont.load_default()
                    draw.text((x + 2, y - 15), label, fill="white", font=font)

            # Save annotated version
            annotated_path = filepath.replace(".png", "_annotated.png")
            img.save(annotated_path)

            # Convert to base64
            with open(annotated_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            return {"path": annotated_path, "base64": b64, "original_path": filepath}
        except Exception as e:
            logger.warning(f"Annotation failed (non-fatal): {e}")
            # Fallback: return plain screenshot as base64
            try:
                with open(filepath, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                return {"path": filepath, "base64": b64, "original_path": filepath}
            except Exception:
                return {"path": filepath, "base64": None, "original_path": filepath}

    async def _get_interactive_elements(self) -> list[dict]:
        """Get all interactive elements on the page with their properties."""
        try:
            elements = await self._page.evaluate("""
                (() => {
                    const interactiveSelectors = 'a, button, input, select, textarea, [role="button"], [onclick], [tabindex]';
                    const elements = document.querySelectorAll(interactiveSelectors);
                    const results = [];
                    const viewport = { width: window.innerWidth, height: window.innerHeight };

                    elements.forEach((el, idx) => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) return;
                        if (rect.bottom < 0 || rect.top > viewport.height) return;
                        if (rect.right < 0 || rect.left > viewport.width) return;

                        const tag = el.tagName.toLowerCase();
                        const text = (el.textContent || '').trim().substring(0, 50);
                        const type = el.getAttribute('type') || '';
                        const placeholder = el.getAttribute('placeholder') || '';
                        const href = el.getAttribute('href') || '';
                        const name = el.getAttribute('name') || '';
                        const value = el.value || '';

                        results.push({
                            index: results.length,
                            tag: tag,
                            text: text,
                            type: type,
                            placeholder: placeholder,
                            href: href,
                            name: name,
                            value: value.substring(0, 50),
                            bbox: {
                                x: Math.round(rect.x),
                                y: Math.round(rect.y),
                                width: Math.round(rect.width),
                                height: Math.round(rect.height)
                            }
                        });
                    });

                    return results;
                })()
            """)

            self._elements_cache = elements
            return elements

        except Exception as e:
            logger.warning(f"Failed to get interactive elements: {e}")
            return []

    async def _extract_content(self) -> str:
        """Extract text content from the page."""
        try:
            content = await self._page.evaluate("""
                (() => {
                    const clone = document.body.cloneNode(true);
                    clone.querySelectorAll('script, style, noscript').forEach(el => el.remove());
                    return clone.innerText;
                })()
            """)
            return content or ""
        except Exception:
            return ""

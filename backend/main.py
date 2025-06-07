import os
import re
import json
import logging
import shutil
import asyncio
import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
from dotenv import load_dotenv
from starlette.websockets import WebSocketState
from fastapi.staticfiles import StaticFiles

from .mcp_client import MCPClient
from anthropic import Anthropic, APIError
from bs4 import BeautifulSoup
import httpx
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import urljoin

# ─── Logging & env ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

# ─── Constants ─────────────────────────────────────────────────────────────
CLONED_PROJECT_DIR = "cloned_project"

PRE_SUMMARY_SYSTEM_PROMPT = (
    "Summarise the layout & styling cues of this fragment in <120 words>. "
    "Focus on: semantic tags used, approximate visual hierarchy, key CSS "
    "classes/inline styles, colours, fonts, spacing rhythm, noticeable JS-driven "
    "behaviour.  DO NOT mention that you are an AI, and do NOT add markdown."
)

ANALYSIS_SYSTEM_PROMPT = """
You are Vision-Sonnet acting as a senior UI/UX analyst.
You receive a JSON payload called `designContext` with every fact our
scraper & AI-Vision tools could extract from the target URL, e.g.

{
  "pageUrl": "...",
  "viewportScreenshot": "<base64-png>",
  "domTree": "... raw outerHTML OR pre-summaries ...",
  "computedStyles": { "...": "..." },
  "layoutTree": [...],
  "colorPalette": ["#0F172A", "#F1F5F9", "#14B8A6", ...],
  "fontFamilies": ["Inter", "Roboto Slab"],
  "assets": { "logo": "...png", "heroBg": "...jpg", ...},
  "interactiveElements": [
      {"role":"button","text":"Get started",...},
      ...
  ],
  "breakpoints": { "md": 768, "lg": 1024, "xl": 1280 }
}

–––– TASK ––––
1  Mentally inspect every field (silently) to infer layout, spacing rhythm,
  typographic scale and responsive breakpoints.
2  Return a **single JSON array** called `sectionPlan`.
   Each item must include:
     • "tag" – semantic HTML5 tag (header, nav, main, section, article, aside, footer, dialog)
     • "componentName" – PascalCase cue (e.g. HeroSection)
     • "description" – what the section does & key style hints (layout, palette,
                       fonts, shadows, border radius, animation cues, ARIA behaviours)
     • "children" – nested sub-components (same schema) or [].

Return ONLY the raw JSON; no markdown, no comments.
"""

HTML_GENERATION_SYSTEM_PROMPT = """
You are Opus (Claude) acting as a precise front-end coder.
You receive:
  • `sectionPlan` – the analysed structure.
  • `designContext` – colour palette, assets, breakpoints, etc.

TASK
Produce a *single* valid HTML5 file (`index.html`) that recreates the look
using **Tailwind CSS classes only**.  Only add a <style> block for things
Tailwind cannot express (e.g. custom @keyframes).

Requirements
• Semantic tags; no React / JSX.
• Link Tailwind CDN:
    <script src="https://cdn.tailwindcss.com"></script>
• IMPORTANT: For all images (<img> src, favicons, etc.), use the local paths provided in `designContext.assets`. This is a map from the original remote URL to a new local path. If a URL from the original site exists as a key in `designContext.assets`, you MUST use its corresponding value as the new path.
• Honour breakpoints from `designContext.breakpoints`.
• Add alt text + ARIA labels from context.
• Keep reasoning internal; output ONLY the finished HTML, no markdown fences.
"""

BUG_FIXING_SYSTEM_PROMPT = """
You are Opus doing a final lint & fix pass.
Input:
  • The full HTML produced by Haiku.
  • (Optional) A list of build-time or Lighthouse errors.

Return the corrected *full* HTML file—no snippets, no ``` fences.
If no issues exist, return the original HTML verbatim.
"""

MODIFICATION_SYSTEM_PROMPT = """
You are an expert front-end developer. You will be given the content of an HTML file and a user request for modification.
Your task is to return the **full, complete, and valid** HTML content with the requested modification applied.
Ensure your output is only the raw HTML code. Do not include any explanations, comments, or markdown fences like ```html.
"""

# ─── Utility helpers ────────────────────────────────────────────────────────
def write_file(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Wrote %s", path)

def json_default_serializer(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return str(obj)

# ─── WebSocket notifier ─────────────────────────────────────────────────────
class WebSocketEventNotifier:
    def __init__(self, ws: WebSocket):
        self.ws = ws

    async def _send(self, event: str, data: dict):
        await self.ws.send_json({"event": event, "data": data})

    async def log(self, msg: str):
        await self._send("log", {"message": msg})

    async def ai_token(self, tok: str):
        await self._send("ai_token", {"token": tok})

    async def file_event(self, typ: str, path: str, content: str = "", old: str = ""):
        await self._send(typ, {"path": path, "content": content, "old_content": old})

    async def status_update(self, status: str):
        await self._send("status", {"status": status})

    async def close(self):
        await self.ws.close()

# ─── Pydantic model ─────────────────────────────────────────────────────────
class CloneUrlRequest(BaseModel):
    url: HttpUrl

# ─── Core service class ─────────────────────────────────────────────────────
class AppState:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY env var is missing.")
        self.llm = Anthropic(api_key=api_key)
        self.mcp_client = MCPClient()

    # --- token/char helper (rough) ---
    def _split_into_chunks(self, text: str, size: int) -> list[str]:
        return [text[i:i + size] for i in range(0, len(text), size)]

    # --- security ---
    def _sanitize_html(self, html: str) -> str:
        return re.sub(r"<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>",
                      "", html, flags=re.IGNORECASE | re.DOTALL)

    # --- Asset Pipeline Helpers ---
    def _create_placeholder_image(self, file_path: str, size: tuple[int, int] = (800, 600)):
        """Creates a gray placeholder image with text."""
        try:
            img = Image.new('RGB', size, color = 'grey')
            d = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("arial.ttf", 40)
            except IOError:
                font = ImageFont.load_default()
            
            text = os.path.basename(file_path)
            d.text((10,10), f"Placeholder for\n{text}", fill='white', font=font)
            img.save(file_path)
            logger.info("Created placeholder for %s", file_path)
        except Exception as e:
            logger.error("Failed to create placeholder image %s: %s", file_path, e)

    async def _prefetch_assets(self, html_content: str, page_url: str, notif: WebSocketEventNotifier) -> dict[str, str]:
        """Finds all images/icons, downloads them, and returns a map of remote_url -> local_path."""
        await notif.log("Starting asset prefetch process...")
        logger.info("Starting asset prefetch for URL: %s", page_url)
        
        soup = BeautifulSoup(html_content, 'lxml')
        asset_dir = os.path.join(CLONED_PROJECT_DIR, "assets")
        os.makedirs(asset_dir, exist_ok=True)
        
        asset_map = {}
        # Find images in <img> tags and <link rel="icon"> tags
        urls_to_fetch = [img['src'] for img in soup.find_all('img') if img.get('src')]
        urls_to_fetch += [link['href'] for link in soup.find_all('link', rel=re.compile(r'icon', re.I)) if link.get('href')]

        await notif.log(f"Found {len(set(urls_to_fetch))} unique assets to process...")
        logger.info("Found %d unique assets to process", len(set(urls_to_fetch)))

        async with httpx.AsyncClient() as client:
            for url in set(urls_to_fetch): # Use set to avoid duplicate downloads
                if not url or url.startswith('data:'):
                    continue

                # Resolve relative URLs to absolute URLs
                abs_src = urljoin(page_url, url)
                
                # Create a sanitized, unique filename
                try:
                    ext = os.path.splitext(abs_src.split('?')[0])[1] or '.png' # Default extension
                    filename_hash = hashlib.sha1(abs_src.encode()).hexdigest()[:10]
                    filename = f"{filename_hash}{ext}"
                    local_path = os.path.join(asset_dir, filename)
                    # Path for the browser to use in the <img src="...">
                    local_preview_path = f"/preview/assets/{filename}"
                except Exception as e:
                    await notif.log(f"Skipping invalid asset URL: {url} ({e})")
                    logger.warning("Skipping invalid asset URL: %s (%s)", url, e)
                    continue

                if abs_src in asset_map: # Already processed
                    continue

                try:
                    await notif.log(f"Prefetching asset: {abs_src}")
                    logger.info("Prefetching asset: %s", abs_src)
                    response = await client.get(abs_src, follow_redirects=True, timeout=10)
                    response.raise_for_status()

                    with open(local_path, 'wb') as f:
                        f.write(response.content)
                    
                    asset_map[abs_src] = local_preview_path
                    asset_map[url] = local_preview_path # Also map original URL
                    logger.info("Successfully downloaded asset: %s -> %s", abs_src, local_preview_path)

                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    await notif.log(f"Failed to download {abs_src}: {e}. Creating placeholder.")
                    logger.warning("Failed to download %s: %s. Creating placeholder.", abs_src, e)
                    self._create_placeholder_image(local_path)
                    asset_map[abs_src] = local_preview_path
                    asset_map[url] = local_preview_path # Also map original URL

        await notif.log(f"Asset prefetch complete. Processed {len(asset_map)} assets.")
        logger.info("Asset prefetch complete. Processed %d assets", len(asset_map))
        return asset_map

    async def _post_process_and_download_remaining_assets(self, html_content: str, page_url: str, notif: WebSocketEventNotifier) -> str:
        """(Fallback) Finds any remaining remote image URLs, downloads them, and rewrites the HTML."""
        await notif.log("Starting post-processing of remaining assets...")
        logger.info("Starting post-processing of remaining assets for URL: %s", page_url)
        
        soup = BeautifulSoup(html_content, 'lxml')
        asset_dir = os.path.join(CLONED_PROJECT_DIR, "assets")
        os.makedirs(asset_dir, exist_ok=True)
        
        img_tags = soup.find_all('img')
        await notif.log(f"Found {len(img_tags)} image tags to check...")
        logger.info("Found %d image tags to check", len(img_tags))
        
        async with httpx.AsyncClient() as client:
            for i, img in enumerate(img_tags):
                src = img.get('src')
                if not src or src.startswith(('/preview/assets/', '/assets/')) or src.startswith('data:'):
                    continue # Skip local or data URI images

                # Resolve relative URLs to absolute URLs
                abs_src = urljoin(page_url, src)
                
                # Create a sanitized filename
                filename = f"fallback_{i}_{os.path.basename(abs_src).split('?')[0]}"
                local_path = os.path.join(asset_dir, filename)
                
                try:
                    await notif.log(f"Downloading fallback asset: {abs_src}")
                    logger.info("Downloading fallback asset: %s", abs_src)
                    response = await client.get(abs_src, follow_redirects=True, timeout=10)
                    response.raise_for_status()

                    with open(local_path, 'wb') as f:
                        f.write(response.content)
                    
                    # Rewrite the src to the new local path for the preview
                    img['src'] = f"/preview/assets/{filename}"
                    logger.info("Successfully downloaded fallback asset: %s -> %s", abs_src, filename)

                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    await notif.log(f"Failed to download fallback {abs_src}: {e}. Creating placeholder.")
                    logger.warning("Failed to download fallback %s: %s. Creating placeholder.", abs_src, e)
                    self._create_placeholder_image(local_path)
                    img['src'] = f"/preview/assets/{filename}"
        
        await notif.log("Post-processing of remaining assets complete.")
        logger.info("Post-processing of remaining assets complete")
        return str(soup)

    # --- ① two-pass DOM compression ---
    async def _summarise_long_dom(self, raw_html: str) -> str:
        CHARS = 12000      # ≈3k tokens
        parts = self._split_into_chunks(raw_html, CHARS)
        summaries = []
        for chunk in parts:
            piece = ""
            with self.llm.messages.stream(
                model="claude-3-haiku-20240307",
                max_tokens=512,
                system=PRE_SUMMARY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": chunk}],
            ) as stream:
                for tok in stream.text_stream:
                    piece += tok
            summaries.append(piece.strip())
        tail = raw_html[:2000] + "\n...\n" + raw_html[-2000:]
        return "\n\n".join(summaries) + "\n\nRAW_SAMPLE:\n" + tail

    # --- ② Vision-Sonnet analysis ---
    async def _analyze_design_context_streaming(self, ctx: dict,
                                                notif: WebSocketEventNotifier) -> str:
        await notif.log("Starting DOM summarization...")
        logger.info("Starting DOM summarization")
        ctx["domTree"] = await self._summarise_long_dom(ctx["domTree"])
        await notif.log("DOM summarization complete. Starting design analysis...")
        logger.info("DOM summarization complete. Starting design analysis")
        
        user_msg = json.dumps({"designContext": ctx}, default=json_default_serializer)

        result = ""
        with self.llm.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            logger.info(f"Stream object type: {type(stream)}")
            logger.info(f"Stream object attributes: {dir(stream)}")
            logger.info(f"Stream object: {stream}")
            
            # Check if stream has expected methods
            if hasattr(stream, 'text_stream'):
                logger.info("Stream has text_stream attribute")
            else:
                logger.warning("Stream missing text_stream attribute")
                
            # Log stream state before iteration
            logger.info("About to iterate over stream.text_stream")
            for t in stream.text_stream:
                await notif.ai_token(t)
                result += t
        
        await notif.log("Design analysis complete.")
        logger.info("Design analysis complete")
        return result

    # --- ③ Haiku HTML generation ---
    async def _generate_html_streaming(self, section_plan: str, ctx: dict,
                                       notif: WebSocketEventNotifier) -> str:
        await notif.log("Starting HTML generation...")
        logger.info("Starting HTML generation")
        
        payload = json.dumps(
            {"sectionPlan": json.loads(section_plan), "designContext": ctx},
            default=json_default_serializer,
        )
        html = ""
        with self.llm.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=HTML_GENERATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
        ) as stream:
            for tok in stream.text_stream:
                await notif.ai_token(tok)
                html += tok
        
        await notif.log("HTML generation complete.")
        logger.info("HTML generation complete")
        return html

    # --- (optional) bug-fix pass with Opus ---
    async def _fix_html_streaming(self, html: str,
                                  notif: WebSocketEventNotifier) -> str:
        await notif.log("Starting HTML bug-fix pass...")
        logger.info("Starting HTML bug-fix pass")
        
        fixed = ""
        with self.llm.messages.stream(
            model="claude-opus-4-20250514",
            max_tokens=4096,
            system=BUG_FIXING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": html}],
        ) as stream:
            for tok in stream.text_stream:
                await notif.ai_token(tok)
                fixed += tok
        
        await notif.log("HTML bug-fix pass complete.")
        logger.info("HTML bug-fix pass complete")
        return fixed

    # --- Code Modification ---
    async def modify_code_streaming(self, prompt: str, notif: WebSocketEventNotifier):
        try:
            await notif.log("Starting code modification process...")
            logger.info("Starting code modification with prompt: %s", prompt)
            
            # For now, assume we're only modifying index.html
            file_path = os.path.join(CLONED_PROJECT_DIR, "index.html")
            if not os.path.exists(file_path):
                await notif.log("Error: index.html not found to modify.")
                logger.error("index.html not found at path: %s", file_path)
                return

            await notif.log(f"Applying modification: '{prompt}'...")
            logger.info("Applying modification: %s", prompt)
            
            with open(file_path, "r", encoding="utf-8") as f:
                current_content = f.read()

            await notif.log("Sending modification request to AI...")
            logger.info("Sending modification request to AI")

            user_message = f"USER REQUEST: {prompt}\n\nCURRENT HTML:\n```html\n{current_content}\n```"
            
            modified_content = ""
            with self.llm.messages.stream(
                model="claude-3-opus-20240229",
                max_tokens=8192, # Allow for larger files
                system=MODIFICATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                async for tok in stream.text_stream:
                    await notif.ai_token(tok)
                    modified_content += tok

            await notif.log("Processing AI response...")
            logger.info("Processing AI response")

            # Basic cleanup of the response
            final_content = re.sub(r'```html\n(.*?)\n```', r'\1', modified_content, flags=re.S).strip()

            await notif.log("Writing modified content to file...")
            logger.info("Writing modified content to file: %s", file_path)
            
            write_file(file_path, final_content)
            await notif.file_event("file_update", "index.html", content=final_content, old=current_content)
            await notif.log("✅ Modification complete!")
            logger.info("Code modification complete")

        except APIError as e:
            logger.error("Anthropic API Error during modification: %s", e)
            await notif.log(f"AI Error: {e.body.get('error', {}).get('message', 'Unknown API error')}")
        except Exception as e:
            logger.error("Modification error: %s", e, exc_info=True)
            await notif.log(f"Error during modification: {e}")

    # --- Orchestrator ---
    async def clone_website(self, url: HttpUrl, notif: WebSocketEventNotifier):
        try:
            await notif.status_update("generating")
            await notif.log("Starting website cloning process...")
            logger.info("Starting website cloning for URL: %s", url)
            
            await notif.log("Cleaning output directory …")
            logger.info("Cleaning output directory: %s", CLONED_PROJECT_DIR)
            if os.path.exists(CLONED_PROJECT_DIR):
                shutil.rmtree(CLONED_PROJECT_DIR)
            os.makedirs(CLONED_PROJECT_DIR, exist_ok=True)

            # 1. Scrape with AI-Vision MCP
            await notif.log("Connecting to AI-Vision server …")
            logger.info("Connecting to AI-Vision MCP server")
            await self.mcp_client.connect_to_server("mcp-ai-vision-debug-ui-automation")

            await notif.log(f"Navigating to {url} …")
            logger.info("Navigating to URL: %s", url)
            await self.mcp_client.session.call_tool("playwright_navigate", {"url": str(url)})

            # Pull rich context
            await notif.log("Gathering design context …")
            logger.info("Gathering design context")
            
            await notif.log("Taking screenshot...")
            logger.info("Taking screenshot")
            screenshot = await self.mcp_client.session.call_tool(
                "screenshot_url", {"url": str(url), "fullPage": True})
            # print("test screenshot content", screenshot.content[0])
            
            await notif.log("Inspecting DOM structure...")
            logger.info("Inspecting DOM structure")
            dom_info = await self.mcp_client.session.call_tool(
                "dom_inspector", {"url": str(url), "selector": "html","includeChildren": True, "includeStyles": True})
            # await notif.log(f"test dom_info.content {dom_info}")
            
            await notif.log("Running enhanced page analysis...")
            logger.info("Running enhanced page analysis")
            analysis = await self.mcp_client.session.call_tool(
                "enhanced_page_analyzer", {"url": str(url), "mapElements": True, "fullPage": True})
            # print("test analysis content", analysis.content[0])

            await notif.log("Building design context...")
            logger.info("Building design context")
            design_ctx = {
                "pageUrl": str(url),
                "viewportScreenshot": screenshot.content[0],
                "domTree": str(dom_info.content[0]),
                "analysis": str(analysis.content[0]),
            }

            # Prefetch assets and add them to the design context
            await notif.log("Prefetching assets...")
            logger.info("Starting asset prefetch")
            asset_map = await self._prefetch_assets(design_ctx["domTree"], str(url), notif)
            design_ctx["assets"] = asset_map

            await notif.log("Sanitizing HTML content...")
            logger.info("Sanitizing HTML content")
            design_ctx["domTree"] = self._sanitize_html(design_ctx.get("domTree", ""))

            # Close session
            await notif.log("Closing MCP session...")
            logger.info("Closing MCP session")
            await self.mcp_client.cleanup()

            # 2. AI analysis
            await notif.log("AI (Sonnet): analysing layout …")
            logger.info("Starting AI layout analysis")
            section_plan = await self._analyze_design_context_streaming(design_ctx, notif)

            # await notif.log(f"section_plan: {section_plan}")
            # 3. HTML generation
            await notif.log("AI (Haiku): generating Tailwind HTML …")
            logger.info("Starting HTML generation")
            raw_html = await self._generate_html_streaming(section_plan, design_ctx, notif)

            # 4. Bug-fix pass
            await notif.log("AI (Opus): fixing potential HTML errors …")
            logger.info("Starting HTML bug-fix pass")
            fixed_html = await self._fix_html_streaming(raw_html, notif)

            # 5. Asset Pipeline: Download images and rewrite paths
            await notif.log("Post-processing assets (images)...")
            logger.info("Starting asset post-processing")
            final_html = await self._post_process_and_download_remaining_assets(fixed_html, str(url), notif)

            # 6. Write index.html
            await notif.log("Writing final HTML file...")
            logger.info("Writing final HTML file")
            file_path = os.path.join(CLONED_PROJECT_DIR, "index.html")
            write_file(file_path, final_html)
            await notif.file_event("file_create", "index.html", final_html)

            await notif.status_update("ready")
            await notif.log("✅ Cloning complete – open cloned_project/index.html!")
            logger.info("Website cloning complete for URL: %s", url)

        except Exception as e:
            logger.error("Clone error: %s", e, exc_info=True)
            await notif.status_update("error")
            await notif.log(f"Error: {e}")
        finally:
            # Keep connection open for modifications
            pass

# ─── FastAPI setup ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup …")
    try:
        app.state.service = AppState()
        yield
    finally:
        logger.info("Shutdown …")

app = FastAPI(title="HTML-Tailwind Cloner", lifespan=lifespan)

# CORS (adjust front-end origins if needed)
origins = [f"http://localhost:{p}" for p in (3000, 3001, 3002, 8000)] + \
          [f"http://127.0.0.1:{p}" for p in (3000, 3001, 3002, 8000)]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ─── WebSocket endpoint ─────────────────────────────────────────────────────
@app.websocket("/ws/clone")
async def websocket_clone(ws: WebSocket):
    await ws.accept()
    notifier = WebSocketEventNotifier(ws)
    clone_task = None
    try:
        # The first message must be the clone request
        req = await ws.receive_json()
        
        if 'url' in req:
            clone_req = CloneUrlRequest(**req)
            # Run cloning in the background
            clone_task = asyncio.create_task(
                ws.app.state.service.clone_website(clone_req.url, notifier)
            )
        else:
            await notifier.log("Invalid initial request. Expected a URL.")
            await ws.close(code=1011)
            return
            
        # Listen for subsequent modification requests
        while ws.application_state == WebSocketState.CONNECTED:
            data = await ws.receive_json()
            if data.get('type') == 'modification':
                prompt = data.get('prompt')
                if prompt:
                    await ws.app.state.service.modify_code_streaming(prompt, notifier)
            
    except WebSocketDisconnect:
        logger.info("Client disconnected.")
        if clone_task and not clone_task.done():
            clone_task.cancel()
    except Exception as e:
        logger.error("WS error: %s", e, exc_info=True)
        if ws.application_state == WebSocketState.CONNECTED:
            try:
                await notifier.log(str(e))
                await ws.close(code=1011)
            except:
                pass

# ─── Simple helpers for UI preview ─────────────────────────────────────────
@app.get("/files/tree")
async def files_tree():
    tree = []
    for root, _, files in os.walk(CLONED_PROJECT_DIR):
        if not os.path.exists(CLONED_PROJECT_DIR):
            return {"tree": []}
        rel = os.path.relpath(root, CLONED_PROJECT_DIR)
        for f in files:
            tree.append(os.path.join("" if rel == "." else rel, f))
    return {"tree": tree}

@app.get("/files/content")
async def file_content(path: str):
    fp = os.path.join(CLONED_PROJECT_DIR, path)
    if not (os.path.isfile(fp) and os.path.exists(fp)):
        raise HTTPException(404, "File not found")
    with open(fp, encoding="utf-8") as f:
        return {"content": f.read()}

@app.get("/")
async def root():
    return {"message": "Backend is running"} 

app.mount("/preview", StaticFiles(directory=CLONED_PROJECT_DIR, html=True), name="preview") 

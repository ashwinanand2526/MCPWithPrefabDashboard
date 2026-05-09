import json
import os
import sys
import subprocess
import urllib.parse
import urllib.request
import re
import time
import traceback
import shutil
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# Create the MCP server
mcp = FastMCP("AssignmentServer")

HERE = Path(__file__).parent
SANDBOX = HERE / "sandbox"

# Cleanup old sandbox files on startup
import shutil
if SANDBOX.exists():
    shutil.rmtree(SANDBOX, ignore_errors=True)
os.makedirs(SANDBOX, exist_ok=True)

GENERATED = SANDBOX / "dashboard_app.py"
LOG_PATH = SANDBOX / "prefab.log"
BACKUP_PATH = SANDBOX / ".last_good_app.py"

# ---------------------------------------------------------------------------
# Widget renderers and dashboard generator ported from prompt_to_app.py
# ---------------------------------------------------------------------------

def _slug(s: str, default: str = "k") -> str:
    out = re.sub(r"[^a-zA-Z0-9_]+", "_", str(s)).strip("_").lower()
    return out or default

def _safe(name: str, idx: int, default: str = "item") -> str:
    return _slug(name, default) or f"{default}_{idx}"

def widget_lines(w: dict, ctx: dict) -> list[str]:
    kind = w.get("kind", "")
    ctx["uid"] = ctx.get("uid", 0) + 1
    uid = ctx["uid"]

    if kind == "stat":
        label = w.get("label", "")
        value = str(w.get("value", ""))
        sub = w.get("sub", "")
        out = [
            'with Column(gap=1):',
            f'    Muted({label!r})',
            f'    H1({value!r})',
        ]
        if sub:
            out.append(f'    Muted({sub!r})')
        return out

    if kind == "badges":
        items = w.get("items", [])
        out = ['with Row(gap=2):']
        for it in items:
            lbl = it.get("label", "") if isinstance(it, dict) else str(it)
            var = it.get("variant", "default") if isinstance(it, dict) else "default"
            out.append(f'    Badge({lbl!r}, variant={var!r})')
        return out or ['Muted("(no badges)")']

    if kind == "checklist":
        items = w.get("items", [])
        title = w.get("title")
        out: list[str] = []
        if title:
            out += [f'H3({title!r})']
        out += ['with Column(gap=2):']
        for i, it in enumerate(items):
            label = it.get("label", f"Item {i+1}") if isinstance(it, dict) else str(it)
            out += [
                '    with Row(gap=3):',
                f'        Checkbox(name="cb_{uid}_{i}")',
                f'        Text({label!r})',
            ]
        return out

    if kind == "progress_list":
        items = w.get("items", [])
        title = w.get("title")
        out: list[str] = []
        if title:
            out += [f'H3({title!r})']
        out += ['with Column(gap=3):']
        for it in items:
            if not isinstance(it, dict):
                continue
            label = it.get("label", "")
            val = it.get("value", 0)
            try:
                val = max(0, min(100, int(val)))
            except Exception:
                val = 0
            out += [
                '    with Column(gap=1):',
                f'        Text({label!r})',
                f'        Progress(value={val})',
            ]
        return out

    if kind == "ring":
        label = w.get("label", "")
        value = w.get("value", 0)
        try:
            value = max(0, min(100, int(value)))
        except Exception:
            value = 0
        suffix = w.get("suffix", "%")
        display = f"{value}{suffix}" if suffix else f"{value}"
        out = ['with Column(gap=2):']
        if label:
            out.append(f'    H3({label!r})')
        out.append(f'    Ring(value={value}, label={display!r})')
        return out

    if kind == "pie":
        title = w.get("title", "")
        data = w.get("data", [])
        name_key = w.get("name_key", "name")
        value_key = w.get("value_key", "value")
        clean = []
        for row in data:
            if isinstance(row, dict) and name_key in row and value_key in row:
                clean.append({name_key: row[name_key], value_key: row[value_key]})
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out.append(
            f'    PieChart(data={clean!r}, data_key={value_key!r}, '
            f'name_key={name_key!r}, show_legend=True)'
        )
        return out

    if kind == "bar":
        title = w.get("title", "")
        data = w.get("data", [])
        x_key = w.get("x_key", "x")
        y_keys = w.get("y_keys", ["y"])
        if isinstance(y_keys, str):
            y_keys = [y_keys]
        series_lines = ", ".join(f'ChartSeries(data_key={yk!r}, label={yk!r})' for yk in y_keys)
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out += [
            f'    BarChart(data={data!r},',
            f'             series=[{series_lines}],',
            f'             x_axis={x_key!r}, show_legend={len(y_keys) > 1})',
        ]
        return out

    if kind == "line":
        title = w.get("title", "")
        data = w.get("data", [])
        x_key = w.get("x_key", "x")
        y_keys = w.get("y_keys", ["y"])
        if isinstance(y_keys, str):
            y_keys = [y_keys]
        series_lines = ", ".join(f'ChartSeries(data_key={yk!r}, label={yk!r})' for yk in y_keys)
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out += [
            f'    LineChart(data={data!r},',
            f'              series=[{series_lines}],',
            f'              x_axis={x_key!r}, show_legend={len(y_keys) > 1})',
        ]
        return out

    if kind == "sparkline":
        values = w.get("values", [])
        title = w.get("title", "")
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out.append(f'    Sparkline(data={values!r})')
        return out

    if kind == "table":
        title = w.get("title", "")
        columns = w.get("columns", [])
        rows = w.get("rows", [])
        out = ['with Column(gap=2):']
        if title:
            out.append(f'    H3({title!r})')
        out.append('    with Row(gap=3):')
        for col in columns:
            out.append(f'        Text({str(col)!r})')
        for row in rows:
            out.append('    with Row(gap=3):')
            cells = row if isinstance(row, list) else [row.get(c, "") for c in columns]
            for cell in cells:
                out.append(f'        Text({str(cell)!r})')
        return out

    if kind == "text":
        heading = w.get("heading", "")
        body = w.get("body", "")
        level = str(w.get("level", "h3")).lower()
        out = ['with Column(gap=1):']
        if heading:
            if level == "h1":
                out.append(f'    H1({heading!r})')
            elif level == "h2":
                out.append(f'    H2({heading!r})')
            else:
                out.append(f'    H3({heading!r})')
        if body:
            out.append(f'    Muted({body!r})')
        return out

    return [f'Muted({f"Unknown widget kind: {kind!r}"!r})']


def dashboard(title: str, tabs: list[dict]) -> str:
    if not tabs:
        tabs = [{"name": "Main", "widgets": [{"kind": "text", "heading": "Empty dashboard"}]}]

    ctx: dict = {"uid": 0}
    TAB_INDENT = " " * 24
    built_tabs: list[tuple[str, str, str]] = []
    for i, tab in enumerate(tabs):
        name = str(tab.get("name") or f"Tab {i+1}")
        value = _slug(tab.get("value") or name, f"tab_{i+1}")
        widgets = tab.get("widgets") or []
        body_lines: list[str] = []
        if not widgets:
            body_lines = [TAB_INDENT + 'Muted("(empty tab)")']
        else:
            for w in widgets:
                for line in widget_lines(w, ctx):
                    body_lines.append((TAB_INDENT + line) if line else "")
        built_tabs.append((name, value, "\n".join(body_lines)))

    first_value = built_tabs[0][1]

    parts = [
        "from prefab_ui.app import PrefabApp",
        "from prefab_ui.components import (",
        "    Badge, Button, Card, CardContent, CardHeader, CardTitle,",
        "    Checkbox, Column, H1, H2, H3, Muted, Progress, Ring, Row,",
        "    Tab, Tabs, Text,",
        ")",
        "from prefab_ui.components.charts import (",
        "    BarChart, ChartSeries, LineChart, PieChart, Sparkline,",
        ")",
        "",
        'with PrefabApp(css_class="max-w-5xl mx-auto p-6") as app:',
        "    with Card():",
        "        with CardHeader():",
        f"            CardTitle({title!r})",
        "        with CardContent():",
        f"            with Tabs(value={first_value!r}):",
    ]
    for name, value, body in built_tabs:
        parts.append(f'                with Tab({name!r}, value={value!r}):')
        parts.append("                    with Column(gap=5):")
        parts.append(body)
    return "\n".join(parts) + "\n"

def tail_log(log_path: Path, n: int = 30) -> str:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception as e:
        return f"(could not read log: {e})"

def save_backup() -> None:
    if GENERATED.exists():
        BACKUP_PATH.write_text(GENERATED.read_text(encoding="utf-8"), encoding="utf-8")

def restore_backup() -> bool:
    if BACKUP_PATH.exists():
        GENERATED.write_text(BACKUP_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        return True
    return False

class PrefabServer:
    def __init__(self, target: Path, log_path: Path):
        self.target = target
        self.log_path = log_path
        self._proc: subprocess.Popen | None = None
        self._log = None
        self.active_port = 5175

    def start(self) -> None:
        self._log = open(self.log_path, "a", encoding="utf-8")
        self._log.write("\n===== restart =====\n")
        self._log.flush()

        import traceback

        try:
            self._log.write("[DEBUG] Starting initialization...\n")
            self._log.write(f"[DEBUG] sys.executable: {sys.executable}\n")

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            prefab_cmd = os.path.join(
                os.path.dirname(sys.executable),
                "prefab.exe" if os.name == "nt" else "prefab"
            )
            self._log.write(f"[DEBUG] prefab_cmd exists: {os.path.exists(prefab_cmd)}\n")

            cmd_args = [prefab_cmd, "serve", self.target.name, "--port", "5175", "--reload"]
            self.active_port = 5175
            self._log.write(f"[DEBUG] Executing: {cmd_args} in cwd: {self.target.parent}\n")
            self._log.flush()

            self._proc = subprocess.Popen(
            cmd_args,
            cwd=self.target.parent,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            self._log.write(f"[DEBUG] Popen successful. PID: {self._proc.pid}\n")
            self._log.flush()

            # Poll the port until server is ready (up to 15 seconds)
            self._log.write("[DEBUG] Waiting for server to bind to port...\n")
            self._log.flush()
            for attempt in range(30):
                time.sleep(0.5)
                # Also check if process already died
                if self._proc.poll() is not None:
                        self._log.write(f"[ERROR] prefab process died during startup! Exit code: {self._proc.poll()}\n")
                        self._log.flush()
                        break
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{self.active_port}/", timeout=1
                    ) as r:
                        if r.status == 200:
                            self._log.write(f"[DEBUG] Server ready after {(attempt+1)*0.5:.1f}s\n")
                            self._log.flush()
                            return  # success
                except Exception:
                    pass
        
            self._log.write("[ERROR] Server did not respond after 15s\n")
            self._log.flush()

        except Exception:
            self._log.write(f"[ERROR] Exception during start:\n{traceback.format_exc()}\n")
            self._log.flush()

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None
        if self._log is not None:
            self._log.close()
            self._log = None

    def restart(self) -> None:
        self.stop()
        self.start()

global_server = PrefabServer(GENERATED, LOG_PATH)

# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def fetch_online_data(topic_or_url: str) -> str:
    """Fetch data from the internet. If a URL is provided, fetches the URL. Otherwise, searches Wikipedia.
    
    Args:
        topic_or_url: The topic to search for (e.g., 'Highest-grossing films') or a direct HTTP URL.
    """
    if topic_or_url.startswith("http://") or topic_or_url.startswith("https://"):
        url = topic_or_url
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                return response.read().decode('utf-8')[:10000]
        except Exception as e:
            return f"Error fetching URL: {str(e)}"
    else:
        search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(topic_or_url)}&utf8=&format=json"
        try:
            req = urllib.request.Request(search_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                search_results = data.get("query", {}).get("search", [])
                if not search_results:
                    return f"Topic '{topic_or_url}' not found on Wikipedia."
                
                title = search_results[0]["title"]
                
                page_url = f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1&titles={urllib.parse.quote(title)}&format=json"
                req_page = urllib.request.Request(page_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_page) as response_page:
                    page_data = json.loads(response_page.read().decode('utf-8'))
                    pages = page_data.get("query", {}).get("pages", {})
                    for page_id, page_info in pages.items():
                        extract = page_info.get("extract", "")
                        return f"Found Wikipedia page: {title}\n\n{extract[:15000]}"
                return "Failed to extract page content."
        except Exception as e:
            return f"Error searching Wikipedia: {str(e)}"

@mcp.tool()
def save_to_sandbox(filename: str, content: str) -> str:
    """Save content to a local file in the sandbox directory.
    
    Args:
        filename: Name of the file (e.g. 'films_data.json' or 'data.csv'). Use JSON or CSV format.
        content: The text content to write to the file.
    """
    os.makedirs(SANDBOX, exist_ok=True)
    filepath = SANDBOX / filename
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully saved to {filepath}"
    except Exception as e:
        return f"Failed to save file: {str(e)}"

@mcp.tool()
def read_from_sandbox(filename: str) -> str:
    """Read content from a local file in the sandbox directory. Use this to read JSON or CSV files to generate UI data.
    
    Args:
        filename: Name of the file (e.g. 'films_data.json').
    """
    filepath = SANDBOX / filename
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Failed to read file: {str(e)}"

@mcp.tool()
def render_prefab_dashboard(spec_json: str) -> str:
    """Generate a Prefab UI dashboard and start the web server to show it on localhost:5175.
    If the UI fails to render (e.g. syntax error), it rolls back to the previous successful dashboard.
    
    Args:
        spec_json: A JSON string specifying the dashboard layout and data. 
                   Format: {"title": "App Title", "tabs": [{"name": "Tab 1", "widgets": [...]}]}
    """
    try:
        spec = json.loads(spec_json)
    except Exception as e:
        return f"Error: spec_json is not valid JSON. {e}"

    title = spec.get("title", "Dynamic Dashboard")
    tabs = spec.get("tabs", [])
    
    try:
        source = dashboard(title, tabs)
        compile(source, "<generated_app>", "exec") # Syntax check
    except Exception as e:
        return f"Error generating or compiling dashboard code: {e}"

    save_backup()
    GENERATED.write_text(source, encoding="utf-8")
    os.utime(GENERATED, None)
    
    if not (global_server._proc and global_server._proc.poll() is None):
        global_server.start()  # start() already sleeps 1.5s
    else:
        time.sleep(1.0)  # already running — --reload picks up the file change
    
    log_tail = tail_log(LOG_PATH, 30)
    looks_broken = (
        global_server._proc is not None and global_server._proc.poll() is not None
    )
    
    if looks_broken:
        restored = restore_backup()
        if restored:
            global_server.restart()
            time.sleep(1.0)
            return f"Error: The new rendering failed and caused a crash. Rolled back to the previous app. Last logs:\n{log_tail}"
        else:
            return f"Error: The new rendering failed, and no backup was found to restore. Last logs:\n{log_tail}"
            
    import webbrowser
    webbrowser.open(f"http://127.0.0.1:{global_server.active_port}")
    return f"Dashboard successfully updated on http://127.0.0.1:{global_server.active_port}."

if __name__ == "__main__":
    mcp.run(transport="stdio")

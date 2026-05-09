import asyncio
import os
import sys
from concurrent.futures import TimeoutError

from dotenv import load_dotenv
from google import genai
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Load the .env from the parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

MODEL = "gemini-3.1-flash-lite-preview"
MAX_ITERATIONS = 8
LLM_SLEEP_SECONDS = 5
LLM_TIMEOUT = 120

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def generate_with_timeout(prompt: str, timeout: int = LLM_TIMEOUT):
    """Run the blocking Gemini call in a thread with a timeout."""
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: client.models.generate_content(model=MODEL, contents=prompt),
        ),
        timeout=timeout,
    )

def describe_tools(tools) -> str:
    lines = []
    for i, t in enumerate(tools, 1):
        props = (t.inputSchema or {}).get("properties", {})
        params = ", ".join(f"{n}: {p.get('type', '?')}" for n, p in props.items()) or "no params"
        lines.append(f"{i}. {t.name}({params}) — {t.description or ''}")
    return "\n".join(lines)

def coerce(value: str, schema_type: str):
    if schema_type == "integer":
        return int(value)
    if schema_type == "number":
        return float(value)
    if schema_type == "array":
        import ast
        try:
            return ast.literal_eval(value)
        except Exception:
            return value
    if schema_type == "boolean":
        return value.lower() in ("true", "1", "yes")
    return value

async def main():
    mcp_script_path = os.path.join(os.path.dirname(__file__), "mcp_server.py")
    
    server_params = StdioServerParameters(
        command="uv",
        args=["run", mcp_script_path],
    )
    # Note: if uv is not present, we fallback to python
    # For now, we assume uv run or just python is in path. 
    # Let's just use "python" directly to be safer if `uv` isn't configured for standard scripts
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[mcp_script_path],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected to Assignment MCP server")

            tools = (await session.list_tools()).tools
            tools_desc = describe_tools(tools)
            print(f"Loaded {len(tools)} tools\n")

            system_prompt = f"""You are a data-analyst agent working inside an MCP server environment.
You solve tasks by calling tools ONE AT A TIME and observing their results.

Available tools:
{tools_desc}

Respond with EXACTLY ONE line, in one of these two formats:
  FUNCTION_CALL: tool_name|arg1|arg2|...
  FINAL_ANSWER: <short natural-language summary of what you did>

Rules:
- Provide args in the exact order of the tool's parameters.
- Do not invent tools that are not listed above.
- After each FUNCTION_CALL you'll receive the result; use it to decide the next step.
- When formatting JSON strings for arguments, ensure it is valid JSON format without line breaks.
- If an API returns a lot of text, parse it carefully.
- Prefer the simplest tool sequence that solves the task.
- To display a dynamic UI, first use save_to_sandbox to save data (as JSON or CSV format).
- Then read the data using read_from_sandbox to analyze the available structure.
- Then call render_prefab_dashboard with a spec_json string formatted exactly like this:
  {{"title": "<app title>", "tabs": [{{"name": "<tab label>", "widgets": [ ... ]}}]}}
- Available widget kinds:
  {{"kind": "stat", "label": "...", "value": "..."}}
  {{"kind": "badges", "items": [{{"label": "...", "variant": "default|success|warning|destructive"}}]}}
  {{"kind": "pie", "title": "...", "data": [{{"name": "...", "value": 123}}]}}
  {{"kind": "bar", "title": "...", "data": [{{"x": "...", "y": 123}}], "x_key": "x", "y_keys": ["y"]}}
  {{"kind": "line", "title": "...", "data": [{{"x": "...", "y": 123}}], "x_key": "x", "y_keys": ["y"]}}
  {{"kind": "table", "title": "...", "columns": ["Col A"], "rows": [["v1"], ["v2"]]}}
  {{"kind": "text", "heading": "...", "body": "...", "level": "h3"}}
  
- After rendering the UI, wait for user input.
- If user asks for change in the existing UI, read the previous UI spec from the file and call render_prefab_dashboard with the updated spec_json string.
"""

            print("\n" + "="*50)
            print("Agent is ready! Type your request and press Enter.")
            print("Press Ctrl+C to exit at any time.")
            print("="*50)
            
            prompt_log_path = os.path.join(os.path.dirname(__file__), "sandbox", "prompt_log.txt")
            
            history: list[str] = []
            
            while True:
                try:
                    user_input = input("\nWhat more can I do for you? (Ctrl+C to exit): ").strip()
                    if not user_input:
                        continue
                    task = user_input
                except (KeyboardInterrupt, EOFError):
                    print("\nExiting agent loop.")
                    sys.exit(0)

                history.append(f"\n--- New Task: {task} ---")
                for iteration in range(1, MAX_ITERATIONS + 1):
                    print(f"\n--- Iteration {iteration} ---")

                    context = "\n".join(history) if history else "(no prior steps)"
                    prompt = (
                        f"{system_prompt}\n"
                        f"Task: {task}\n\n"
                        f"Previous steps:\n{context}\n\n"
                        f"What is your next single action?"
                    )

                    print(f"Sleeping {LLM_SLEEP_SECONDS}s before LLM call...")
                    
                    with open(prompt_log_path, "a", encoding="utf-8") as f:
                        f.write(f"\n=== Task: {task} | Iteration: {iteration} ===\n")
                        f.write(f"PROMPT:\n{prompt}\n")
                        f.write("=" * 50 + "\n")

                    await asyncio.sleep(LLM_SLEEP_SECONDS)

                    try:
                        response = await generate_with_timeout(prompt)
                    except (TimeoutError, asyncio.TimeoutError):
                        print("LLM timed out — stopping.")
                        break
                    except Exception as e:
                        print(f"LLM error: {e}")
                        break

                    text = (response.text or "").strip().splitlines()[0].strip()
                    print(f"LLM: {text}")

                    if text.startswith("FINAL_ANSWER:"):
                        print("\n=== Agent done ===")
                        print(text)
                        history.append(f"Iteration {iteration}: gave {text}")
                        break

                    if not text.startswith("FUNCTION_CALL:"):
                        print("Unexpected response format — stopping.")
                        break

                    _, call = text.split(":", 1)
                    parts = [p.strip() for p in call.split("|")]
                    func_name, raw_args = parts[0], parts[1:]

                    tool = next((t for t in tools if t.name == func_name), None)
                    if tool is None:
                        msg = f"Unknown tool {func_name!r}"
                        print(msg)
                        history.append(f"Iteration {iteration}: {msg}")
                        continue

                    props = (tool.inputSchema or {}).get("properties", {})
                    
                    # Make sure we don't try to zip more args than properties
                    if len(raw_args) > len(props):
                        raw_args = raw_args[:len(props)]
                    elif len(raw_args) < len(props):
                        # padding with empty strings
                        raw_args += [""] * (len(props) - len(raw_args))

                    arguments = {
                        name: coerce(val, info.get("type", "string"))
                        for (name, info), val in zip(props.items(), raw_args)
                    }

                    print(f"-> {func_name}({arguments})")
                    try:
                        result = await session.call_tool(func_name, arguments=arguments)
                        payload = (
                            result.content[0].text
                            if result.content and hasattr(result.content[0], "text")
                            else str(result)
                        )
                    except Exception as e:
                        payload = f"ERROR: {e}"

                    print(f"<- [Result length: {len(payload)} chars]")
                    history.append(
                        f"Iteration {iteration}: called {func_name}({arguments}) -> {payload}"
                    )
                else:
                    print(f"\nReached MAX_ITERATIONS({MAX_ITERATIONS}) without FINAL_ANSWER.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

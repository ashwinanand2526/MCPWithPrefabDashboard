# Agentic Dashboard Generator (MCP Server)

This project demonstrates an agentic workflow using the **Model Context Protocol (MCP)**. It consists of an intelligent agent (`agent.py`) powered by Gemini, communicating with an MCP server (`mcp_server.py`) that executes tools locally on the user's behalf. 

The primary use case showcased is dynamically fetching data, analyzing it, and generating an interactive dashboard UI using Prefab, all fully autonomous based on natural language requests.

## Architecture

- **`agent.py`**: The client application. It establishes a loop where it accepts a task from the user, forwards it to the LLM (Gemini), and iteratively processes tool calls. It dynamically maintains session context and tracks its thought processes in a prompt log.
- **`mcp_server.py`**: The FastMCP server. It implements the specific functions the agent can invoke, effectively granting the LLM safe access to local capabilities.
- **`sandbox/`**: A temporary directory managed by the MCP server for storing fetched data (`.json`, `.csv`), agent logs (`prompt_log.txt`), and the generated dashboard code.

## Available Tools (MCP Server)

The server provides four distinct capabilities:

1. **`fetch_online_data(topic_or_url)`**: Pulls raw data directly from Wikipedia or a specified URL.
2. **`save_to_sandbox(filename, content)`**: Dumps the fetched or analyzed data into the local `sandbox/` directory.
3. **`read_from_sandbox(filename)`**: Reads back data so the LLM can analyze its structure and decide how to visualize it.
4. **`render_prefab_dashboard(spec_json)`**: Accepts a JSON specification of UI components, generates Python code using the `prefab_ui` library, and serves an interactive dashboard. Features auto-recovery, rollback if the generated UI code is faulty, and robust process reuse across multiple renderings.

## Running the Project

1. Install dependencies:
   ```bash
   pip install mcp fastmcp google-genai python-dotenv
   # Additionally ensure prefab is installed if using the UI rendering capabilities
   ```
2. Configure your environment:
   Make sure you have a `.env` file at the root containing your Gemini API key:
   ```env
   GEMINI_API_KEY=your_api_key_here
   ```
3. Run the Agent:
   ```bash
   cd Assignment
   python agent.py
   ```
4. Enter natural language instructions such as:
   * "Find the top 5 highest grossing movies and show them to me on a dashboard."
   * "Create a heat map for the same data in a separate tab."

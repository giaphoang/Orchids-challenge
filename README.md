# Fullstack AI Cloner

This project consists of a backend built with FastAPI and a frontend built with Next.js and TypeScript that allows you to clone a website's design using AI.

## Project Structure

- `/backend`: The FastAPI application that handles the website cloning logic.
- `/frontend`: The Next.js application that provides the user interface.

## Quick Start (Local Development)

To get the application running locally, follow these steps in order.

### 1. Run the Backend

First, set up and run the Python backend.

1.  **Navigate to the backend directory:**
    ```bash
    cd backend
    ```

2.  **Set up the virtual environment and install dependencies:**
    This project uses `uv` for package management. The following command creates a virtual environment and installs all dependencies from `requirements.txt`.
    ```bash
    uv sync
    ```

3.  **Set up your environment variables:**
    You will need an Anthropic API key. Create a `.env` file in the `backend` directory and add your key:
    ```
    ANTHROPIC_API_KEY="your-api-key-here"
    ```

4.  **Run the backend server:**
    ```bash
    uv run fastapi dev
    ```
    The backend API will now be running at `http://localhost:8000`.

5. **Set up MCP server:**
    You will use https://glama.ai/mcp/servers/%40samihalawa/mcp-server-ai-vision MCP server to extract and scrape UI information from input URL
    ```bash
    npm install -g visual-ui-debug-agent-mcp
    ```
    This server already handle in backend logic and you don't need to run a separate server for this process. You can go to the link for more details about what this MCP server can do.

### 2. Run the Frontend

Next, set up and run the Next.js frontend in a separate terminal.

1.  **Navigate to the frontend directory:**
    ```bash
    cd frontend
    ```

2.  **Install dependencies:**
    ```bash
    pnpm install
    ```
    *If you encounter dependency conflicts, you may need to run `npm install --legacy-peer-deps`.*

3.  **Run the frontend development server:**
    ```bash
    pnpm dev
    ```
    The frontend will now be accessible at `http://localhost:3000`.



## Testing

A smoke test script is provided to verify the basic functionality of the `/clone` endpoint.

**Prerequisites:**

1.  Ensure the backend service are running. 

2.  The smoke test script requires the `requests` Python library. If you don't have it installed in the Python environment you'll use to run the script, install it with:
    ```bash
    pip install requests
    ```

**Running the Test:**

Navigate to the project root directory and run the script using Python:

```bash
python scripts/smoke_test.py
```

**Expected Outcome:**

-   The script will send a request to clone `https://example.com`.
-   On success, it will print a success message and create a folder name `cloned_project ` in `backend` folder
-   If there are errors (e.g., backend not reachable, cloning failed), it will print error messages to the console.

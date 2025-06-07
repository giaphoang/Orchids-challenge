import pytest
import os
import json
from unittest.mock import MagicMock, AsyncMock, patch

from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketState
from pydantic import HttpUrl

# Adjust the import path to be relative to the project structure
import sys
# This ensures that the tests can find the 'main' module and its dependencies
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app, AppState, CLONED_PROJECT_DIR

# --- Fixtures ---

@pytest.fixture
def client():
    """Fixture for the TestClient, used to test API endpoints."""
    with TestClient(app) as c:
        yield c

@pytest.fixture
def temp_project_dir(tmp_path):
    """Fixture to create a temporary directory for testing file operations."""
    project_path = tmp_path / CLONED_PROJECT_DIR
    project_path.mkdir()
    return project_path

# --- Unit Tests for AppState Core Logic ---

@pytest.mark.asyncio
async def test_summarise_long_dom_chunks_data():
    """Tests that a long HTML string is correctly chunked and summarized."""
    app_state = AppState()
    # Make the chunk size small to force chunking
    app_state._split_into_chunks = lambda text, size: [text[:size], text[size:]]

    mock_stream = AsyncMock()
    mock_stream.text_stream.__aiter__.return_value = ["summary1 "].__iter__()
    
    mock_stream2 = AsyncMock()
    mock_stream2.text_stream.__aiter__.return_value = ["summary2"].__iter__()

    # Have the mock return different values on subsequent calls
    app_state.llm.messages.stream = MagicMock(side_effect=[mock_stream, mock_stream2])

    long_html = "a" * 20000
    result = await app_state._summarise_long_dom(long_html)

    assert app_state.llm.messages.stream.call_count == 2
    assert "summary1" in result
    assert "summary2" in result
    assert "RAW_SAMPLE" in result


@pytest.mark.asyncio
async def test_analyze_design_context_streaming():
    """Tests the design context analysis, mocking the summarizer and LLM."""
    app_state = AppState()
    mock_notifier = AsyncMock()
    
    with patch.object(app_state, '_summarise_long_dom', new_callable=AsyncMock, return_value="summarized_dom") as mock_summarize:
        
        async def mock_text_stream():
            yield '{"sectionPlan":'
            yield '["Hero"]}'

        app_state.llm.messages.stream = MagicMock()
        app_state.llm.messages.stream.return_value.text_stream = mock_text_stream()
        
        test_context = {"domTree": "<html>...</html>"}
        result = await app_state._analyze_design_context_streaming(test_context, mock_notifier)

        mock_summarize.assert_called_once_with("<html>...</html>")
        
        # Verify the correct model and system prompt were used
        call_args = app_state.llm.messages.stream.call_args
        assert call_args.kwargs['model'] == "claude-sonnet-4-20250514"
        assert "You are Vision-Sonnet" in call_args.kwargs['system']
        
        assert result == '{"sectionPlan":["Hero"]}'
        assert mock_notifier.ai_token.call_count == 2


@pytest.mark.asyncio
async def test_generate_html_streaming():
    """Tests HTML generation, mocking the LLM."""
    app_state = AppState()
    mock_notifier = AsyncMock()
    
    async def mock_text_stream():
        yield "<html>"
        yield "</html>"
        
    app_state.llm.messages.stream = MagicMock()
    app_state.llm.messages.stream.return_value.text_stream = mock_text_stream()

    result = await app_state._generate_html_streaming('[]', {}, mock_notifier)

    # Verify the correct model and system prompt were used
    call_args = app_state.llm.messages.stream.call_args
    assert call_args.kwargs['model'] == "claude-opus-4-20250514"
    assert "You are Opus (Claude) acting as a precise front-end coder." in call_args.kwargs['system']
    
    assert result == "<html></html>"
    assert mock_notifier.ai_token.call_count == 2

# --- Test for the Main Orchestrator ---

@pytest.mark.asyncio
async def test_clone_website_orchestration():
    """Tests the high-level orchestration of the clone_website method."""
    app_state = AppState()
    mock_notifier = AsyncMock()
    # Mock the websocket state to prevent an error on close
    mock_notifier.ws.application_state = WebSocketState.CONNECTED
    test_url = HttpUrl("https://example.com")
    
    # Mock all external dependencies and helpers
    with patch('main.shutil.rmtree'), \
         patch('main.os.makedirs'), \
         patch('main.write_file') as mock_write_file, \
         patch.object(app_state, '_analyze_design_context_streaming', return_value='[{"componentName": "Test"}]') as mock_analyze, \
         patch.object(app_state, '_generate_html_streaming', return_value='<html></html>') as mock_generate, \
         patch.object(app_state.mcp_client, 'connect_to_server', new_callable=AsyncMock), \
         patch.object(app_state.mcp_client, 'cleanup', new_callable=AsyncMock) as mock_cleanup:
        
        # Mock the MCP session and its tool calls to return mock data
        mock_session = AsyncMock()
        mock_screenshot = MagicMock(content=["fake_screenshot_data"])
        mock_dom = MagicMock(content=[{"domTree": "...", "styles": {}}])
        mock_analysis = MagicMock(content=[{"layoutTree": []}])

        async def mock_call_tool_side_effect(tool_name, *args, **kwargs):
            if tool_name == "screenshot_url": return mock_screenshot
            if tool_name == "dom_inspector": return mock_dom
            if tool_name == "enhanced_page_analyzer": return mock_analysis
        
        mock_session.call_tool = AsyncMock(side_effect=mock_call_tool_side_effect)
        app_state.mcp_client.session = mock_session
        
        await app_state.clone_website(test_url, mock_notifier)
        
        # Assert that key orchestration steps were called
        mock_notifier.log.assert_any_call("Connecting to AI-Vision server …")
        mock_session.call_tool.assert_any_call("playwright_navigate", {"url": "https://example.com/"})
        mock_analyze.assert_called_once()
        mock_generate.assert_called_once()
        mock_write_file.assert_called_once_with(os.path.join(CLONED_PROJECT_DIR, "index.html"), "<html></html>")
        mock_cleanup.assert_called_once()
        mock_notifier.log.assert_any_call("✅ Cloning complete – open cloned_project/index.html!")

# --- API Endpoint Tests ---

def test_root_endpoint(client):
    """Tests the root endpoint, which should always return a 200 OK."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Backend is running"}

def test_get_files_tree_endpoint(client, temp_project_dir):
    """Tests the file tree endpoint. Should now find index.html."""
    (temp_project_dir / "index.html").touch()
    
    with patch('main.CLONED_PROJECT_DIR', str(temp_project_dir)):
        response = client.get("/files/tree")
        assert response.status_code == 200
        assert response.json()["tree"] == ["index.html"]

def test_get_file_content_endpoint(client, temp_project_dir):
    """Tests the file content endpoint."""
    file_path = temp_project_dir / "index.html"
    file_path.write_text("<h1>Hello</h1>")

    with patch('main.CLONED_PROJECT_DIR', str(temp_project_dir)):
        response = client.get("/files/content?path=index.html")
        assert response.status_code == 200
        assert response.json()["content"] == "<h1>Hello</h1>"

def test_get_file_content_not_found(client, temp_project_dir):
    """Tests that the file content endpoint returns 404 for a missing file."""
    with patch('main.CLONED_PROJECT_DIR', str(temp_project_dir)):
        response = client.get("/files/content?path=nonexistent.txt")
        assert response.status_code == 404

def test_websocket_clone_endpoint():
    """Tests that the WebSocket endpoint successfully creates and runs the clone task."""
    client = TestClient(app)
    # Mock the main clone_website method to prevent it from actually running
    with patch('main.AppState.clone_website', new_callable=AsyncMock) as mock_clone:
        with client.websocket_connect("/ws/clone") as websocket:
            websocket.send_json({"url": "https://example.com"})
            # The test will complete because the mocked clone_website returns immediately.
    
    # Assert that clone_website was called once with the correct URL.
    mock_clone.assert_called_once()
    assert str(mock_clone.call_args[0][0]) == "https://example.com/" 
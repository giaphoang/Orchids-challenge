import sys
import os
 
# Add the project root to the Python path to allow for absolute imports
# of modules like `mcp_client` from the `backend` directory.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root) 
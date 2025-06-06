from mcp.server.fastmcp import FastMCP, Context, Image
from contextlib import asynccontextmanager

import logging
import socket
from typing import Dict, Any, List
from dataclasses import dataclass
import json
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MayaMCPServer")

@asynccontextmanager
async def server_lifespan(server: FastMCP):
    try:
        logger.info("Server is starting...")
        try:
            maya = get_maya_connection()
        except Exception as e:
            logger.error(f"Failed to connect to Maya: {e}")
            raise e
        yield {}
    finally:
        global _maya_connection
        if _maya_connection:
            logger.info("Disconnecting from Maya on shutdown")
            _maya_connection.disconnect()
            _maya_connect = None
        logger.info("Maya Server is shutting down...")

# Create a FastMCP server
mcp = FastMCP(
    "mayaServer",
    lifespan=server_lifespan,
    )


@dataclass
class MayaConnection:
    host: str
    port: int
    sock: socket.socket = None

    def connect(self):
        if self.sock:
            return True
        
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Maya at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Maya: {e}")
            self.sock = None
            return False
        
    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Failed to disconnect from Maya: {e}")
            finally:
                self.sock = None
                logger.info("Disconnected from Maya")

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        # Use a consistent timeout value that matches the addon's timeout
        sock.settimeout(15.0)  # Match the addon's timeout

        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        # If we get an empty chunk, the connection might be closed
                        if not chunks:  # If we haven't received anything yet, this is an error
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        # If we get here, it parsed successfully
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    # If we hit a timeout during receiving, break the loop and try to use what we have
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise  # Re-raise to be handled by the caller
        except socket.timeout:
            logger.warning("Socket timeout during chunked receive")
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        # Try to use what we have
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                # Try to parse what we have
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                # If we can't parse it, it's incomplete
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Send a command to Maya and return the response
        """
        if not self.sock:
            raise Exception("Not connected to Maya")
        
        command = {
            "command": command_type,
            "params": params or {}
        }
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            self.sock.sendall(json.dumps(command).encode("utf-8"))
            logger.info(f"Command sent to Maya")

            self.sock.settimeout(15.0)

            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received response from Maya")

            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Maya error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Maya"))
            
            return response.get("result", {})
        except Exception as e:
            logger.error(f"Failed to send command to Maya: {e}")
            self.sock = None
            raise e

# Global connection for resources
_maya_connection = None            

def get_maya_connection():
    """
    Get or create a persistent Maya connection
    """
    global _maya_connection

    if _maya_connection is not None:
        try:
            # First check if the connection is still valid
            result = _maya_connection.send_command("about")
            return result.get("enabled", False)
        except Exception as e:
            logger.error(f"Maya connection is invalid: {e}")
            try:
                _maya_connection.disconnect()
            except:
                pass
            _maya_connection = None
    
    if _maya_connection is None:
        _maya_connection = MayaConnection(host="localhost", port=9876)
        if not _maya_connection.connect():
            logger.error("Failed to connect to Maya")
            _maya_connection = None
            raise Exception("Failed to connect to Maya")
    
    return _maya_connection
    # Create a new connection
    _maya_connection = MayaConnection()
    return _maya_connection


@mcp.tool()
def get_maya_version(ctx: Context) -> str:
    """Get the version of Maya"""
    maya = get_maya_connection()
    return maya.send_command("about")

@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """Get the current scene name"""
    maya = get_maya_connection()
    return maya.send_command("get_scene_info")

@mcp.tool()
def modify_object(
    ctx: Context,
    name: str,
    location: List[float] = None,
    rotation: List[float] = None,
    scale: List[float] = None,
    visible: bool = None
) -> str:
    """
    Modify an existing object in the Maya scene.
    
    Parameters:
    - name: Name of the object to modify
    - location: Optional [x, y, z] location coordinates
    - rotation: Optional [x, y, z] rotation in radians
    - scale: Optional [x, y, z] scale factors
    - visible: Optional boolean to set visibility
    """
    try:
        # Get the global connection
        maya = get_maya_connection()
        
        params = {"name": name}
        
        if location is not None:
            params["location"] = location
        if rotation is not None:
            params["rotation"] = rotation
        if scale is not None:
            params["scale"] = scale
        if visible is not None:
            params["visible"] = visible
            
        result = maya.send_command("modify_object", params)
        return f"Modified object: {result['name']}"
    except Exception as e:
        logger.error(f"Error modifying object: {str(e)}")
        return f"Error modifying object: {str(e)}"

@mcp.tool()
def create_object(
    ctx: Context,
    type: str = "CUBE",
    name: str = None,
    location: list[float] = None,
    rotation: list[float] = None,
    scale: list[float] = None,
    # Torus-specific parameters
    align: str = "WORLD",
    major_segments: int = 48,
    minor_segments: int = 12,
    mode: str = "MAJOR_MINOR",
    major_radius: float = 1.0,
    minor_radius: float = 0.25,
    abso_major_rad: float = 1.25,
    abso_minor_rad: float = 0.75,
    generate_uvs: bool = True
) -> str:
    """
    Create a new object in the Maya scene.
    
    Parameters:
    - type: Object type (CUBE, SPHERE, CYLINDER, PLANE, CONE, TORUS, EMPTY, CAMERA, LIGHT)
    - name: Optional name for the object
    - location: Optional [x, y, z] location coordinates
    - rotation: Optional [x, y, z] rotation in radians
    - scale: Optional [x, y, z] scale factors (not used for TORUS)
    
    Torus-specific parameters (only used when type == "TORUS"):
    - align: How to align the torus ('WORLD', 'VIEW', or 'CURSOR')
    - major_segments: Number of segments for the main ring
    - minor_segments: Number of segments for the cross-section
    - mode: Dimension mode ('MAJOR_MINOR' or 'EXT_INT')
    - major_radius: Radius from the origin to the center of the cross sections
    - minor_radius: Radius of the torus' cross section
    - abso_major_rad: Total exterior radius of the torus
    - abso_minor_rad: Total interior radius of the torus
    - generate_uvs: Whether to generate a default UV map
    
    Returns:
    A message indicating the created object name.
    """
    try:
        # Get the global connection
        maya = get_maya_connection()
        
        # Set default values for missing parameters
        loc = location or [0, 0, 0]
        rot = rotation or [0, 0, 0]
        sc = scale or [1, 1, 1]
        
        params = {
            "type": type,
            "location": loc,
            "rotation": rot,
            "scale": sc
        }
        
        if name:
            params["name"] = name

        params["scale"] = sc
        result = maya.send_command("create_object", params)
        return f"Created {type} object: {result['name']}"

    except Exception as e:
        logger.error(f"Error creating object: {str(e)}")
        return f"Error creating object: {str(e)}"
    
@mcp.prompt()
def asset_creation_strategy() -> str:
    """Defines the preferred strategy for creating assets in Maya"""
    return """When creating 3D content in Maya, always start by checking if integrations are available:

    0. Before anything, always check the scene from get_scene_info()

    1. Use basic tools:
       - create_object() for all shapes
    
    2. When including an object into scene, ALWAYS make sure that the name of the object is meanful.

    3. Always check the world_bounding_box for each item so that:
        - Ensure that all objects that should not be clipping are not clipping.
        - Items have right spatial relationship.
    
    4. After giving the tool location/scale/rotation information (via create_object() and modify_object()),
       double check the related object's location, scale, rotation, and world_bounding_box using get_object_info(),
       so that the object is in the desired location.

    Only fall back to basic creation tools when:
    - A simple primitive is explicitly requested
    - The task specifically requires a basic material/color
    """
    

# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers"""
    return a * b

# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def greeting(name: str) -> str:
    """Greet a person"""
    return f"Hello 123, {name}!"

def main():
    mcp.run()

# if __name__ == "__main__":
#     main()
    
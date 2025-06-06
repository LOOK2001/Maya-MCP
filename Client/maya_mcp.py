import socket
import os
import json
import time
import threading
import logging
import traceback

from maya import cmds as cmds
import maya.utils

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MayaMCPServer2")


class MayaMCPServer:
    def __init__(self, host='localhost', port=9876):
        logger.info("Initializing MayaMCPServer2")
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.server_thread = None

    def start(self):
        if self.running:
            print("Server is already running")
            return
        
        self.running = True

        try:
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)

            # Start server thread
            self.server_thread = threading.Thread(target=self._server_loop)
            self.server_thread.daemon = True
            self.server_thread.start()

            print(f"Server is running on {self.host}:{self.port}")
        except Exception as e:
            print(f"Error starting server: {e}")
            self.stop()

    def stop(self):
        self.running = False
        # Close socket
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                print(f"Error closing socket: {e}")
            self.socket = None
        
        # Wait for thread to finish
        if self.server_thread:
            try:
                if self.server_thread.is_alive():
                    self.server_thread.join(timeout=1.0)
            except Exception as e:
                print(f"Error joining server thread: {e}")
            self.server_thread = None
        
        print("Maya MCPServer stopped")

    def _server_loop(self):
        """
        Main server loop in a separate thread
        """
        while self.running:
            try:
                print("Waiting for connection...")
                # Accept new connection
                try:
                    client, address = self.socket.accept()
                    print(f"Connected to client: {address}")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except socket.timeout:
                    # Just check running condition
                    print("Timeout while waiting for connection")
                    continue
                except Exception as e:
                    print(f"Error accepting connection: {str(e)}")
                    time.sleep(0.5)
            except Exception as e:
                print(f"Error in server loop: {str(e)}")
                if not self.running:
                    break
                time.sleep(0.5)
        
        print("Server thread stopped")

    def _handle_client(self, client):
        print("Handling client...")
        client.settimeout(None)
        buffer = b''

        try:
            while self.running:
                # Receive data
                try:
                    data = client.recv(8192)
                    if not data:
                        print("Client disconnected")
                        break
                    
                    buffer += data
                    try:
                        # Try to parse command
                        command = json.loads(buffer.decode('utf-8'))
                        buffer = b''
                        
                        # Execute command in Blender's main thread
                        def execute_wrapper():
                            print("Executing command:", command)
                            try:
                                response = self.execute_command(command)
                                print("response:", response)
                                response_json = json.dumps(response)
                                print("response_json:", response_json)
                                try:
                                    client.sendall(response_json.encode('utf-8'))
                                except:
                                    print("Failed to send response - client disconnected")
                            except Exception as e:
                                print(f"Error executing command: {str(e)}")
                                traceback.print_exc()
                                try:
                                    error_response = {
                                        "status": "error",
                                        "message": str(e)
                                    }
                                    client.sendall(json.dumps(error_response).encode('utf-8'))
                                except:
                                    pass
                            return None
                        
                        # Schedule execution in main thread
                        maya.utils.executeDeferred(execute_wrapper)
                        print("Executing command...")
                    except json.JSONDecodeError:
                        # Incomplete data, wait for more
                        print("Incomplete data, waiting for more...")
                        pass
                except Exception as e:
                    print(f"Error receiving data: {str(e)}")
                    break
        except Exception as e:
            print(f"Error in client handler: {str(e)}")
        finally:
            try:
                client.close()
            except:
                pass
            print("Client handler stopped")
            
    def execute_command(self, command):
        """Execute a command in the main Maya thread"""
        try:
            cmd_type = command.get("command")
            params = command.get("params", {})
            print(f"Executing command: {cmd_type} with params: {params}")
            if cmd_type in ["create_object", "modify_object", "delete_object"]:
                # Run in the main thread to be safe with UI/scene changes
                return maya.utils.executeInMainThreadWithResult(self._execute_command_internal, command)
            else:
                return self._execute_command_internal(command)

        except Exception as e:
            print(f"Error executing command: {str(e)}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _execute_command_internal(self, command):
        cmd_type = command.get("command")
        params = command.get("params", {})
        
        # Base handlers that are always available
        handlers = {
            "get_scene_info": self.get_scene_info,
            "create_object": self.create_object
        }
        
        handler = handlers.get(cmd_type)
        if handler:
            result = handler(params)
            return {"status": "success", "result": result}
        
    def create_object(self, params=None):
        name = params.get("type", "pCube1")
        location = params.get("location", (0, 0, 0))
        rotaion = params.get("rotation", (0, 0, 0))
        scale = params.get("scale", (1, 1, 1))
        cube = cmds.polyCube(name=name)[0]
        cmds.xform(cube, ws=True, t=location)
        cmds.xform(cube, ws=True, ro=rotaion)
        cmds.xform(cube, ws=True, s=scale)
        
        result = {
                "name": name,
                "location": location
            }
        return result
    
    def modify_object(self, params=None):
        name = params.get("name")
        obj = cmds.ls(name)
        
        location = params.get("location")
        rotation = params.get("rotation")
        scale = params.get("scale")
        visibility = params.get("visibility", True)
        
        if location is not None:
            cmds.xform(obj, ws=True, t=location)
        if rotation is not None:
            cmds.xform(obj, ws=True, ro=rotation)
        if scale is not None:
            cmds.xform(obj, ws=True, s=scale)
        if visibility is not None:
            cmds.setAttr(f"{obj[0]}.visibility", visibility)
        result = {
            "name": name,
            "location": cmds.xform(obj, q=True, ws=True, t=True),
            "rotation": cmds.xform(obj, q=True, ws=True, ro=True),
            "scale": cmds.xform(obj, q=True, ws=True, s=True),
            "visibility": cmds.getAttr(f"{obj[0]}.visibility")
        }
        
        return result
        

    def get_scene_info(self, params=None):
        """Get information about the current Maya scene"""
        try:
            print("Getting scene info...")

            # Get the scene name from the current file
            scene_name = cmds.file(q=True, sn=True, shn=True) or "untitled"

            # Get all objects in the scene
            all_objects = cmds.ls(transforms=True)
            object_count = len(all_objects)

            scene_info = {
                "name": scene_name,
                "object_count": object_count,
                "objects": [],
                "materials_count": len(cmds.ls(materials=True)),
            }

            # Limit to first 10 objects
            for i, obj in enumerate(all_objects):
                if i >= 10:
                    break

                # Get object translation
                position = cmds.xform(obj, q=True, ws=True, t=True)

                obj_info = {
                    "name": obj,
                    "type": cmds.nodeType(obj),
                    "location": [round(position[0], 2),
                                round(position[1], 2),
                                round(position[2], 2)],
                }
                scene_info["objects"].append(obj_info)

            print(f"Scene info collected: {len(scene_info['objects'])} objects")
            return scene_info

        except Exception as e:
            print(f"Error in get_scene_info: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}


global maya_mcp_server
maya_mcp_server = None

            
def maya_mcp_start_server():
    global maya_mcp_server
    if not maya_mcp_server:
        maya_mcp_server = MayaMCPServer()
        maya_mcp_server.start()
    else:
        print("Server is already running")
        maya_mcp_stop_server()
        maya_mcp_server = MayaMCPServer()
        maya_mcp_server.start()

def maya_mcp_stop_server():
    global maya_mcp_server
    if maya_mcp_server:
        maya_mcp_server.stop()
        del maya_mcp_server
        maya_mcp_server = None
        


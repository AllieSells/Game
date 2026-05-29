"""
GLB to ASCII Converter for TCOD Rendering
==========================================

Converts 3D GLB models to ASCII art suitable for TCOD display.
Supports multiple projection methods and ASCII conversion strategies.
"""

import math
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
import json

# Try importing required libraries with fallbacks
try:
    import pygltflib
    HAS_PYGLTF = True
except ImportError:
    HAS_PYGLTF = False
    print("Warning: pygltflib not installed. Install with: pip install pygltflib")

try:
    import trimesh
    HAS_TRIMESH = True
except ImportError:
    HAS_TRIMESH = False
    print("Warning: trimesh not installed. Install with: pip install trimesh")


@dataclass
class AsciiArtConfig:
    """Configuration for ASCII art generation"""
    width: int = 80
    height: int = 40
    ascii_chars: str = "@%#*+=-:. "  # Dense to sparse
    use_shading: bool = True
    camera_distance: float = 5.0
    camera_elevation: float = 30.0  # degrees
    camera_azimuth: float = 45.0    # degrees
    # Lighting parameters
    light_elevation: float = 45.0   # Light elevation angle
    light_azimuth: float = 135.0    # Light azimuth angle
    light_intensity: float = 1.0    # Light strength
    ambient_light: float = 0.2      # Base lighting level
    use_shadows: bool = True        # Enable shadow casting


class GLBToASCII:
    """Main converter class for GLB to ASCII conversion"""
    
    def __init__(self, config: AsciiArtConfig):
        self.config = config
        self.vertices = None
        self.faces = None
        self.normals = None
    
    def load_glb_pygltf(self, glb_path: str) -> bool:
        """Load GLB file using pygltflib"""
        if not HAS_PYGLTF:
            raise ImportError("pygltflib is required for GLB loading")
        
        try:
            gltf = pygltflib.GLTF2().load(glb_path)
            
            # Extract mesh data
            vertices_list = []
            faces_list = []
            
            for mesh in gltf.meshes:
                for primitive in mesh.primitives:
                    # Get vertices
                    pos_accessor = gltf.accessors[primitive.attributes.POSITION]
                    pos_bufferview = gltf.bufferViews[pos_accessor.bufferView]
                    pos_buffer = gltf.buffers[pos_bufferview.buffer]
                    
                    # Convert binary data to numpy array
                    pos_data = gltf.get_data_from_buffer_uri(pos_buffer.uri)
                    vertices = np.frombuffer(
                        pos_data[pos_bufferview.byteOffset:pos_bufferview.byteOffset + pos_bufferview.byteLength],
                        dtype=np.float32
                    ).reshape(-1, 3)
                    
                    # Get indices if available
                    if primitive.indices is not None:
                        idx_accessor = gltf.accessors[primitive.indices]
                        idx_bufferview = gltf.bufferViews[idx_accessor.bufferView]
                        idx_buffer = gltf.buffers[idx_bufferview.buffer]
                        idx_data = gltf.get_data_from_buffer_uri(idx_buffer.uri)
                        faces = np.frombuffer(
                            idx_data[idx_bufferview.byteOffset:idx_bufferview.byteOffset + idx_bufferview.byteLength],
                            dtype=np.uint16 if idx_accessor.componentType == 5123 else np.uint32
                        ).reshape(-1, 3)
                    else:
                        # Generate faces from vertices
                        faces = np.arange(len(vertices)).reshape(-1, 3)
                    
                    vertices_list.append(vertices)
                    faces_list.append(faces)
            
            if vertices_list:
                self.vertices = np.vstack(vertices_list)
                self.faces = np.vstack(faces_list)
                self.compute_normals()
                return True
            
            return False
            
        except Exception as e:
            print(f"Error loading GLB with pygltf: {e}")
            return False
    
    def load_glb_trimesh(self, glb_path: str) -> bool:
        """Load GLB file using trimesh (alternative method)"""
        if not HAS_TRIMESH:
            raise ImportError("trimesh is required for GLB loading")
        
        try:
            mesh = trimesh.load(glb_path)
            
            if hasattr(mesh, 'vertices') and hasattr(mesh, 'faces'):
                self.vertices = mesh.vertices
                self.faces = mesh.faces
                if hasattr(mesh, 'vertex_normals'):
                    self.normals = mesh.vertex_normals
                else:
                    self.compute_normals()
                return True
            elif isinstance(mesh, dict):
                # Handle multi-mesh GLB files
                combined_vertices = []
                combined_faces = []
                vertex_offset = 0
                
                for name, submesh in mesh.items():
                    if hasattr(submesh, 'vertices') and hasattr(submesh, 'faces'):
                        combined_vertices.append(submesh.vertices)
                        faces_with_offset = submesh.faces + vertex_offset
                        combined_faces.append(faces_with_offset)
                        vertex_offset += len(submesh.vertices)
                
                if combined_vertices:
                    self.vertices = np.vstack(combined_vertices)
                    self.faces = np.vstack(combined_faces)
                    self.compute_normals()
                    return True
            
            return False
            
        except Exception as e:
            print(f"Error loading GLB with trimesh: {e}")
            return False
    
    def compute_normals(self):
        """Compute face normals for lighting calculations"""
        if self.vertices is None or self.faces is None:
            return
        
        # Compute face normals
        v1 = self.vertices[self.faces[:, 1]] - self.vertices[self.faces[:, 0]]
        v2 = self.vertices[self.faces[:, 2]] - self.vertices[self.faces[:, 0]]
        face_normals = np.cross(v1, v2)
        
        # Normalize
        norms = np.linalg.norm(face_normals, axis=1)
        face_normals = face_normals / norms.reshape(-1, 1)
        
        # Average face normals to get vertex normals
        vertex_normals = np.zeros_like(self.vertices)
        for i, face in enumerate(self.faces):
            for vertex_idx in face:
                vertex_normals[vertex_idx] += face_normals[i]
        
        # Normalize vertex normals
        norms = np.linalg.norm(vertex_normals, axis=1)
        vertex_normals = vertex_normals / norms.reshape(-1, 1)
        
        self.normals = vertex_normals
    
    def project_to_2d(self) -> Tuple[np.ndarray, np.ndarray]:
        """Project 3D vertices to 2D screen coordinates"""
        if self.vertices is None:
            raise ValueError("No vertices loaded")
        
        # Set up camera
        cam_rad_elev = math.radians(self.config.camera_elevation)
        cam_rad_azim = math.radians(self.config.camera_azimuth)
        
        # Camera position
        cam_x = self.config.camera_distance * math.cos(cam_rad_elev) * math.cos(cam_rad_azim)
        cam_y = self.config.camera_distance * math.cos(cam_rad_elev) * math.sin(cam_rad_azim)
        cam_z = self.config.camera_distance * math.sin(cam_rad_elev)
        
        camera_pos = np.array([cam_x, cam_y, cam_z])
        
        # Look at origin
        look_at = np.array([0, 0, 0])
        up = np.array([0, 0, 1])
        
        # Create view matrix
        forward = look_at - camera_pos
        forward = forward / np.linalg.norm(forward)
        
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        
        up = np.cross(right, forward)
        
        # Transform vertices to camera space
        vertices_cam = np.dot(self.vertices - camera_pos, np.array([right, up, -forward]).T)
        
        # Project to 2D (simple orthographic projection)
        x_2d = vertices_cam[:, 0]
        y_2d = vertices_cam[:, 1]
        z_depth = vertices_cam[:, 2]
        
        # Scale and center to fit in ASCII art bounds
        if len(x_2d) > 0:
            x_range = np.max(x_2d) - np.min(x_2d)
            y_range = np.max(y_2d) - np.min(y_2d)
            
            if x_range > 0:
                x_2d = (x_2d - np.min(x_2d)) / x_range * (self.config.width - 1)
            if y_range > 0:
                y_2d = (y_2d - np.min(y_2d)) / y_range * (self.config.height - 1)
        
        return np.column_stack([x_2d, y_2d]), z_depth
    
    def get_light_direction(self) -> np.ndarray:
        """Calculate light direction vector from elevation and azimuth angles"""
        light_rad_elev = math.radians(self.config.light_elevation)
        light_rad_azim = math.radians(self.config.light_azimuth)
        
        # Light direction vector (pointing towards the light source)
        light_x = math.cos(light_rad_elev) * math.cos(light_rad_azim)
        light_y = math.cos(light_rad_elev) * math.sin(light_rad_azim)
        light_z = math.sin(light_rad_elev)
        
        return np.array([light_x, light_y, light_z])
    
    def calculate_lighting_and_shadows(self, face_idx: int, normal: np.ndarray, world_pos: np.ndarray) -> float:
        """Calculate lighting intensity with shadows for a face"""
        light_dir = self.get_light_direction()
        
        # Basic diffuse lighting
        diffuse = max(0, np.dot(normal, light_dir)) * self.config.light_intensity
        
        # Add ambient light
        total_light = diffuse + self.config.ambient_light
        
        # Simple shadow calculation (distance-based attenuation)
        if self.config.use_shadows:
            # Calculate how much this face is facing away from camera (creates shadow effect)
            camera_rad_elev = math.radians(self.config.camera_elevation)
            camera_rad_azim = math.radians(self.config.camera_azimuth)
            
            cam_x = math.cos(camera_rad_elev) * math.cos(camera_rad_azim)
            cam_y = math.cos(camera_rad_elev) * math.sin(camera_rad_azim)
            cam_z = math.sin(camera_rad_elev)
            camera_dir = np.array([cam_x, cam_y, cam_z])
            
            # Shadow factor based on angle between light and camera
            light_camera_dot = np.dot(light_dir, camera_dir)
            shadow_factor = (light_camera_dot + 1.0) / 2.0  # Normalize to 0-1
            
            # Apply shadow
            total_light *= shadow_factor
        
        return min(1.0, total_light)
    
    def render_to_ascii(self) -> List[str]:
        """Convert projected vertices to ASCII art"""
        if self.vertices is None:
            raise ValueError("No mesh loaded")
        
        # Create 2D grid
        grid = [[' ' for _ in range(self.config.width)] for _ in range(self.config.height)]
        depth_buffer = [[float('inf') for _ in range(self.config.width)] for _ in range(self.config.height)]
        
        # Project vertices
        projected, depths = self.project_to_2d()
        
        # Render faces
        for face_idx, face in enumerate(self.faces):
            # Get triangle vertices
            v1, v2, v3 = projected[face]
            d1, d2, d3 = depths[face]
            
            # Simple triangle rasterization
            min_x = max(0, min(int(v1[0]), int(v2[0]), int(v3[0])))
            max_x = min(self.config.width - 1, max(int(v1[0]), int(v2[0]), int(v3[0])))
            min_y = max(0, min(int(v1[1]), int(v2[1]), int(v3[1])))
            max_y = min(self.config.height - 1, max(int(v1[1]), int(v2[1]), int(v3[1])))
            
            for y in range(min_y, max_y + 1):
                for x in range(min_x, max_x + 1):
                    # Check if point is inside triangle (simplified)
                    if self._point_in_triangle((x, y), v1, v2, v3):
                        # Calculate depth
                        depth = (d1 + d2 + d3) / 3  # Simplified depth
                        
                        # Z-buffer check
                        if depth < depth_buffer[y][x]:
                            depth_buffer[y][x] = depth
                            
                            # Choose ASCII character based on lighting
                            if self.config.use_shading and self.normals is not None:
                                # Calculate face center for world position
                                face_vertices = self.vertices[face]
                                world_pos = np.mean(face_vertices, axis=0)
                                
                                # Average normal for this face
                                normal = (self.normals[face[0]] + self.normals[face[1]] + self.normals[face[2]]) / 3
                                normal = normal / np.linalg.norm(normal)  # Normalize
                                
                                # Calculate lighting with shadows
                                intensity = self.calculate_lighting_and_shadows(face_idx, normal, world_pos)
                                char_idx = int(intensity * (len(self.config.ascii_chars) - 1))
                            else:
                                # Use depth fallback
                                if len(depths) > 0:
                                    normalized_depth = (depth - np.min(depths)) / (np.max(depths) - np.min(depths))
                                    char_idx = int(normalized_depth * (len(self.config.ascii_chars) - 1))
                                else:
                                    char_idx = 0
                            
                            char_idx = max(0, min(len(self.config.ascii_chars) - 1, char_idx))
                            grid[y][x] = self.config.ascii_chars[char_idx]
        
        # Convert grid to strings
        return [''.join(row) for row in grid]
    
    def _point_in_triangle(self, point, v1, v2, v3) -> bool:
        """Check if a point is inside a triangle (barycentric coordinates)"""
        x, y = point
        x1, y1 = v1
        x2, y2 = v2
        x3, y3 = v3
        
        denom = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if abs(denom) < 1e-10:
            return False
        
        a = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / denom
        b = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / denom
        c = 1 - a - b
        
        return a >= 0 and b >= 0 and c >= 0
    
    def save_to_tcod_format(self, ascii_lines: List[str], output_path: str):
        """Save ASCII art in a format suitable for TCOD loading"""
        tcod_data = {
            'width': self.config.width,
            'height': self.config.height,
            'ascii_art': ascii_lines,
            'metadata': {
                'camera_elevation': self.config.camera_elevation,
                'camera_azimuth': self.config.camera_azimuth,
                'camera_distance': self.config.camera_distance,
                'ascii_chars': self.config.ascii_chars
            }
        }
        
        with open(output_path, 'w') as f:
            json.dump(tcod_data, f, indent=2)
    
    def convert_glb_to_ascii(self, glb_path: str, output_path: Optional[str] = None) -> List[str]:
        """Main conversion function"""
        # Try loading with different methods
        success = False
        
        if HAS_TRIMESH:
            success = self.load_glb_trimesh(glb_path)
            if success:
                print("Loaded GLB using trimesh")
        
        if not success and HAS_PYGLTF:
            success = self.load_glb_pygltf(glb_path)
            if success:
                print("Loaded GLB using pygltflib")
        
        if not success:
            raise RuntimeError("Failed to load GLB file. Make sure trimesh or pygltflib is installed.")
        
        # Convert to ASCII
        ascii_lines = self.render_to_ascii()
        
        # Save if output path provided
        if output_path:
            self.save_to_tcod_format(ascii_lines, output_path)
            print(f"ASCII art saved to {output_path}")
        
        return ascii_lines


def load_ascii_for_tcod(json_path: str) -> Tuple[List[str], Dict[str, Any]]:
    """Load ASCII art from JSON file for use in TCOD"""
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    return data['ascii_art'], data['metadata']


def demo_conversion():
    """Demo function showing how to use the converter"""
    config = AsciiArtConfig(
        width=60,
        height=30,
        ascii_chars="@%#*+=-:. ",
        use_shading=True,
        camera_elevation=30.0,
        camera_azimuth=45.0
    )
    
    converter = GLBToASCII(config)
    
    # Example usage (replace with actual GLB path)
    glb_path = "example_model.glb"
    output_path = "model_ascii.json"
    
    try:
        ascii_lines = converter.convert_glb_to_ascii(glb_path, output_path)
        
        # Print ASCII art
        print("\n=== ASCII Art Preview ===")
        for line in ascii_lines:
            print(line)
        
        return ascii_lines
    except Exception as e:
        print(f"Error in demo: {e}")
        return []


if __name__ == "__main__":
    print("GLB to ASCII Converter for TCOD")
    print("================================")
    print()
    
    # Check required libraries
    print("Library Status:")
    print(f"- pygltflib: {'✓ Available' if HAS_PYGLTF else '✗ Not available'}")
    print(f"- trimesh: {'✓ Available' if HAS_TRIMESH else '✗ Not available'}")
    print()
    
    if not (HAS_PYGLTF or HAS_TRIMESH):
        print("Please install at least one of the following:")
        print("  pip install trimesh")
        print("  pip install pygltflib")
    else:
        print("Ready to convert GLB files to ASCII!")
        print("Use demo_conversion() or create your own AsciiArtConfig.")

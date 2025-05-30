import json
import os
import numpy as np
import pyvista as pv

# --- CONFIGURATION ---
# Determine the project root dynamically.
script_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(script_dir) # Go up from 'src' to project root

print(f"Detected PROJECT_ROOT: {PROJECT_ROOT}")

# Input data directory within the project
INPUT_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "testing-input-output")

# Output directory for VTK files (will be created if it doesn't exist)
OUTPUT_VTK_DIR = os.path.join(INPUT_DATA_DIR, "vtk_output")

INPUT_MESH_JSON_FILENAME = "fluid_mesh_data.json"
INPUT_VOLUME_JSON_FILENAME = "fluid_volume_data.json"
OUTPUT_PVD_FILENAME = "turbine_flow_animation.pvd" # ParaView time series file

INPUT_MESH_JSON_PATH = os.path.join(INPUT_DATA_DIR, INPUT_MESH_JSON_FILENAME)
INPUT_VOLUME_JSON_PATH = os.path.join(INPUT_DATA_DIR, INPUT_VOLUME_JSON_FILENAME)
OUTPUT_PVD_PATH = os.path.join(OUTPUT_VTK_DIR, OUTPUT_PVD_FILENAME)

# --- UTILITY FUNCTIONS ---

def load_json_data(filepath):
    """Loads JSON data from a given filepath."""
    if not os.path.exists(filepath):
        print(f"Error: JSON file not found at {filepath}")
        return None
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        print(f"Successfully loaded {filepath}")
        return data
    except json.JSONDecodeError as e:
        print(f"Error: Could not decode JSON from {filepath}: {e}")
        return None
    except Exception as e:
        print(f"Error: An unexpected error occurred loading {filepath}: {e}")
        return None

def create_pvd_file(vtu_files, timesteps, pvd_filepath):
    """Creates a .pvd file for a time series of VTK files."""
    with open(pvd_filepath, 'w') as f:
        f.write('<?xml version="1.0"?>\n')
        f.write('<VTKFile type="Collection" version="0.1" byte_order="LittleEndian" compressor="vtkZLibDataCompressor">\n')
        f.write('  <Collection>\n')
        for i, vtu_file in enumerate(vtu_files):
            # ParaView PVD files need relative paths to the VTU files
            relative_path = os.path.basename(vtu_file)
            f.write(f'    <DataSet timestep="{timesteps[i]}" file="{relative_path}"/>\n')
        f.write('  </Collection>\n')
        f.write('</VTKFile>\n')
    print(f"Created PVD file: {pvd_filepath}")

# --- MAIN CONVERSION FUNCTION ---
def convert_json_to_vtk(mesh_json_path, volume_json_path, output_vtk_dir, output_pvd_path):
    """
    Converts fluid mesh and volume data from JSON to VTK formats.
    Generates a .pvd file for time series animation in ParaView.
    """
    print(f"\n--- Starting JSON to VTK Conversion ---")
    print(f"Mesh JSON: {mesh_json_path}")
    print(f"Volume JSON: {volume_json_path}")
    print(f"Output VTK Directory: {output_vtk_dir}")
    print(f"Output PVD Path: {output_pvd_path}")

    # Ensure output directory exists
    os.makedirs(output_vtk_dir, exist_ok=True)
    print(f"Ensured output directory exists: {output_vtk_dir}")

    mesh_data = load_json_data(mesh_json_path)
    volume_data = load_json_data(volume_json_path)

    if not mesh_data and not volume_data:
        print("Error: No valid mesh or volume data loaded. Aborting conversion.")
        return

    vtu_files = []
    timesteps = []

    # --- Process Fluid Mesh Data ---
    print("Processing fluid mesh data...")
    if mesh_data and 'time_steps' in mesh_data and mesh_data['time_steps']:
        static_faces = None
        if 'static_faces' in mesh_data:
            static_faces = mesh_data['static_faces'] # Keep as list of lists for now
            print(f"Loaded {len(static_faces)} static faces for mesh.")
        else:
            print("Warning: 'static_faces' key not found in fluid_mesh_data.json. Mesh object might not be correctly formed.")

        if static_faces is not None and 'vertices' in mesh_data['time_steps'][0]:
            first_frame_vertices = np.array(mesh_data['time_steps'][0]['vertices'])

            # Correctly format faces for pyvista.PolyData (for quads)
            # pyvista.PolyData expects a flattened array: [n_verts_0, p0_idx, p1_idx, p2_idx, p3_idx, n_verts_1, ...]
            faces_formatted_list = []
            for face in static_faces:
                # Assuming all faces are quads (4 vertices) as generated by generate_fluid_mesh_data_json.py
                if len(face) == 4:
                    faces_formatted_list.append(4) # Prefix with the number of vertices in the quad
                    faces_formatted_list.extend(face) # Add the 4 vertex indices
                else:
                    print(f"Warning: Detected a non-quad face with {len(face)} vertices. Skipping this face.")
                    # Handle other face types if necessary, e.g., if you have triangles, add '3' and the indices.
                    # For now, assuming consistent quads.
            
            if not faces_formatted_list:
                print("Error: No valid faces could be processed for static mesh after formatting.")
                return # Or handle as a non-fatal warning if mesh is optional

            faces_formatted = np.array(faces_formatted_list, dtype=int)
            print(f"Successfully formatted {len(static_faces)} quad faces for pyvista.")
            print(f"Length of faces_formatted array: {len(faces_formatted)}")
            
            static_mesh = pv.PolyData(first_frame_vertices, faces_formatted)
            
            # Save the static mesh once
            static_mesh_path = os.path.join(output_vtk_dir, "turbine_geometry.vtp") # .vtp for PolyData
            static_mesh.save(static_mesh_path)
            print(f"Saved static turbine mesh to: {static_mesh_path}")
        else:
            print("Skipping static mesh creation due to missing data.")

    else:
        print("No mesh data found or 'time_steps' is empty, skipping static mesh creation.")

    # --- Process Fluid Volume Data (and create .pvd for animation) ---
    print("Processing fluid volume data for animation...")
    if volume_data and 'time_steps' in volume_data and volume_data['time_steps']:
        if 'grid_info' not in volume_data:
            print("Error: 'grid_info' missing in volume data. Cannot create volume objects.")
            return

        grid_info = volume_data['grid_info']
        required_grid_keys = ['dimensions', 'voxel_size', 'origin']
        if not all(key in grid_info for key in required_grid_keys):
            print(f"Error: Missing required grid_info keys ({required_grid_keys}) in volume data. Cannot create volume objects.")
            return

        # Note: Your mesh script uses Z, Y, X order for dimensions from grid_info
        # pyvista.ImageData expects dimensions (nx, ny, nz) as (X, Y, Z)
        num_z, num_y, num_x = grid_info['dimensions'] 
        dx, dy, dz = grid_info['voxel_size']
        origin_x, origin_y, origin_z = grid_info['origin']

        # Create a base UniformGrid (ImageData) for the volume
        # pyvista.ImageData is an alias for UniformGrid and is commonly used for rectilinear, uniformly spaced data.
        # Changed 'dims' to 'dimensions' for broader compatibility with pyvista versions.
        base_grid = pv.ImageData(
            dimensions=(num_x, num_y, num_z), # Corrected keyword argument to 'dimensions'
            spacing=(dx, dy, dz),
            origin=(origin_x, origin_y, origin_z)
        )
        print(f"Created base UniformGrid with dimensions {base_grid.dimensions}, spacing {base_grid.spacing}, origin {base_grid.origin}")


        for frame_idx, frame_data in enumerate(volume_data['time_steps']):
            current_timestep = frame_data.get('time', frame_idx) # Use 'time' if available, else index
            
            # Clone the base grid for each timestep to attach data
            current_grid = base_grid.copy()

            # Add Point Data
            # For UniformGrid (ImageData), pyvista expects data flattened in C-order (row-major),
            # which usually corresponds to (Z, Y, X) order if you flatten a 3D array directly.
            # Your generate script provides dimensions as [Z, Y, X] and data is flattened accordingly.
            expected_data_size = num_x * num_y * num_z

            if 'density_data' in frame_data:
                density_data = np.array(frame_data['density_data'], dtype=np.float32)
                if density_data.shape == (expected_data_size,):
                    current_grid['Density'] = density_data
                else:
                    print(f"Warning: Density data shape mismatch for frame {frame_idx}. Expected {expected_data_size}, got {density_data.shape}. Skipping Density.")

            if 'temperature_data' in frame_data:
                temperature_data = np.array(frame_data['temperature_data'], dtype=np.float32)
                if temperature_data.shape == (expected_data_size,):
                    current_grid['Temperature'] = temperature_data
                else:
                    print(f"Warning: Temperature data shape mismatch for frame {frame_idx}. Skipping Temperature.")
            
            if 'velocity_data' in frame_data:
                velocity_data = np.array(frame_data['velocity_data'], dtype=np.float32)
                # Ensure velocity data is Nx3 where N is total points
                if velocity_data.shape == (expected_data_size, 3):
                    current_grid['Velocity'] = velocity_data
                else:
                    print(f"Warning: Velocity data shape mismatch for frame {frame_idx}. Expected ({expected_data_size}, 3), got {velocity_data.shape}. Skipping Velocity.")

            # Save as .vti (for image data/uniform grids)
            vtk_filepath = os.path.join(output_vtk_dir, f'fluid_data_t{frame_idx:04d}.vti')
            current_grid.save(vtk_filepath)
            vtu_files.append(vtk_filepath)
            timesteps.append(current_timestep)
            print(f"Saved VTK data for frame {frame_idx} (time: {current_timestep}) to {vtk_filepath}")

    else:
        print("No volume data found or 'time_steps' is empty, skipping volume animation creation.")

    # Create the .pvd file to link all VTK files for ParaView
    if vtu_files:
        create_pvd_file(vtu_files, timesteps, output_pvd_path)
    else:
        print("No VTK files generated, skipping .pvd creation.")

    print("--- JSON to VTK Conversion Complete! ---")

# --- Main execution block ---
if __name__ == "__main__":
    convert_json_to_vtk(INPUT_MESH_JSON_PATH, INPUT_VOLUME_JSON_PATH, OUTPUT_VTK_DIR, OUTPUT_PVD_PATH)

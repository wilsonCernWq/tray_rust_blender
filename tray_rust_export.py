import bpy
import math
import mathutils
import json
import re
import os
from bpy_extras.io_utils import ExportHelper

bl_info = {
    "name": "tray_rust export",
    "author": "Will Usher",
    "blender": (2, 7, 6),
    "version": (0, 0, 1),
    "location": "File > Import-Export",
    "description": "Export the scene to a tray_rust scene",
    "category": "Import-Export"
}

TRANSFORM_MAT = mathutils.Matrix([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]])

# Convert a matrix from Blender's coordinate system to tray_rust's
def convert_blender_matrix(mat):
    return TRANSFORM_MAT.inverted() * mat * TRANSFORM_MAT * mathutils.Matrix.Rotation(math.radians(90), 4, "X")

# Convert a matrix from Blender's OBJ export coordinate system to tray_rust's
def convert_obj_matrix(mat):
    return TRANSFORM_MAT.inverted() * mat * mathutils.Matrix.Scale(-1, 4, [1, 0, 0]) * TRANSFORM_MAT

# Sample and export the keyframes of the object's animation to a dict for saving to the scene file
# mat_convert is a function that will convert the object's matrix to tray_rust's coordinate
# system. Returns the dict of control points, knots and degree required to specify the curve
# for the animation in the scene file
def export_animation(obj, mat_convert, scene):
    frame_time = 1.0 / scene.render.fps
    knots = []
    control_points = []
    anim_data = obj.animation_data
    start = int(anim_data.action.frame_range[0])
    end = int(math.ceil(anim_data.action.frame_range[1]))
    knots.append((start - 1) * frame_time)
    for f in range(start - 1, end):
        scene.frame_set(f + 1)
        mat = mat_convert(obj.matrix_world)
        knots.append(f * frame_time)
        control_points.append({
            "transform": [
                {
                    "type": "matrix",
                    "matrix": [mat[0][0:], mat[1][0:], mat[2][0:], mat[3][0:]]
                }
            ]})
    knots.append((end - 1) * frame_time)
    scene.frame_set(1)
    return {
        "control_points": control_points,
        "knots": knots,
        "degree": 1
    }

def export_tray_rust(operator, context, filepath="", check_existing=False):
    scene = context.scene
    film = {
        "width": scene.render.resolution_x,
        "height": scene.render.resolution_y,
        "samples": scene.cycles.samples,
        "frames": scene.frame_end - scene.frame_start + 1,
        "start_frame": scene.frame_start - 1,
        "end_frame": scene.frame_end - 1,
        "scene_time": (scene.frame_end - scene.frame_start + 1) / scene.render.fps,
        "filter" : {
            "type": "mitchell_netravali",
            "width": 2.0,
            "height": 2.0,
                "b": 0.333333333333333333,
                "c": 0.333333333333333333
        },
    }
    integrator = {
        "type": "normals_debug",
        "min_depth": 4,
        "max_depth": 8
    }
    materials = [
        {
            "type": "matte",
            "name": "white_wall",
            "diffuse": [0.740063, 0.742313, 0.733934],
            "roughness": 1.0
        }
    ]

    camera = scene.objects["Camera"]
    camera.select = False
    camera_json = {
        "fov": math.degrees(bpy.data.cameras[camera.name].angle_y),
    }

    if camera.animation_data and camera.animation_data.action:
        camera_json["keyframes"] = export_animation(camera, convert_blender_matrix, scene)
    else:
        cam_mat = convert_blender_matrix(camera.matrix_world)
        camera_json["transform"] = [
                {
                    "type": "matrix",
                    "matrix": [cam_mat[0][0:], cam_mat[1][0:], cam_mat[2][0:], cam_mat[3][0:]]
                }
            ]

    print("camera = {}".format(json.dumps(camera_json, indent=4)))

    match_instance = re.compile("(\w+)\.\d+")
    mesh_transforms = {}
    objects = []
    _, obj_file_name = os.path.split(filepath)
    obj_file_name, _ = os.path.splitext(obj_file_name)
    obj_file_name += ".obj"

    # Add the scene objects
    for name, obj in scene.objects.items():
        # Append all the meshes in the scene
        if obj.type == "MESH":
            print(obj.data.name)
            # Check if this is an instance or a "real" object
            instance = match_instance.match(name)
            geometry = {}
            # If it's an instance we expect the real object to be exported without
            # the .### in the name, so use that model in the OBJ file. To prevent exporting
            # this object we also don't select it
            if instance:
                obj.select = False
                geometry = {
                    "type": "mesh",
                    "file": obj_file_name,
                    "model": obj.data.name,
                    }
            else:
                # Fix up any mis-named objects since the exported name in the OBJ will
                # be name_obj.data.name in that case, which is more annoying to track
                # down for instancing
                if obj.data.name != obj.name:
                    obj.name = obj.data.name
                obj.select = True
                geometry = {
                    "type": "mesh",
                    "file": obj_file_name,
                    "model": obj.data.name,
                }
            objects.append({
                "name": name,
                "type": "receiver",
                "material": "white_wall",
                "geometry": geometry,
            })

            mesh_transforms[obj.name] = obj.matrix_world.copy()
            if obj.animation_data and obj.animation_data.action:
                objects[-1]["keyframes"] = export_animation(obj, convert_obj_matrix, scene)
                print("# of fcurves = {}".format(len(obj.animation_data.action.fcurves)))
                # Mute keyframe animation so it doesn't block (location|rotation|scale)_clear
                for curve in obj.animation_data.action.fcurves:
                    curve.mute = True
            else:
                obj_mat = convert_obj_matrix(obj.matrix_world)
                objects[-1]["transform"] = [
                        {
                            "type": "matrix",
                            "matrix": [obj_mat[0][0:], obj_mat[1][0:], obj_mat[2][0:], obj_mat[3][0:]]
                        }
                    ]

        # Convert meta balls to analytic spheres
        if obj.type == "META":
            obj.select = False
            obj_mat = convert_obj_matrix(obj.matrix_world)
            objects.append({
                "name": name,
                "type": "receiver",
                "material": "white_wall",
                "geometry": {
                    "type": "sphere",
                    "radius": 1
                },
                "transform": [
                    {
                        "type": "matrix",
                        "matrix": [obj_mat[0][0:], obj_mat[1][0:], obj_mat[2][0:], obj_mat[3][0:]]
                    }
                ]
            })
        # Export lights
        if obj.type == "LAMP":
            obj.select = False
            lamp = bpy.data.lamps[name]
            if lamp.type == "POINT":
                obj_mat = convert_blender_matrix(obj.matrix_world)
                objects.append({
                    "name": name,
                    "type": "emitter",
                    "emitter": "point",
                    "emission": [0.780131, 0.780409, 0.775833, 100],
                    "transform": [
                        {
                            "type": "matrix",
                            "matrix": [obj_mat[0][0:], obj_mat[1][0:], obj_mat[2][0:], obj_mat[3][0:]]
                        }
                    ]
                })
            elif lamp.type == "AREA":
                obj_mat = convert_blender_matrix(obj.matrix_world)
                lamp_geometry = {}
                # TODO: Sphere and disk lights
                if lamp.shape == "SQUARE":
                    lamp_geometry = {
                        "type": "rectangle",
                        "width": lamp.size,
                        "height": lamp.size
                    }
                elif lamp.shape == "RECTANGLE":
                    lamp_geometry = {
                        "type": "rectangle",
                        "width": lamp.size,
                        "height": lamp.size_y
                    }
                # TODO: Configuring light properties
                objects.append({
                    "name": name,
                    "type": "emitter",
                    "material": "white_wall",
                    "emitter": "area",
                    "emission": [0.780131, 0.780409, 0.775833, 50],
                    "geometry": lamp_geometry,
                    "transform": [
                        {
                            "type": "matrix",
                            "matrix": [obj_mat[0][0:], obj_mat[1][0:], obj_mat[2][0:], obj_mat[3][0:]]
                        }
                    ]
                })

    # Reset all transformations
    bpy.ops.object.location_clear()
    bpy.ops.object.rotation_clear()
    bpy.ops.object.scale_clear()

    # Save out the OBJ containing all our meshes
    obj_path, _ = os.path.splitext(filepath)
    bpy.ops.export_scene.obj("EXEC_DEFAULT", False, filepath=obj_path + ".obj",
        axis_forward="Z", axis_up="Y", use_materials=False, use_uvs=True, use_normals=True,
        use_triangles=True, use_selection=True)

    # Restore all transformations
    for name, obj in scene.objects.items():
        if obj.type == "MESH":
            obj.matrix_world = mesh_transforms[obj.name]
            obj.select = False
            if obj.animation_data and obj.animation_data.action:
                # Unmute keyframe animation to restore it
                for curve in obj.animation_data.action.fcurves:
                    curve.mute = False

    # Save out the JSON scene file
    scene = {
        "film": film,
        "camera": camera_json,
        "integrator": integrator,
        "materials": materials,
        "objects": objects
    }
    with open(filepath, "w") as f:
        json.dump(scene, f, indent=4)

    return { "FINISHED" }

class ExportTrayRust(bpy.types.Operator, ExportHelper):
    """Save a tray_rust scene, exports a JSON scene file + OBJ mesh file"""

    bl_idname = "export_tray_rust.json"
    bl_label = "Export tray_rust"
    bl_options = { "PRESET" }
    filename_ext = ".json"

    def execute(self, context):
        keywords = self.as_keywords()
        return export_tray_rust(self, context, **keywords)

def menu_func(self, context):
    self.layout.operator(ExportTrayRust.bl_idname, text="tray_rust scene (.json + .obj)")

def register():
    bpy.utils.register_module(__name__)
    #bpy.types.INFO_MT_file_export.append(menu_func)

def unregister():
    bpy.utils.unregister_module(__name__)
    bpy.types.INFO_MT_file_export.remove(menu_func)

if __name__ == "__main__":
    register()


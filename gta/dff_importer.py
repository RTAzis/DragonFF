# GTA DragonFF - Blender scripts to edit basic GTA formats
# Copyright (C) 2019  Parik

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
import bpy
import bmesh
import math
import mathutils

from . import dff
from .importer_common import (
        link_object, create_collection,
        material_helper, set_object_mode)
from .col_importer import import_col_mem

#######################################################
class dff_importer:

    image_ext = "png"
    use_bone_connect = False
    current_collection = None

    __slots__ = [
        'dff',
        'meshes',
        'objects',
        'file_name',
        'skin_data',
        'bones'
    ]

    #######################################################
    def multiply_matrix(a, b):
        # For compatibility with 2.79
        if bpy.app.version < (2, 80, 0):
            return a * b
        return a @ b
    
    #######################################################
    def _init():
        self = dff_importer

        # Variables
        self.dff = None
        self.meshes = {}
        self.objects = []
        self.file_name = ""
        self.skin_data = {}
        self.bones = {}

    #######################################################
    def import_atomics():
        self = dff_importer

        # Import atomics (meshes)
        for atomic in self.dff.atomic_list:

            frame = self.dff.frame_list[atomic.frame]
            geom = self.dff.geometry_list[atomic.geometry]
            
            mesh = bpy.data.meshes.new(frame.name)
            bm   = bmesh.new()

            uv_layers = []
            
            # Vertices
            for v in geom.vertices:
                bm.verts.new(v)

            bm.verts.ensure_lookup_table()
            bm.verts.index_update()

            # Will use this later when creating frames to construct an armature
            if 'skin' in geom.extensions:
                self.skin_data[atomic.frame] = geom.extensions['skin']
            
            # Add UV Layers
            for layer in geom.uv_layers:
                uv_layers.append(bm.loops.layers.uv.new())
                
            # Add Vertex Colors
            if geom.flags & dff.rpGEOMETRYPRELIT:
                vertex_color = bm.loops.layers.color.new()

            extra_vertex_color = None
            if 'extra_vert_color' in geom.extensions:
                extra_vertex_color = bm.loops.layers.color.new()
            
            for f in geom.triangles:
                try:
                    face = bm.faces.new(
                        [
                            bm.verts[f.a],
                            bm.verts[f.b],
                            bm.verts[f.c]
                        ])

                    face.material_index = f.material
                    
                    # Setting UV coordinates
                    for loop in face.loops:
                        for i, layer in enumerate(geom.uv_layers):

                            bl_layer = uv_layers[i]
                            
                            uv_coords = layer[loop.vert.index]

                            loop[bl_layer].uv = (
                                uv_coords.u,
                                1 - uv_coords.v # Y coords are flipped in Blender
                            )
                        # Vertex colors
                        if geom.flags & dff.rpGEOMETRYPRELIT:
                            loop[vertex_color] = [
                                c / 255.0 for c in
                                geom.prelit_colors[loop.vert.index]
                            ]
                        # Night/Extra Vertex Colors
                        if extra_vertex_color:
                            extension = geom.extensions['extra_vert_color']
                            loop[extra_vertex_color] = [
                                c / 255.0 for c in
                                extension.colors[loop.vert.index]
                            ]
                            
                    face.smooth = True
                except BaseException as e:
                    print(e)

            bm.to_mesh(mesh)
            bm.free()

            # Set loop normals
            if geom.has_normals:
                normals = []
                for loop in mesh.loops:
                    normals.append(geom.normals[loop.vertex_index])

                mesh.normals_split_custom_set(normals)
                mesh.use_auto_smooth = True

            mesh.update()

            # Import materials and add the mesh to the meshes list
            self.import_materials(geom, frame, mesh)
            self.meshes[atomic.frame] = mesh

               
    #######################################################
    def set_empty_draw_properties(empty):
        if (2, 80, 0) > bpy.app.version:
            empty.empty_draw_type = 'CUBE'
            empty.empty_draw_size = 0.05
        else:
            empty.empty_display_type = 'CUBE'
            empty.empty_display_size = 0.05
        pass
    
    ##################################################################
    # TODO: MatFX: Dual Textures
    def import_materials(geometry, frame, mesh):

        self = dff_importer        
        from bpy_extras.image_utils import load_image

        # Refactored
        for index, material in enumerate(geometry.materials):

            # Generate a nice name with index and frame
            name = "%s.%d" % (frame.name, index)

            mat = bpy.data.materials.new(name)
            helper = material_helper(mat)
            
            helper.set_base_color(material.color)

            # Loading Texture
            if material.is_textured == 1:
                texture = material.textures[0]
                path    = os.path.dirname(self.file_name)

                # name.None shouldn't exist, lol
                image = load_image("%s.%s" % (texture.name, self.image_ext),
                                   path,
                                   recursive=False,
                                   place_holder=True,
                                   check_existing=True
                )
                helper.set_texture(image, texture.name)
                
            # Normal Map
            if 'bump_map' in material.plugins:
                mat.dff.export_bump_map = True
                
                for bump_fx in material.plugins['bump_map']:

                    texture = None
                    if bump_fx.height_map is not None:
                        texture = bump_fx.height_map
                        if bump_fx.bump_map is not None:
                            mat.dff.bump_map_tex = bump_fx.bump_map.name

                    elif bump_fx.bump_map is not None:
                        texture = bump_fx.bump_map

                    if texture:
                        path = os.path.dirname(self.file_name)

                        # see name.None note above
                        image = load_image("%s.%s" % (texture.name,
                                                      self.image_ext),
                                           path,
                                           recursive=False,
                                           place_holder=True,
                                           check_existing=True
                        )

                        helper.set_normal_map(image,
                                              texture.name,
                                              bump_fx.intensity
                        )

            # Surface Properties
            if material.surface_properties is not None:
                props = material.surface_properties

            elif geometry.surface_properties is not None:
                props = geometry.surface_properties

            if props is not None:
                helper.set_surface_properties(props)

            # Environment Map
            if 'env_map' in material.plugins:
                plugin = material.plugins['env_map'][0]
                helper.set_environment_map(plugin)

            # Specular Material
            if 'spec' in material.plugins:
                plugin = material.plugins['spec'][0]
                helper.set_specular_material(plugin)

            # Reflection Material
            if 'refl' in material.plugins:
                plugin = material.plugins['refl'][0]
                helper.set_reflection_material(plugin)

            # UV Animation
            # TODO: Figure out ways to add multiple uv animations
            if 'uv_anim' in material.plugins:
                plugin = material.plugins['uv_anim'][0]

                for uv_anim in self.dff.uvanim_dict:
                    if uv_anim.name == plugin:
                        helper.set_uv_animation(uv_anim)
                        break
                
            # Add imported material to the object
            mesh.materials.append(helper.material)
                

    #######################################################
    def construct_bone_dict():
        self = dff_importer
        
        for index, frame in enumerate(self.dff.frame_list):
            if frame.bone_data:
                bone_id = frame.bone_data.header.id
                if bone_id != 4294967295: #-1
                    self.bones[bone_id] = {'frame': frame,
                                              'index': index}
                        
    #######################################################
    def align_roll( vec, vecz, tarz ):

        sine_roll = vec.normalized().dot(vecz.normalized().cross(tarz.normalized()))

        if 1 < abs(sine_roll):
            sine_roll /= abs(sine_roll)
            
        if 0 < vecz.dot( tarz ):
            return math.asin( sine_roll )
        
        elif 0 < sine_roll:
            return -math.asin( sine_roll ) + math.pi
        
        else:
            return -math.asin( sine_roll ) - math.pi
        
    #######################################################
    def construct_armature(frame, frame_index):

        self = dff_importer
        
        armature = bpy.data.armatures.new(frame.name)
        obj = bpy.data.objects.new(frame.name, armature)
        link_object(obj, dff_importer.current_collection)

        skinned_obj_index = frame.parent if frame.parent in self.skin_data \
            else next(iter(self.skin_data))
        
        skinned_obj_data = self.skin_data[skinned_obj_index]
        skinned_obj = self.objects[skinned_obj_index]
        
        # armature edit bones are only available in edit mode :/
        set_object_mode(obj, "EDIT")
        edit_bones = obj.data.edit_bones
        
        bone_list = {}
                        
        for index, bone in enumerate(frame.bone_data.bones):
            
            bone_frame = self.bones[bone.id]['frame']

            # Set vertex group name of the skinned object
            skinned_obj.vertex_groups[index].name = bone_frame.name
            
            e_bone = edit_bones.new(bone_frame.name)
            e_bone.tail = (0,0.05,0) # Stop bone from getting delete

            e_bone['bone_id'] = bone.id
            e_bone['type'] = bone.type

            matrix = skinned_obj_data.bone_matrices[bone.index]
            matrix = mathutils.Matrix(matrix).transposed()
            matrix = matrix.inverted()

            e_bone.transform(matrix, False, False)
            e_bone.roll = self.align_roll(e_bone.vector,
                                          e_bone.z_axis,
                                          self.multiply_matrix(
                                              matrix.to_3x3(),
                                              mathutils.Vector((0,0,1))
                                          )
            )
            
            # Setting parent. See "set parent" note below
            if bone_frame.parent != -1:
                try:
                    e_bone.parent = bone_list[bone_frame.parent][0]
                    if self.use_bone_connect:

                        if not bone_list[bone_frame.parent][1]:

                            e_bone.parent.tail = e_bone.head
                            e_bone.use_connect = self.use_bone_connect
                            
                            bone_list[bone_frame.parent][1] = True
                        
                except BaseException:
                    print("DragonFF: Bone parent not found")
            
            bone_list[self.bones[bone.id]['index']] = [e_bone, False]
            
                    
        set_object_mode(obj, "OBJECT")

        # Add Armature modifier to skinned object
        modifier        = skinned_obj.modifiers.new("Armature", 'ARMATURE')
        modifier.object = obj
        
        return (armature, obj)

    #######################################################
    def set_vertex_groups(obj, skin_data):

        # Allocate vertex groups
        for i in range(skin_data.num_bones):
            obj.vertex_groups.new()

        # vertex_bone_indices stores what 4 bones influence this vertex
        for i in range(len(skin_data.vertex_bone_indices)):

            for j in range(len(skin_data.vertex_bone_indices[i])):

                bone = skin_data.vertex_bone_indices[i][j]
                weight = skin_data.vertex_bone_weights[i][j]

                obj.vertex_groups[bone].add([i], weight, 'ADD')
    
    #######################################################
    def import_frames():
        self = dff_importer

        # Initialise bone indices for use in armature construction
        self.construct_bone_dict()
        
        for index, frame in enumerate(self.dff.frame_list):
            
            # Check if the mesh for the frame has been loaded
            mesh = None
            if index in self.meshes:
                mesh = self.meshes[index]

            obj = None

            # Load rotation matrix
            matrix = mathutils.Matrix(
                (
                    frame.rotation_matrix.right,
                    frame.rotation_matrix.up,
                    frame.rotation_matrix.at
                )
            )
            
            matrix.transpose()

            if frame.bone_data is not None:
                
                # Construct an armature
                if frame.bone_data.header.bone_count > 0:
                    mesh, obj = self.construct_armature(frame, index)
                    
                # Skip bones
                elif frame.bone_data.header.id in self.bones and mesh is None:
                    continue
                    
            
            # Create and link the object to the scene
            if obj is None:
                obj = bpy.data.objects.new(frame.name, mesh)
                link_object(obj, dff_importer.current_collection)

                obj.rotation_mode       = 'QUATERNION'
                obj.rotation_quaternion = matrix.to_quaternion()
                obj.location            = frame.position

                # Set empty display properties to something decent
                if mesh is None:
                    self.set_empty_draw_properties(obj)

                # Set vertex groups
                if index in self.skin_data:
                    self.set_vertex_groups(obj, self.skin_data[index])
            
            # set parent
            # Note: I have not considered if frames could have parents
            # that have not yet been defined. If I come across such
            # a model, the code will be modified to support that
          
            if  frame.parent != -1:
                obj.parent = self.objects[frame.parent]
                
            self.objects.append(obj)

            # Set a collision model used for export
            obj["gta_coll"] = self.dff.collisions
            
    #######################################################
    def import_dff(file_name):
        self = dff_importer
        self._init()

        # Load the DFF
        self.dff = dff.dff()
        self.dff.load_file(file_name)
        self.file_name = file_name

        # Create a new group/collection
        self.current_collection = create_collection(
            os.path.basename(file_name)
        )
        
        self.import_atomics()
        self.import_frames()

        # Add collisions
        for collision in self.dff.collisions:
            col = import_col_mem(collision, os.path.basename(file_name), False)
            
            if (2, 80, 0) <= bpy.app.version:
                for collection in col:
                    self.current_collection.children.link(collection)

#######################################################
def import_dff(options):

    # Shadow function
    dff_importer.image_ext        = options['image_ext']
    dff_importer.use_bone_connect = options['connect_bones']
    
    dff_importer.import_dff(options['file_name'])

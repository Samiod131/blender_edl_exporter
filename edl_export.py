"""
Export EDL - CMX 3600 Edit Decision List exporter for Blender VSE
Exports video editing timelines to industry-standard EDL format
"""

import bpy
import os
from bpy.props import IntProperty, StringProperty, BoolProperty
from bpy_extras.io_utils import ExportHelper
from bpy.types import Operator, Panel

bl_info = {
    "name": "Export EDL",
    "author": "Tintwotin, Campbell Barton, William R. Zwicky, batFINGER, szaszak",
    "version": (0, 6, 0),
    "blender": (4, 0, 0),
    "location": "Sequencer > Sidebar > EDL",
    "description": "Export timeline as CMX 3600 EDL format (one video + four audio tracks)",
    "warning": "",
    "doc_url": "https://github.com/tin2tin/ExportEDL",
    "category": "Import-Export",
}


# ============================================================
# TIMECODE CLASS
# ============================================================

class TimeCode:
    """
    Simple timecode class for EDL conversion
    Supports CMX 3600 format: HH:MM:SS:FF
    """
    __slots__ = ("fps", "hours", "minutes", "seconds", "frame")

    def __init__(self, data, fps):
        self.fps = fps
        if isinstance(data, str):
            self.from_string(data)
            frame = self.as_frame()
            self.from_frame(frame)
        else:
            self.from_frame(data)

    def from_string(self, text):
        """Parse timecode from string"""
        if text.lower().endswith("mps"):
            return self.from_frame(int(float(text[:-3]) * self.fps))
        elif text.lower().endswith("s"):
            return self.from_frame(int(float(text[:-1]) * self.fps))
        elif text.isdigit():
            return self.from_frame(int(text))
        elif ":" in text:
            text = text.replace(";", ":").replace(",", ":").replace(".", ":")
            parts = text.split(":")
            self.hours = int(parts[0])
            self.minutes = int(parts[1])
            self.seconds = int(parts[2])
            self.frame = int(parts[3])
            return self
        else:
            print(f"ERROR: Could not convert to timecode: {text}")
            return self

    def from_frame(self, frame):
        """Convert frame number to timecode"""
        if frame < 0:
            frame = -frame
            neg = True
        else:
            neg = False

        self.frame = int(frame % self.fps)
        frame = (frame - self.frame) // self.fps
        self.seconds = int(frame % 60)
        frame = (frame - self.seconds) // 60
        self.minutes = int(frame % 60)
        self.hours = int((frame - self.minutes) // 60)

        if neg:
            self.frame = -self.frame
            self.seconds = -self.seconds
            self.minutes = -self.minutes
            self.hours = -self.hours

        return self

    def as_frame(self):
        """Convert timecode to frame number"""
        abs_frame = (
            (abs(self.hours) * 60 * 60 * self.fps) +
            (abs(self.minutes) * 60 * self.fps) +
            (abs(self.seconds) * self.fps) +
            abs(self.frame)
        )
        return -abs_frame if self.hours < 0 else abs_frame

    def __str__(self):
        """Format as HH:MM:SS:FF"""
        return f"{abs(self.hours):02d}:{abs(self.minutes):02d}:{abs(self.seconds):02d}:{abs(self.frame):02d}"


# ============================================================
# EDL BLOCK CLASS
# ============================================================

class EDLBlock:
    """
    Represents a single edit event in an EDL
    """
    def __init__(self):
        self.id = 0
        self.reel = "AX"  # Standard reel name
        self.channels = None  # V=video, A=audio
        self.transition = "C"  # C=cut, D=dissolve
        self.transDur = ""
        self.srcIn = None
        self.srcOut = None
        self.recIn = None
        self.recOut = None
        self.file = ""


class EDLList(list):
    """
    List of EDL blocks with export functionality
    """
    def __init__(self):
        super().__init__()
        self.title = "Untitled"
        self.dropframe = False

    def save_edl(self):
        """Generate EDL format string"""
        render = bpy.context.scene.render
        fps = int(round(render.fps / render.fps_base))

        # Header
        lines = []
        if self.title:
            lines.append(f"TITLE: {self.title}  {fps} fps")
        
        fcm = "DROP FRAME" if self.dropframe else "NON-DROP FRAME"
        lines.append(f"FCM: {fcm}")
        lines.append("")

        # Edit events
        for block in self:
            line = (
                f"{block.id:03d}  {block.reel:<8s} {block.channels:<4s}  "
                f"{block.transition:<4s} {block.transDur:>3s} "
                f"{str(block.srcIn):<11s} {str(block.srcOut):<11s} "
                f"{str(block.recIn):<11s} {str(block.recOut):<11s}"
            )
            lines.append(line)
            
            if block.file:
                lines.append(f"* FROM CLIP NAME: {block.file}")
                lines.append("")

        return "\n".join(lines)


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def check_fps():
    """
    Validate project FPS against EDL standards
    Returns: (fps, is_valid)
    """
    valid_fps = [24, 25, 30, 60]
    render = bpy.context.scene.render
    fps = round(render.fps / render.fps_base, 3)

    if fps in valid_fps:
        return int(fps) if fps.is_integer() else fps, True
    else:
        return fps, False


def get_sorted_strips(scene):
    """
    Get all strips sorted by start frame and channel
    """
    if not scene.sequence_editor:
        return []
    
    strips = [s for s in scene.sequence_editor.sequences_all]
    return sorted(strips, key=lambda s: (s.frame_final_start, s.channel))


# ============================================================
# EXPORT FUNCTION
# ============================================================

def write_edl(context, filepath):
    """
    Main EDL export function
    """
    print("Exporting EDL...")
    
    scene = context.scene
    fps, is_valid = check_fps()
    
    if not is_valid:
        return {'CANCELLED'}

    # Initialize EDL
    edl = EDLList()
    edl.title = bpy.path.display_name_from_filepath(filepath)
    
    strips = get_sorted_strips(scene)
    event_id = 1

    # Video track
    video_channel = scene.video_int
    for strip in strips:
        if strip.channel != video_channel or strip.type != 'MOVIE':
            continue

        block = EDLBlock()
        block.id = event_id
        block.reel = "AX"
        block.channels = "V"
        block.transition = "C"
        block.srcIn = TimeCode(strip.frame_offset_start, fps)
        block.srcOut = TimeCode(strip.frame_offset_start + strip.frame_final_duration, fps)
        block.recIn = TimeCode(strip.frame_final_start, fps)
        block.recOut = TimeCode(strip.frame_final_end, fps)
        block.file = bpy.path.basename(strip.filepath)
        
        edl.append(block)
        event_id += 1

    # Audio tracks
    audio_channels = [
        scene.audio1_int,
        scene.audio2_int,
        scene.audio3_int,
        scene.audio4_int
    ]
    
    for strip in strips:
        if strip.channel not in audio_channels or strip.type != 'SOUND':
            continue

        block = EDLBlock()
        block.id = event_id
        block.reel = "AX"
        block.channels = "A"  # Standard stereo audio
        block.transition = "C"
        block.srcIn = TimeCode(strip.frame_offset_start, fps)
        block.srcOut = TimeCode(strip.frame_offset_start + strip.frame_final_duration, fps)
        block.recIn = TimeCode(strip.frame_final_start, fps)
        block.recOut = TimeCode(strip.frame_final_end, fps)
        block.file = bpy.path.basename(strip.sound.filepath)
        
        edl.append(block)
        event_id += 1

    # Write file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(edl.save_edl())

    print(f"EDL exported: {filepath}")
    return {'FINISHED'}


# ============================================================
# OPERATORS
# ============================================================

class SEQUENCER_OT_export_edl(Operator, ExportHelper):
    """Export timeline as CMX 3600 EDL file"""
    bl_idname = "sequencer.export_edl"
    bl_label = "Export EDL"
    bl_options = {'REGISTER'}

    filename_ext = ".edl"
    filter_glob: StringProperty(
        default="*.edl",
        options={'HIDDEN'},
        maxlen=255,
    )

    def execute(self, context):
        fps, is_valid = check_fps()
        if not is_valid:
            self.report({'ERROR'}, f"Framerate {fps} not supported. Use 24, 25, 30, or 60 fps")
            return {'CANCELLED'}
        
        return write_edl(context, self.filepath)


# ============================================================
# UI PANEL
# ============================================================

class SEQUENCER_PT_edl_export(Panel):
    """EDL Export Panel in Video Sequencer"""
    bl_label = "Export EDL"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "EDL"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Track selection
        box = layout.box()
        box.label(text="Track Selection:", icon='SEQ_STRIP_DUPLICATE')
        box.prop(scene, "video_int", text="Video")
        box.prop(scene, "audio1_int", text="Audio 1")
        box.prop(scene, "audio2_int", text="Audio 2")
        box.prop(scene, "audio3_int", text="Audio 3")
        box.prop(scene, "audio4_int", text="Audio 4")

        # Export button
        layout.separator()
        
        fps, is_valid = check_fps()
        if not is_valid:
            box = layout.box()
            box.alert = True
            box.label(text=f"⚠ FPS {fps} not supported", icon='ERROR')
            box.label(text="Change to: 24, 25, 30, or 60")
        
        layout.operator("sequencer.export_edl", icon='EXPORT')


# ============================================================
# CHANNEL SELECTION CALLBACKS
# ============================================================

def update_channel_selection(channel_prop):
    """Factory function for channel update callbacks"""
    def update(self, context):
        channel = getattr(self, channel_prop)
        sed = self.sequence_editor
        
        if not sed:
            return
        
        # Deselect if active strip not in channel
        if getattr(sed.active_strip, "channel", -1) != channel:
            sed.active_strip = None
        
        # Select all strips in channel
        for strip in sed.sequences_all:
            strip.select = (strip.channel == channel)
    
    return update


# ============================================================
# REGISTRATION
# ============================================================

classes = (
    SEQUENCER_OT_export_edl,
    SEQUENCER_PT_edl_export,
)


def register():
    """Register addon"""
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Scene properties for track selection
    bpy.types.Scene.video_int = IntProperty(
        name="Video Channel",
        description="Channel for video export",
        min=1, max=32, default=1,
        update=update_channel_selection("video_int")
    )
    
    bpy.types.Scene.audio1_int = IntProperty(
        name="Audio Channel 1",
        description="First audio channel",
        min=1, max=32, default=2,
        update=update_channel_selection("audio1_int")
    )
    
    bpy.types.Scene.audio2_int = IntProperty(
        name="Audio Channel 2",
        description="Second audio channel",
        min=1, max=32, default=3,
        update=update_channel_selection("audio2_int")
    )
    
    bpy.types.Scene.audio3_int = IntProperty(
        name="Audio Channel 3",
        description="Third audio channel",
        min=1, max=32, default=4,
        update=update_channel_selection("audio3_int")
    )
    
    bpy.types.Scene.audio4_int = IntProperty(
        name="Audio Channel 4",
        description="Fourth audio channel",
        min=1, max=32, default=5,
        update=update_channel_selection("audio4_int")
    )


def unregister():
    """Unregister addon"""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    # Remove scene properties
    del bpy.types.Scene.video_int
    del bpy.types.Scene.audio1_int
    del bpy.types.Scene.audio2_int
    del bpy.types.Scene.audio3_int
    del bpy.types.Scene.audio4_int


if __name__ == "__main__":
    register()

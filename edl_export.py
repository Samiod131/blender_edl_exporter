# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

"""CMX 3600 EDL exporter for Blender Video Sequence Editor.

This module exports Blender VSE timelines to industry-standard CMX 3600
Edit Decision List (EDL) format for video editing workflows.
"""

import bpy
from bpy.props import IntProperty, StringProperty, CollectionProperty, EnumProperty
from bpy_extras.io_utils import ExportHelper
from bpy.types import Operator, Panel, PropertyGroup

bl_info = {
    "name": "Export EDL",
    "author": "Tintwotin, Campbell Barton, William R. Zwicky, batFINGER, szaszak, Samiod131",
    "version": (0, 8, 0),
    "blender": (4, 0, 0),
    "location": "Sequencer > Sidebar > EDL Export",
    "description": "Export timeline to EDL (CMX 3600, OpenShot, GVG, CMX 340)",
    "warning": "",
    "doc_url": "https://github.com/Samiod131/blender_edl_exporter",
    "category": "Import-Export",
}


# ============================================================
# TIMECODE CLASS
# ============================================================

class TimeCode:
    """Timecode representation for CMX 3600 EDL format.
    
    Converts between frame numbers and HH:MM:SS:FF timecode format.
    Supports both positive and negative timecodes.
    
    Attributes:
        fps (int): Frames per second.
        hours (int): Hour component of timecode.
        minutes (int): Minute component of timecode.
        seconds (int): Second component of timecode.
        frame (int): Frame component of timecode.
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
        """Parse timecode from string.
        
        Args:
            text (str): Timecode string in format HH:MM:SS:FF or frame number.
            
        Returns:
            TimeCode: Self for chaining.
        """
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
        """Convert frame number to timecode components.
        
        Args:
            frame (int): Absolute frame number.
            
        Returns:
            TimeCode: Self for chaining.
        """
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
        """Convert timecode components to absolute frame number.
        
        Returns:
            int: Frame number (negative if timecode is negative).
        """
        abs_frame = (
            (abs(self.hours) * 60 * 60 * self.fps) +
            (abs(self.minutes) * 60 * self.fps) +
            (abs(self.seconds) * self.fps) +
            abs(self.frame)
        )
        return -abs_frame if self.hours < 0 else abs_frame

    def __str__(self):
        """Format timecode as HH:MM:SS:FF string.
        
        Returns:
            str: Formatted timecode string.
        """
        return f"{abs(self.hours):02d}:{abs(self.minutes):02d}:{abs(self.seconds):02d}:{abs(self.frame):02d}"


# ============================================================
# EDL BLOCK CLASS
# ============================================================

class EDLBlock:
    """Single edit event in a CMX 3600 EDL.
    
    Attributes:
        id (int): Event number.
        reel (str): Source reel/tape name (default: "AX").
        channels (str): Channel designation (V, A1, A2, etc).
        transition (str): Transition type (default: "C" for cut).
        transDur (str): Transition duration in frames.
        srcIn (TimeCode): Source in timecode.
        srcOut (TimeCode): Source out timecode.
        recIn (TimeCode): Record in timecode.
        recOut (TimeCode): Record out timecode.
        file (str): Source filename.
    """
    __slots__ = ('id', 'reel', 'channels', 'transition', 'transDur', 'srcIn', 'srcOut', 'recIn', 'recOut', 'file')
    
    def __init__(self):
        self.id = 0
        self.reel = "AX"
        self.channels = None
        self.transition = "C"
        self.transDur = ""
        self.srcIn = None
        self.srcOut = None
        self.recIn = None
        self.recOut = None
        self.file = ""


class EDLList(list):
    """Container for EDL blocks with multi-format export capability.
    
    Attributes:
        title (str): EDL title.
        dropframe (bool): Whether to use drop frame timecode.
        format (str): Export format ('CMX3600', 'OPENSHOT', 'GVG', 'CMX340').
    """
    def __init__(self):
        super().__init__()
        self.title = "Untitled"
        self.dropframe = False
        self.format = 'CMX3600'

    def save_edl(self):
        """Generate EDL formatted string based on selected format.
        
        Returns:
            str: Complete EDL file content.
        """
        render = bpy.context.scene.render
        fps = int(round(render.fps / render.fps_base))

        lines = []
        if self.title:
            lines.append(f"TITLE: {self.title}  {fps} fps")
        
        fcm = "DROP FRAME" if self.dropframe else "NON-DROP FRAME"
        lines.append(f"FCM: {fcm}")
        lines.append("")

        for block in self:
            if self.format == 'GVG':
                line = (
                    f"{block.id:04d} {block.reel:<6s} {block.channels:<4s}  "
                    f"{block.transition:<4s} {block.transDur:>3s} "
                    f"{str(block.srcIn):<11s} {str(block.srcOut):<11s}  "
                    f"{str(block.recIn):<11s} {str(block.recOut):<11s}"
                )
            elif self.format == 'CMX340':
                line = (
                    f"{block.id:03d}  {block.reel:<3s}      {block.channels:<4s}  "
                    f"{block.transition:<4s} {block.transDur:>3s} "
                    f"{str(block.srcIn):<11s} {str(block.srcOut):<11s} "
                    f"{str(block.recIn):<11s} {str(block.recOut):<11s}"
                )
            else:
                line = (
                    f"{block.id:03d}  {block.reel:<8s} {block.channels:<4s}  "
                    f"{block.transition:<4s} {block.transDur:>3s} "
                    f"{str(block.srcIn):<11s} {str(block.srcOut):<11s} "
                    f"{str(block.recIn):<11s} {str(block.recOut):<11s}"
                )
            lines.append(line)
            
            if block.file:
                if self.format in ('OPENSHOT', 'GVG'):
                    lines.append(f"* FROM CLIP NAME: {block.file}")
                elif self.format == 'CMX3600':
                    lines.append(f"* SOURCE FILE: {block.file}")
                lines.append("")

        return "\n".join(lines)


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def get_fps():
    """Get project FPS rounded to integer.
    
    Returns:
        int: Project framerate rounded to nearest integer.
    """
    render = bpy.context.scene.render
    fps = render.fps / render.fps_base
    return int(round(fps))


def get_sorted_strips(scene):
    """Get all sequence strips sorted by timeline position.
    
    Args:
        scene: Blender scene object.
        
    Returns:
        list: Strips sorted by (start_frame, channel).
    """
    if not scene.sequence_editor:
        return []
    
    strips = [s for s in scene.sequence_editor.sequences_all]
    return sorted(strips, key=lambda s: (s.frame_final_start, s.channel))


def count_clips_in_channel(scene, channel, strip_type):
    """Count clips of a specific type in a channel.
    
    Args:
        scene: Blender scene object.
        channel (int): Channel number to check.
        strip_type (str): Strip type ('MOVIE', 'SOUND', etc).
        
    Returns:
        int: Number of matching clips.
    """
    if not scene.sequence_editor:
        return 0
    return sum(1 for s in scene.sequence_editor.sequences_all 
               if s.channel == channel and s.type == strip_type)


# ============================================================
# EXPORT FUNCTION
# ============================================================

def create_edl_block(strip, event_id, fps, channel_label, filepath):
    """Create an EDL block from a strip.
    
    Args:
        strip: Blender sequence strip.
        event_id (int): Event number.
        fps (int): Frames per second.
        channel_label (str): Channel designation (V, A1, A2, etc).
        filepath (str): Source file path.
        
    Returns:
        EDLBlock: Configured EDL block.
    """
    block = EDLBlock()
    block.id = event_id
    block.channels = channel_label
    block.srcIn = TimeCode(strip.frame_offset_start, fps)
    block.srcOut = TimeCode(strip.frame_offset_start + strip.frame_final_duration, fps)
    block.recIn = TimeCode(strip.frame_final_start, fps)
    block.recOut = TimeCode(strip.frame_final_end - 1, fps)
    block.file = bpy.path.basename(filepath)
    return block


def create_gap_block(event_id, fps, start_frame, end_frame, channel_label):
    """Create a black/gap EDL block.
    
    Args:
        event_id (int): Event number.
        fps (int): Frames per second.
        start_frame (int): Gap start frame.
        end_frame (int): Gap end frame.
        channel_label (str): Channel designation.
        
    Returns:
        EDLBlock: Configured gap block.
    """
    block = EDLBlock()
    block.id = event_id
    block.reel = "BL"
    block.channels = channel_label
    duration = end_frame - start_frame
    block.srcIn = TimeCode(1, fps)
    block.srcOut = TimeCode(duration, fps)
    block.recIn = TimeCode(start_frame, fps)
    block.recOut = TimeCode(end_frame - 1, fps)
    return block


def write_edl(context, filepath, edl_format):
    """Export Blender VSE timeline to EDL file.
    
    Args:
        context: Blender context.
        filepath (str): Output EDL file path.
        edl_format (str): EDL format ('CMX3600', 'OPENSHOT', 'GVG', 'CMX340').
        
    Returns:
        set: Blender operator return status {'FINISHED'} or {'CANCELLED'}.
    """
    scene = context.scene
    fps = get_fps()

    edl = EDLList()
    edl.title = bpy.path.display_name_from_filepath(filepath)
    edl.format = edl_format
    
    strips = get_sorted_strips(scene)
    event_id = 1
    reel_counter = 1

    if edl_format == 'OPENSHOT':
        video_strips = [s for s in strips if s.channel == scene.edl_video_channel and s.type == 'MOVIE']
        audio_channels = [track.channel for track in scene.edl_audio_tracks]
        audio_strips = [s for s in strips if s.channel in audio_channels and s.type == 'SOUND']
        
        all_strips = sorted(video_strips + audio_strips, key=lambda s: s.frame_final_start)
        
        last_end = scene.frame_start
        
        for strip in all_strips:
            if strip.frame_final_start > last_end:
                gap_v = create_gap_block(event_id, fps, last_end, strip.frame_final_start, "V")
                edl.append(gap_v)
                
                for audio_strip in [s for s in audio_strips if s.frame_final_start == strip.frame_final_start]:
                    gap_a = create_gap_block(event_id, fps, last_end, strip.frame_final_start, "A")
                    edl.append(gap_a)
            
            if strip.type == 'MOVIE':
                block_v = create_edl_block(strip, event_id, fps, "V", strip.filepath)
                edl.append(block_v)
                
                block_a = create_edl_block(strip, event_id, fps, "A", strip.filepath)
                edl.append(block_a)
            elif strip.type == 'SOUND':
                block = create_edl_block(strip, event_id, fps, "A", strip.sound.filepath)
                edl.append(block)
            
            last_end = max(last_end, strip.frame_final_end)
            event_id += 1
    
    elif edl_format == 'CMX340':
        for strip in strips:
            if strip.channel == scene.edl_video_channel and strip.type == 'MOVIE':
                block = create_edl_block(strip, event_id, fps, "V", strip.filepath)
                block.reel = f"{reel_counter:03d}"
                edl.append(block)
                event_id += 1
                reel_counter += 1
                if reel_counter > 999:
                    reel_counter = 1

        audio_channels = [track.channel for track in scene.edl_audio_tracks]
        for idx, ch in enumerate(audio_channels[:2]):
            for strip in strips:
                if strip.channel == ch and strip.type == 'SOUND':
                    channel_label = f"A{idx + 1}"
                    block = create_edl_block(strip, event_id, fps, channel_label, strip.sound.filepath)
                    block.reel = f"{reel_counter:03d}"
                    edl.append(block)
                    event_id += 1
                    reel_counter += 1
                    if reel_counter > 999:
                        reel_counter = 1
    
    elif edl_format == 'GVG':
        for strip in strips:
            if strip.channel == scene.edl_video_channel and strip.type == 'MOVIE':
                block = create_edl_block(strip, event_id, fps, "V", strip.filepath)
                block.reel = block.reel[:6]
                edl.append(block)
                event_id += 1

        audio_channels = [track.channel for track in scene.edl_audio_tracks]
        for strip in strips:
            if strip.channel in audio_channels and strip.type == 'SOUND':
                track_idx = audio_channels.index(strip.channel) + 1
                block = create_edl_block(strip, event_id, fps, f"A{track_idx}", strip.sound.filepath)
                block.reel = block.reel[:6]
                edl.append(block)
                event_id += 1
    
    else:
        for strip in strips:
            if strip.channel == scene.edl_video_channel and strip.type == 'MOVIE':
                block = create_edl_block(strip, event_id, fps, "V", strip.filepath)
                edl.append(block)
                event_id += 1

        audio_channels = [track.channel for track in scene.edl_audio_tracks]
        for strip in strips:
            if strip.channel in audio_channels and strip.type == 'SOUND':
                track_idx = audio_channels.index(strip.channel) + 1
                block = create_edl_block(strip, event_id, fps, f"A{track_idx}", strip.sound.filepath)
                edl.append(block)
                event_id += 1

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(edl.save_edl())

    return {'FINISHED'}


# ============================================================
# PROPERTY GROUPS
# ============================================================

class EDL_AudioTrack(PropertyGroup):
    """Property group representing a single audio track for EDL export.
    
    Attributes:
        channel: Audio channel number (1-32).
    """
    channel: IntProperty(
        name="Channel",
        description="Audio channel number",
        min=1, max=32, default=2
    )


# ============================================================
# OPERATORS
# ============================================================

class SEQUENCER_OT_add_audio_track(Operator):
    """Add an audio track to the EDL export configuration."""
    bl_idname = "sequencer.edl_add_audio_track"
    bl_label = "Add Audio Track"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        track = scene.edl_audio_tracks.add()
        
        used_channels = {scene.edl_video_channel, *(t.channel for t in scene.edl_audio_tracks)}
        track.channel = next((ch for ch in range(1, 33) if ch not in used_channels), 2)
        
        return {'FINISHED'}


class SEQUENCER_OT_remove_audio_track(Operator):
    """Remove an audio track from the EDL export configuration."""
    bl_idname = "sequencer.edl_remove_audio_track"
    bl_label = "Remove Audio Track"
    bl_options = {'REGISTER', 'UNDO'}
    
    index: IntProperty()
    
    def execute(self, context):
        scene = context.scene
        scene.edl_audio_tracks.remove(self.index)
        return {'FINISHED'}


class SEQUENCER_OT_export_edl(Operator, ExportHelper):
    """Export VSE timeline to EDL file in various formats."""
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
        edl_format = context.scene.edl_format
        result = write_edl(context, self.filepath, edl_format)
        
        if result == {'FINISHED'}:
            format_names = {
                'CMX3600': 'CMX 3600',
                'OPENSHOT': 'OpenShot',
                'GVG': 'GVG',
                'CMX340': 'CMX 340'
            }
            
            filepath = self.filepath
            
            def show_popup(popup_self, popup_context):
                popup_self.layout.label(text="EDL Export Successful!", icon='CHECKMARK')
                popup_self.layout.separator()
                popup_self.layout.label(text=f"Format: {format_names[edl_format]}")
                popup_self.layout.label(text=f"File: {filepath}")
            
            context.window_manager.popup_menu(show_popup, title="Export Complete", icon='INFO')
        
        return result
    
    def invoke(self, context, event):
        edl_format = context.scene.edl_format
        format_suffixes = {
            'CMX3600': 'CMX3600',
            'OPENSHOT': 'OpenShot',
            'GVG': 'GVG',
            'CMX340': 'CMX340'
        }
        
        if context.blend_data.filepath:
            blend_name = bpy.path.display_name_from_filepath(context.blend_data.filepath)
            self.filepath = f"{blend_name}_{format_suffixes[edl_format]}.edl"
        else:
            self.filepath = f"untitled_{format_suffixes[edl_format]}.edl"
        
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


# ============================================================
# UI PANEL
# ============================================================

class SEQUENCER_PT_edl_export(Panel):
    """EDL export panel in the Video Sequence Editor sidebar."""
    bl_label = "Export EDL"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "EDL"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        box = layout.box()
        box.label(text="Video Track:", icon='FILE_MOVIE')
        row = box.row(align=True)
        row.prop(scene, "edl_video_channel", text="Channel")
        video_count = count_clips_in_channel(scene, scene.edl_video_channel, 'MOVIE')
        row.label(text=f"{video_count} clips", icon='INFO')

        box = layout.box()
        box.label(text="Audio Tracks:", icon='SPEAKER')
        
        for i, track in enumerate(scene.edl_audio_tracks):
            row = box.row(align=True)
            row.prop(track, "channel", text=f"Track {i+1}")
            audio_count = count_clips_in_channel(scene, track.channel, 'SOUND')
            row.label(text=f"{audio_count}", icon='INFO')
            row.operator("sequencer.edl_remove_audio_track", text="", icon='X').index = i
        
        box.operator("sequencer.edl_add_audio_track", icon='ADD')

        layout.separator()
        
        box = layout.box()
        box.label(text="Export Format:", icon='FILE_TEXT')
        box.prop(scene, "edl_format", text="")
        
        layout.separator()
        fps = get_fps()
        box = layout.box()
        box.label(text=f"Project FPS: {fps}", icon='TIME')
        
        layout.separator()
        layout.operator("sequencer.export_edl", icon='EXPORT', text="Export EDL")





# ============================================================
# REGISTRATION
# ============================================================

classes = (
    EDL_AudioTrack,
    SEQUENCER_OT_add_audio_track,
    SEQUENCER_OT_remove_audio_track,
    SEQUENCER_OT_export_edl,
    SEQUENCER_PT_edl_export,
)


def register():
    """Register addon classes and properties."""
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.edl_video_channel = IntProperty(
        name="Video Channel",
        description="Channel for video export",
        min=1, max=32, default=1
    )
    
    bpy.types.Scene.edl_audio_tracks = CollectionProperty(
        type=EDL_AudioTrack,
        name="Audio Tracks",
        description="Audio channels for EDL export"
    )
    
    bpy.types.Scene.edl_format = EnumProperty(
        name="EDL Format",
        description="EDL format to export",
        items=[
            ('CMX3600', "CMX 3600", "Industry standard (Premiere, Resolve, Media Composer)"),
            ('OPENSHOT', "OpenShot", "OpenShot compatible with gaps and unified audio"),
            ('GVG', "GVG (Grass Valley)", "Grass Valley format with 6-char reel names"),
            ('CMX340', "CMX 340", "Legacy format with 3-char numeric reels (2 audio max)"),
        ],
        default='CMX3600',
    )
    
    def init_defaults():
        for scene in bpy.data.scenes:
            if len(scene.edl_audio_tracks) == 0:
                for ch in [2, 3, 4, 5]:
                    track = scene.edl_audio_tracks.add()
                    track.channel = ch
    
    bpy.app.timers.register(init_defaults, first_interval=0.1)


def unregister():
    """Unregister addon classes and remove properties."""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    del bpy.types.Scene.edl_video_channel
    del bpy.types.Scene.edl_audio_tracks
    del bpy.types.Scene.edl_format


if __name__ == "__main__":
    register()

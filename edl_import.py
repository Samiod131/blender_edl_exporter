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

"""CMX 3600 EDL importer for Blender Video Sequence Editor.

This module imports industry-standard CMX 3600 Edit Decision List (EDL) format
into Blender's VSE timeline for video editing workflows.
"""

import bpy
import os
from bpy.props import StringProperty, IntProperty, PointerProperty
from bpy.types import Operator, Panel, PropertyGroup

bl_info = {
    "name": "Import EDL",
    "author": "Samiod131",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "Sequencer > Sidebar > EDL Import",
    "description": "Import CMX 3600 EDL files with multi-track audio, dissolves, and markers",
    "warning": "Not a stable release.",
    "doc_url": "https://github.com/Samiod131/blender_edl_exporter",
    "category": "Import-Export",
}


# ============================================================
# EDL PARSING - CMX 3600 STANDARD
# ============================================================

# Transition type constants
TRANSITION_CUT = 0
TRANSITION_DISSOLVE = 1
TRANSITION_EFFECT = 2
TRANSITION_FADEIN = 3
TRANSITION_FADEOUT = 4
TRANSITION_WIPE = 5
TRANSITION_KEY = 6

TRANSITION_DICT = {
    "c": TRANSITION_CUT,
    "d": TRANSITION_DISSOLVE,
    "e": TRANSITION_EFFECT,
    "fi": TRANSITION_FADEIN,
    "fo": TRANSITION_FADEOUT,
    "w": TRANSITION_WIPE,
    "k": TRANSITION_KEY,
}

# Edit type constants
EDIT_VIDEO = 1 << 1
EDIT_AUDIO = 1 << 2
EDIT_AUDIO_STEREO = 1 << 3
EDIT_VIDEO_AUDIO = 1 << 4

EDIT_DICT = {
    "none": 0,
    "v": EDIT_VIDEO,
    "a": EDIT_AUDIO,
    "aa": EDIT_AUDIO_STEREO,
    "va": EDIT_VIDEO_AUDIO,
    "b": EDIT_VIDEO_AUDIO,
}

# Wipe type constants
WIPE_0 = 0
WIPE_1 = 1

# Key type constants
KEY_BG = 0
KEY_IN = 1
KEY_OUT = 2

# Black/gap identifiers
BLACK_ID = {"bw", "bl", "blk", "black"}


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
            # SMPTE timecode - handle various separators
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

        fpm = 60 * self.fps
        fph = 60 * fpm

        if frame < fph:
            self.hours = 0
        else:
            self.hours = int(frame / fph)
            frame = frame % fph

        if frame < fpm:
            self.minutes = 0
        else:
            self.minutes = int(frame / fpm)
            frame = frame % fpm

        if frame < self.fps:
            self.seconds = 0
        else:
            self.seconds = int(frame / self.fps)
            frame = frame % self.fps

        self.frame = frame

        if neg:
            self.frame = -self.frame
            self.seconds = -self.seconds
            self.minutes = -self.minutes
            self.hours = -self.hours

        return self

    def as_frame(self):
        """Convert timecode to absolute frame number.
        
        Returns:
            int: Frame number (negative if timecode is negative).
        """
        abs_frame = self.frame
        abs_frame += self.seconds * self.fps
        abs_frame += self.minutes * 60 * self.fps
        abs_frame += self.hours * 60 * 60 * self.fps
        return abs_frame

    def __str__(self):
        """Format timecode as HH:MM:SS:FF string.
        
        Returns:
            str: Formatted timecode string.
        """
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}:{self.frame:02d}"

    def __repr__(self):
        return self.__str__()

    def __int__(self):
        return self.as_frame()


class EditDecision:
    """Single edit event in a CMX 3600 EDL.
    
    Attributes:
        number (int): Event number.
        reel (str): Source reel/tape name.
        transition_duration (int): Transition duration in frames.
        edit_type (int): Edit type flags (video/audio).
        transition_type (int): Transition type constant.
        wipe_type (int): Wipe type constant.
        key_type (int): Key type constant.
        key_fade (bool): Key fade flag.
        srcIn (TimeCode): Source in timecode.
        srcOut (TimeCode): Source out timecode.
        recIn (TimeCode): Record in timecode.
        recOut (TimeCode): Record out timecode.
        filename (str): Source filename.
        custom_data (list): Additional metadata.
    """
    __slots__ = (
        "number", "reel", "transition_duration", "edit_type", "transition_type",
        "wipe_type", "key_type", "key_fade", "srcIn", "srcOut", "recIn", "recOut",
        "m2", "filename", "custom_data"
    )

    def __init__(self, text=None, fps=25):
        self.number = -1
        self.reel = ""
        self.transition_duration = 0
        self.edit_type = 0
        self.transition_type = TRANSITION_CUT
        self.wipe_type = WIPE_0
        self.key_type = KEY_IN
        self.key_fade = False
        self.srcIn = None
        self.srcOut = None
        self.recIn = None
        self.recOut = None
        self.m2 = None
        self.filename = ""
        self.custom_data = []
        
        if text is not None:
            try:
                self.read(text, fps)
            except Exception as e:
                print(f"Error parsing edit line: {e}")

    def read(self, line, fps):
        """Parse a single EDL line into an EditDecision.
        
        Handles both fixed-width (77 char) and space-separated formats.
        """
        # Check if it's a fixed-width format (77 characters)
        if len(line) == 77:
            parts = []
            parts.append(line[0:3].strip())      # Event number
            parts.append(line[5:12].strip())     # Reel name
            if line[14:18].strip():
                parts.append(line[14:18].strip())  # Edit mode (V/A/VA)
            if line[20:22].strip():
                parts.append(line[20:22].strip())  # Transition
            if line[23:25].strip():
                parts.append(line[23:25].strip())  # Duration/type
            if line[27:28].strip():
                parts.append(line[27:28].strip())  # Additional
            parts.append(line[29:40].strip())    # Source in
            parts.append(line[41:52].strip())    # Source out
            parts.append(line[53:64].strip())    # Record in
            parts.append(line[65:76].strip())    # Record out
            line = parts
        else:
            # Space-separated format
            line = line.split()

        index = 0
        
        # Event number
        self.number = int(line[index])
        index += 1
        
        # Reel/source name
        self.reel = line[index]
        index += 1

        # Edit type (V, A, VA, etc.)
        self.edit_type = 0
        for edit_type_str in line[index].lower().split("/"):
            # Strip digits for formats like A1, A2
            edit_type_clean = "".join(c for c in edit_type_str if not c.isdigit())
            if edit_type_clean in EDIT_DICT:
                self.edit_type |= EDIT_DICT[edit_type_clean]
        index += 1

        # Transition type
        trans_str = line[index].lower()
        tx_name = "".join(c for c in trans_str if not c.isdigit())
        self.transition_type = TRANSITION_DICT.get(tx_name, TRANSITION_CUT)

        # Handle wipe type
        if self.transition_type == TRANSITION_WIPE:
            tx_num = "".join(c for c in trans_str if c.isdigit())
            self.wipe_type = int(tx_num) if tx_num else 0

        # Handle key type
        elif self.transition_type == TRANSITION_KEY:
            if index + 1 < len(line):
                val = line[index + 1].lower()
                if val == "b":
                    self.key_type = KEY_BG
                    index += 1
                elif val == "o":
                    self.key_type = KEY_OUT
                    index += 1
                else:
                    self.key_type = KEY_IN
                
                # Check for fade flag
                if index + 1 < len(line) and line[index + 1].lower() == "(f)":
                    self.key_fade = True
                    index += 1

        index += 1

        # Transition duration (for dissolves, effects, etc.)
        if self.transition_type in {TRANSITION_DISSOLVE, TRANSITION_EFFECT, 
                                     TRANSITION_FADEIN, TRANSITION_FADEOUT, TRANSITION_WIPE}:
            if index < len(line):
                self.transition_duration = TimeCode(line[index], fps)
                index += 1

        # Timecodes
        if index < len(line):
            self.srcIn = TimeCode(line[index], fps)
            index += 1
        if index < len(line):
            self.srcOut = TimeCode(line[index], fps)
            index += 1
        if index < len(line):
            self.recIn = TimeCode(line[index], fps)
            index += 1
        if index < len(line):
            self.recOut = TimeCode(line[index], fps)
            index += 1

    def as_name(self):
        """Generate a human-readable name for this edit.
        
        Returns:
            str: Formatted name like '001_ClipName_cut'.
        """
        trans_name = "cut"
        for k, v in TRANSITION_DICT.items():
            if v == self.transition_type:
                trans_name = k
                break
        return f"{self.number:03d}_{self.reel}_{trans_name}"

    def __repr__(self):
        return (f"EditDecision(#{self.number} {self.reel} "
                f"rec:{self.recIn}->{self.recOut} src:{self.srcIn}->{self.srcOut})")


class EditList:
    """Container for all edit decisions in an EDL file.
    
    Attributes:
        edits (list): List of EditDecision objects.
        title (str): EDL title.
        detected_format (str): Auto-detected EDL format.
    """
    __slots__ = ("edits", "title", "detected_format")

    def __init__(self):
        self.edits = []
        self.title = ""
        self.detected_format = None

    def detect_format(self, file_lines):
        """Auto-detect EDL format from file content.
        
        Args:
            file_lines (list): List of file lines.
            
        Returns:
            str: Format name ('CMX3600', 'GVG', 'CMX340', 'OPENSHOT').
        """
        for line in file_lines:
            line = line.strip()
            if not line or line.startswith(("*", "#", "TITLE:", "FCM:")):
                continue
            
            parts = line.split()
            if parts and parts[0].isdigit():
                event_num = parts[0]
                
                # Check event number format
                if len(event_num) == 4:
                    return 'GVG'  # 4-digit event numbers
                elif len(event_num) == 3:
                    # Check reel name length to distinguish CMX3600 vs CMX340
                    if len(parts) > 1:
                        reel = parts[1]
                        if len(reel) <= 3 and reel.isdigit():
                            return 'CMX340'  # 3-char numeric reels
                        else:
                            # Check for OpenShot vs CMX3600 by comment style
                            return 'CMX3600'  # Default to CMX3600
                break
        
        return 'CMX3600'  # Default fallback

    def parse(self, filepath, fps):
        """Parse an EDL file.
        
        Args:
            filepath (str): Path to the EDL file.
            fps (int): Frames per second to use for timecode conversion.
            
        Returns:
            bool: True if parsing succeeded, False otherwise.
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                file_lines = f.readlines()
        except Exception as e:
            print(f"ERROR: Could not open file {filepath}: {e}")
            return False

        # Auto-detect format
        self.detected_format = self.detect_format(file_lines)
        print(f"Detected EDL format: {self.detected_format}")
        
        self.edits = []
        
        for index, line in enumerate(file_lines):
            # Normalize whitespace for non-fixed-width lines
            if len(line) != 77:
                line = " ".join(line.split())

            # Skip empty lines and comments
            if not line or line.startswith(("*", "#")):
                continue
            
            # Parse title
            if line.startswith("TITLE:"):
                self.title = " ".join(line.split()[1:])
                continue
            
            # Skip FCM (Frame Code Mode) and other header lines
            if line.startswith(("FCM:", "DROP FRAME", "NON-DROP FRAME")):
                continue
            
            # Check if line starts with a number (edit event)
            parts = line.split()
            if parts and parts[0].isdigit():
                try:
                    edit = EditDecision(line, fps)
                    self.edits.append(edit)
                    
                    # Check for filename or marker comment on next line
                    if index + 1 < len(file_lines):
                        next_line = file_lines[index + 1].strip()
                        if next_line.startswith("*"):
                            if "SOURCE FILE:" in next_line or "FROM CLIP NAME:" in next_line:
                                # Extract filename from comment
                                filename_part = next_line.split(":", 1)[1].strip()
                                edit.reel = filename_part
                            elif "MARKER:" in next_line:
                                # Store marker for timeline creation
                                marker_name = next_line.split(":", 1)[1].strip()
                                edit.custom_data.append(("marker", marker_name))
                except Exception as e:
                    print(f"⚠ Failed to parse event, skipping: {e}")
            else:
                pass  # Silently ignore unrecognized lines

        if len(self.edits) == 0:
            print(f"⚠ No valid events found in EDL")
            return False
        
        print(f"✓ Parsed {len(self.edits)} events from EDL")
        return True

    def reels_as_dict(self):
        """Group edits by reel/source name.
        
        Returns:
            dict: Dictionary mapping reel names to lists of EditDecision objects.
        """
        reels = {}
        for edit in self.edits:
            reels.setdefault(edit.reel, []).append(edit)
        return reels

    def overlap_test(self, edit_test):
        """Test if an edit overlaps with any previous edit on the timeline.
        
        Args:
            edit_test (EditDecision): EditDecision to test.
            
        Returns:
            bool: True if overlap detected, False otherwise.
        """
        recIn = int(edit_test.recIn)
        recOut = int(edit_test.recOut)

        for edit in self.edits:
            if edit is edit_test:
                break

            recIn_other = int(edit.recIn)
            recOut_other = int(edit.recOut)

            # Check for overlap
            if recIn_other < recIn < recOut_other:
                return True
            if recIn_other < recOut < recOut_other:
                return True
            if recIn < recIn_other < recOut:
                return True
            if recIn < recOut_other < recOut:
                return True

        return False


# ============================================================
# IMPORT FUNCTIONS
# ============================================================

def get_open_channel(scene):
    """Find the first free channel in the sequencer.
    
    Args:
        scene: Blender scene object.
        
    Returns:
        int: First available channel number.
    """
    if not scene.sequence_editor:
        return 1
    
    channels = [s.channel for s in scene.sequence_editor.sequences_all]
    return max(channels) + 1 if channels else 1


def apply_dissolve_fcurve(strip, duration):
    """Apply a dissolve transition using animated blend_alpha.
    
    Args:
        strip: Blender sequence strip.
        duration (int): Dissolve duration in frames.
    """
    scene = strip.id_data
    
    # Create animation data if needed
    scene.animation_data_create()
    if scene.animation_data.action is None:
        scene.animation_data.action = bpy.data.actions.new(name="Scene Action")
    
    action = scene.animation_data.action
    data_path = strip.path_from_id("blend_alpha")
    
    # Create or get the fcurve
    fcurve = action.fcurves.find(data_path)
    if not fcurve:
        fcurve = action.fcurves.new(data_path, index=0)
    
    # Add keyframes for fade
    fcurve.keyframe_points.insert(strip.frame_final_start, 0.0)
    fcurve.keyframe_points.insert(strip.frame_final_end, 1.0)
    
    # Set interpolation
    for kf in fcurve.keyframe_points:
        kf.interpolation = 'LINEAR'
    
    # Set blend type
    if strip.type != 'SOUND':
        strip.blend_type = 'ALPHA_OVER'


def load_edl(scene, filepath, reel_files, reel_offsets, global_offset=0, video_channel=1, audio_channels=None):
    """Load an EDL file into the Blender sequencer.
    
    Args:
        scene: Blender scene to import into.
        filepath (str): Path to the EDL file.
        reel_files (dict): Dictionary mapping reel names to file paths.
        reel_offsets (dict): Dictionary mapping reel names to frame offsets.
        global_offset (int): Global frame offset to apply to all clips.
        video_channel (int): Channel number for video strips.
        audio_channels (list): List of channel numbers for audio tracks.
        
    Returns:
        str: Empty string on success, error message on failure.
    """
    fps = scene.render.fps
    print(f"\n=== EDL IMPORT START ===")
    print(f"Scene FPS: {fps}")
    if fps < 20:
        print(f"WARNING: Scene FPS is {fps}, but most EDLs are 24/25/30 fps!")
        print(f"Set Output Properties > Frame Rate to match your EDL!")
    print(f"Video Channel: {video_channel}")
    print(f"Audio Channels: {audio_channels}")
    print(f"Reel files: {reel_files}")
    print(f"Reel offsets: {reel_offsets}")
    
    # Parse the EDL
    elist = EditList()
    if not elist.parse(filepath, fps):
        return f"Unable to parse {filepath}"
    
    print(f"\nParsed {len(elist.edits)} total edits from EDL")
    for edit in elist.edits:
        src_duration = int(edit.srcOut) - int(edit.srcIn)
        rec_duration = int(edit.recOut) - int(edit.recIn)
        print(f"  Edit {edit.number}: {edit.reel} type={edit.edit_type} srcIn={edit.srcIn} srcOut={edit.srcOut} (dur={src_duration}) recIn={edit.recIn} recOut={edit.recOut} (dur={rec_duration})")
        if src_duration < 0:
            print(f"    ERROR: srcOut comes BEFORE srcIn!")
        if rec_duration < 0:
            print(f"    ERROR: recOut comes BEFORE recIn!")
    
    # Create sequence editor if needed
    if not scene.sequence_editor:
        scene.sequence_editor_create()
    sequence_editor = scene.sequence_editor
    
    # Initialize audio_channels to default if None
    if audio_channels is None:
        audio_channels = [2]
    
    # Validate audio channels
    if not isinstance(audio_channels, list):
        print(f"WARNING: audio_channels should be a list, got {type(audio_channels)}")
        audio_channels = [audio_channels] if audio_channels else [2]
    
    # Deselect all strips
    for strip in sequence_editor.sequences_all:
        strip.select = False
    
    strip_list = []
    prev_edit = None
    
        # Count clips for progress
    video_count = sum(1 for e in elist.edits if e.edit_type & (EDIT_VIDEO | EDIT_VIDEO_AUDIO))
    audio_count = sum(1 for e in elist.edits if (e.edit_type & (EDIT_AUDIO | EDIT_AUDIO_STEREO | EDIT_VIDEO_AUDIO)) and e.reel.lower() not in BLACK_ID)
    total_clips = video_count + (audio_count * len(audio_channels))  # Multiply by tracks
    
    print(f"\nImporting {video_count} video + {audio_count} audio clips across {len(audio_channels)} track(s) (total: {total_clips})")
    
    # Process video and audio separately
    # First pass: Video clips
    current_clip = 0
    for edit in elist.edits:
        # Skip non-video edits
        if not (edit.edit_type & (EDIT_VIDEO | EDIT_VIDEO_AUDIO)):
            continue
        
        current_clip += 1
        clip_type = "Black" if edit.reel.lower() in BLACK_ID else "Video"
        print(f"[{current_clip}/{total_clips}] {clip_type}: {edit.reel}")
        
        # Determine frame offset
        if edit.reel.lower() in BLACK_ID:
            frame_offset = 0
        else:
            frame_offset = reel_offsets.get(edit.reel, 0)
        
        # Calculate timings
        src_start = int(edit.srcIn) + frame_offset
        rec_start = int(edit.recIn) + global_offset
        rec_end = int(edit.recOut) + global_offset
        rec_length = rec_end - rec_start
        
        # Validate timecodes
        src_duration = int(edit.srcOut) - int(edit.srcIn)
        rec_duration = rec_end - rec_start
        if src_duration <= 0:
            print(f"  ERROR: Invalid source duration ({src_duration}), skipping")
            continue
        if rec_duration <= 0:
            print(f"  ERROR: Invalid record duration ({rec_duration}), skipping")
            continue
        
        # Handle black/gap
        if edit.reel.lower() in BLACK_ID:
            try:
                # frame_end is EXCLUSIVE in new_effect, so add 1 to include recOut
                print(f"  Creating BLACK: frame_start={rec_start}, frame_end={rec_end + 1} (recOut={rec_end})")
                strip = sequence_editor.sequences.new_effect(
                    name="Black",
                    type='COLOR',
                    frame_start=rec_start,
                    frame_end=rec_end + 1,  # +1 because frame_end is exclusive
                    channel=video_channel
                )
                strip.color = (0.0, 0.0, 0.0)
                strip_list.append(strip)
                print(f"  BLACK created: frame_final_start={strip.frame_final_start}, frame_final_end={strip.frame_final_end}, duration={strip.frame_final_duration}")
                edit.custom_data = [strip]
            except Exception as e:
                print(f"  ERROR creating black strip: {e}")
                prev_edit = edit  # Still track for transitions
                continue
        else:
            # Regular video clip
            if edit.reel not in reel_files:
                print(f"WARNING: Reel '{edit.reel}' not found in reel_files")
                continue
            
            path_full = reel_files[edit.reel]
            
            try:
                # CORRECT Blender approach:
                # 1. Place strip at timeline position (recIn)
                # 2. Use animation_offset_start to skip source frames (srcIn)
                # 3. Use animation_offset_end to trim from end
                print(f"  API CALL: sequences.new_movie(name='{edit.reel}', filepath='{path_full}', channel={video_channel}, frame_start={rec_start})")
                
                strip = sequence_editor.sequences.new_movie(
                    name=edit.reel,
                    filepath=path_full,
                    channel=video_channel,
                    frame_start=rec_start
                )
                strip_list.append(strip)
                
                if strip.channel != video_channel:
                    print(f"  *** ERROR: VIDEO moved to channel {strip.channel} instead of {video_channel}! ***")
                
                print(f"  CREATED: Strip '{strip.name}' on channel {strip.channel}")
                print(f"    frame_duration={strip.frame_duration}")
                print(f"    frame_start={strip.frame_start}")
                print(f"    frame_final_start={strip.frame_final_start}")
                print(f"    frame_final_end={strip.frame_final_end}")
                
                # Trim source: skip srcIn frames from start, trim from end to srcOut
                src_end = int(edit.srcOut) + frame_offset
                trim_start = src_start
                trim_end = strip.frame_duration - src_end
                
                print(f"  TRIMMING: animation_offset_start={trim_start}, animation_offset_end={trim_end}")
                strip.animation_offset_start = trim_start
                strip.animation_offset_end = trim_end
                
                print(f"  RESULT:")
                print(f"    frame_final_start={strip.frame_final_start} (should be {rec_start})")
                print(f"    frame_final_end={strip.frame_final_end} (should be {rec_end})")
                print(f"    frame_final_duration={strip.frame_final_duration} (should be {rec_end - rec_start})")
                
                # Apply dissolve transition
                if edit.transition_type == TRANSITION_DISSOLVE and edit.transition_duration:
                    dissolve_duration = int(edit.transition_duration)
                    
                    # Extend previous clip to overlap
                    if prev_edit and prev_edit.custom_data:
                        for prev_strip in prev_edit.custom_data:
                            if prev_strip.type in ('MOVIE', 'IMAGE'):
                                # Reduce the trim at the end to extend the clip
                                prev_strip.frame_offset_end = max(0, prev_strip.frame_offset_end - dissolve_duration)
                    
                    # Apply fade to current clip
                    apply_dissolve_fcurve(strip, dissolve_duration)
                
                # Apply wipe transition
                if edit.transition_type == TRANSITION_WIPE and prev_edit and prev_edit.custom_data:
                    from math import radians
                    
                    for prev_strip in prev_edit.custom_data:
                        if prev_strip.type in ('MOVIE', 'IMAGE'):
                            try:
                                # Create wipe effect between previous and current clip
                                wipe_channel = video_channel + 1
                                strip_wipe = sequence_editor.sequences.new_effect(
                                    name="Wipe",
                                    type='WIPE',
                                    seq1=prev_strip,
                                    seq2=strip,
                                    frame_start=rec_start,
                                    channel=wipe_channel
                                )
                                
                                # Set wipe direction based on wipe_type
                                if edit.wipe_type == WIPE_0:
                                    strip_wipe.angle = radians(90)   # Right to left
                                else:
                                    strip_wipe.angle = radians(-90)  # Left to right
                                
                                strip_list.append(strip_wipe)
                                break
                            except Exception as e:
                                print(f"  ⚠ Could not create wipe: {e}")
                
                # Set name
                strip.name = edit.as_name()
                edit.custom_data = [strip]
                
            except Exception as e:
                print(f"  ⚠ Error loading video: {e}")
                prev_edit = edit  # Still track for transitions
                continue
        
        prev_edit = edit
    
    # Second pass: Audio clips (multi-track support)
    for track_idx, audio_ch in enumerate(audio_channels, 1):
        print(f"\n--- Processing Audio Track {track_idx} (Channel {audio_ch}) ---")
        
        for edit in elist.edits:
            # Skip non-audio edits
            if not (edit.edit_type & (EDIT_AUDIO | EDIT_AUDIO_STEREO | EDIT_VIDEO_AUDIO)):
                continue
            
            # Skip black clips for audio
            if edit.reel.lower() in BLACK_ID:
                continue
            
            current_clip += 1
            print(f"[{current_clip}/{total_clips}] Audio Track {track_idx}: {edit.reel}")
            
            # Determine frame offset
            frame_offset = reel_offsets.get(edit.reel, 0)
            
            # Calculate timings
            src_start = int(edit.srcIn) + frame_offset
            rec_start = int(edit.recIn) + global_offset
            rec_end = int(edit.recOut) + global_offset
            
            # Validate timecodes
            src_duration = int(edit.srcOut) - int(edit.srcIn)
            rec_duration = rec_end - rec_start
            if src_duration <= 0 or rec_duration <= 0:
                print(f"  ERROR: Invalid audio duration, skipping")
                continue
            
            # Load audio
            if edit.reel not in reel_files:
                print(f"  WARNING: Reel '{edit.reel}' not in reel_files")
                continue
            
            path_full = reel_files[edit.reel]
            
            try:
                strip = sequence_editor.sequences.new_sound(
                    name=edit.reel,
                    filepath=path_full,
                    channel=audio_ch,
                    frame_start=rec_start
                )
                strip_list.append(strip)
                
                # Trim source audio
                src_end = int(edit.srcOut) + frame_offset
                trim_start = src_start
                trim_end = strip.frame_duration - src_end
                
                strip.animation_offset_start = trim_start
                strip.animation_offset_end = trim_end
                strip.name = f"{edit.as_name()}_A{track_idx}"
                
                print(f"  ✓ Audio loaded on channel {audio_ch}")
                
            except Exception as e:
                # Fallback: try .wav extension
                try:
                    path_wav = os.path.splitext(path_full)[0] + ".wav"
                    
                    strip = sequence_editor.sequences.new_sound(
                        name=edit.reel,
                        filepath=path_wav,
                        channel=audio_ch,
                        frame_start=rec_start
                    )
                    strip_list.append(strip)
                    
                    # Trim source audio
                    src_end = int(edit.srcOut) + frame_offset
                    trim_start = src_start
                    trim_end = strip.frame_duration - src_end
                    
                    strip.animation_offset_start = trim_start
                    strip.animation_offset_end = trim_end
                    strip.name = f"{edit.as_name()}_A{track_idx}"
                    
                    print(f"  ✓ WAV loaded on channel {audio_ch}")
                except Exception as e2:
                    print(f"  ERROR: Could not load audio from {path_full} or .wav: {e2}")
    
    # Select all imported strips
    for strip in strip_list:
        strip.select = True
    
    # Create timeline markers from EDL comments
    marker_count = 0
    for edit in elist.edits:
        if isinstance(edit.custom_data, list):
            for item in edit.custom_data:
                if isinstance(item, tuple) and len(item) == 2:
                    data_type, data_value = item
                    if data_type == "marker":
                        # Create marker at clip start (with global offset)
                        marker_frame = int(edit.recIn) + global_offset
                        marker = scene.timeline_markers.new(data_value, frame=marker_frame)
                        marker_count += 1
    
    if marker_count > 0:
        print(f"\n✓ Created {marker_count} timeline markers")
    
    # Summary
    video_imported = sum(1 for s in strip_list if s.type in ('MOVIE', 'IMAGE', 'COLOR'))
    audio_imported = sum(1 for s in strip_list if s.type == 'SOUND')
    print(f"\n=== IMPORT COMPLETE ===")
    print(f"✓ Video strips: {video_imported}")
    print(f"✓ Audio strips: {audio_imported}")
    print(f"✓ Total: {len(strip_list)} strips added to timeline")
    return ""


# ============================================================
# PROPERTY GROUPS
# ============================================================

class EDLReelInfo(PropertyGroup):
    """Property group storing information about a single reel/source.
    
    Attributes:
        name: Reel name.
        filepath: Path to source file.
        frame_offset: Frame offset for this reel.
    """
    name: StringProperty(name="Reel Name")
    filepath: StringProperty(name="File Path", subtype='FILE_PATH')
    frame_offset: IntProperty(name="Frame Offset", default=0)


class EDLAudioTrack(PropertyGroup):
    """Property group for audio track configuration.
    
    Attributes:
        channel: Audio channel number (1-128).
    """
    channel: IntProperty(name="Channel", default=2, min=1, max=128)


class EDLImportInfo(PropertyGroup):
    """Property group storing EDL import configuration.
    
    Attributes:
        filepath: Path to EDL file.
        frame_offset: Global frame offset.
        video_channel: Video channel number.
        audio_tracks: Collection of audio track configurations.
        reels: Collection of reel information.
    """
    filepath: StringProperty(name="EDL File", subtype='FILE_PATH')
    frame_offset: IntProperty(name="Global Frame Offset", default=0)
    video_channel: IntProperty(name="Video Channel", default=1, min=1, max=128)
    audio_tracks: bpy.props.CollectionProperty(type=EDLAudioTrack)
    reels: bpy.props.CollectionProperty(type=EDLReelInfo)


# ============================================================
# OPERATORS
# ============================================================

class SEQUENCER_OT_reload_edl(Operator):
    """Reload EDL file and refresh reel list."""
    bl_idname = "sequencer.import_edl_refresh"
    bl_label = "Refresh Reels"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        edl_import_info = scene.edl_import_info
        filepath = bpy.path.abspath(edl_import_info.filepath)  # Convert // to absolute path
        
        if not os.path.exists(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}
        
        # Parse EDL to get reel list (use scene FPS for parsing)
        fps = scene.render.fps
        elist = EditList()
        if not elist.parse(filepath, fps):
            self.report({'ERROR'}, f"Failed to parse EDL: {filepath}")
            return {'CANCELLED'}
        
        # Save existing reel data
        data_prev = {reel.name: (reel.filepath, reel.frame_offset)
                     for reel in edl_import_info.reels}
        
        # Get unique reels (excluding black)
        reels_dict = elist.reels_as_dict()
        reel_names = [k for k in reels_dict.keys() if k.lower() not in BLACK_ID]
        
        # Rebuild reel collection
        edl_import_info.reels.clear()
        for name in sorted(reel_names):
            reel = edl_import_info.reels.add()
            reel.name = name
            # Restore previous values if available
            if name in data_prev:
                reel.filepath, reel.frame_offset = data_prev[name]
        
        self.report({'INFO'}, f"Found {len(reel_names)} reels in EDL")
        return {'FINISHED'}


class SEQUENCER_OT_find_reels(Operator):
    """Scan directory for missing reel files."""
    bl_idname = "sequencer.import_edl_findreel"
    bl_label = "Scan For Missing Files"
    bl_options = {'REGISTER'}
    
    directory: StringProperty(subtype='DIR_PATH')

    @staticmethod
    def missing_reels(context):
        """Get list of reels without valid file paths."""
        scene = context.scene
        edl_import_info = scene.edl_import_info
        return [reel for reel in edl_import_info.reels
                if not os.path.exists(bpy.path.abspath(reel.filepath))]

    def execute(self, context):
        scene = context.scene
        missing = SEQUENCER_OT_find_reels.missing_reels(context)
        
        if not missing:
            self.report({'INFO'}, "All reels have valid file paths")
            return {'FINISHED'}
        
        # Scan directory for media files
        found = 0
        for reel in missing:
            # Try to find file matching reel name
            for root, dirs, files in os.walk(self.directory):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for filename in files:
                    name_only = os.path.splitext(filename)[0]
                    # Match by name (case insensitive)
                    if name_only.lower() == reel.name.lower():
                        reel.filepath = os.path.join(root, filename)
                        found += 1
                        break
                if reel.filepath:
                    break
        
        still_missing = len([r for r in missing if not r.filepath])
        self.report({'INFO'}, f"Found {found} files, {still_missing} still missing")
        return {'FINISHED'}

    def invoke(self, context, event):
        scene = context.scene
        edl_import_info = scene.edl_import_info
        
        if not SEQUENCER_OT_find_reels.missing_reels(context):
            self.report({'INFO'}, "All reels already have valid file paths")
            return {'CANCELLED'}
        
        # Default to EDL directory
        if not self.directory and edl_import_info.filepath:
            filepath_abs = bpy.path.abspath(edl_import_info.filepath)
            self.directory = os.path.dirname(filepath_abs)
        
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SEQUENCER_OT_add_audio_track(Operator):
    """Add an audio track to the EDL import configuration."""
    bl_idname = "sequencer.import_edl_add_audio"
    bl_label = "Add Audio Track"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        track = scene.edl_import_info.audio_tracks.add()
        # Find first unused channel
        used = {scene.edl_import_info.video_channel} | {t.channel for t in scene.edl_import_info.audio_tracks}
        track.channel = next((ch for ch in range(1, 33) if ch not in used), 2)
        return {'FINISHED'}


class SEQUENCER_OT_remove_audio_track(Operator):
    """Remove an audio track from the EDL import configuration."""
    bl_idname = "sequencer.import_edl_remove_audio"
    bl_label = "Remove Audio Track"
    bl_options = {'REGISTER', 'UNDO'}
    
    index: IntProperty()
    
    def execute(self, context):
        scene = context.scene
        scene.edl_import_info.audio_tracks.remove(self.index)
        return {'FINISHED'}


class SEQUENCER_OT_import_edl(Operator):
    """Import EDL file into Video Sequence Editor."""
    bl_idname = "sequencer.import_edl"
    bl_label = "Import EDL"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        edl_import_info = scene.edl_import_info
        
        filepath = bpy.path.abspath(edl_import_info.filepath)  # Convert // to absolute path
        if not os.path.exists(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}
        
        # Build reel dictionaries (convert relative paths to absolute)
        reel_files = {reel.name: bpy.path.abspath(reel.filepath) for reel in edl_import_info.reels}
        reel_offsets = {reel.name: reel.frame_offset for reel in edl_import_info.reels}
        
        # Import EDL with all configured audio tracks
        audio_channels = [track.channel for track in edl_import_info.audio_tracks]
        if not audio_channels:
            audio_channels = [2]  # Default fallback
        
        msg = load_edl(
            scene, filepath,
            reel_files, reel_offsets,
            edl_import_info.frame_offset,
            edl_import_info.video_channel,
            audio_channels
        )
        
        if msg:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        
        self.report({'INFO'}, "EDL imported successfully")
        return {'FINISHED'}


# ============================================================
# UI PANEL
# ============================================================

class SEQUENCER_PT_import_edl(Panel):
    """EDL import panel in the Video Sequence Editor sidebar."""
    bl_label = "Import EDL"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "EDL"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        
        scene = context.scene
        edl_import_info = scene.edl_import_info
        
        # EDL file selection
        box = layout.box()
        box.label(text="EDL File:", icon='FILE_TEXT')
        box.prop(edl_import_info, "filepath", text="")
        
        # Refresh button
        row = box.row()
        row.operator("sequencer.import_edl_refresh", text="Load EDL", icon='FILE_REFRESH')
        row.enabled = bool(edl_import_info.filepath)
        
        # Reel list
        if edl_import_info.reels:
            box = layout.box()
            box.label(text="Source Files:", icon='FILE_MOVIE')
            
            missing_count = 0
            for reel in edl_import_info.reels:
                row = box.row()
                if reel.filepath and os.path.exists(bpy.path.abspath(reel.filepath)):
                    row.prop(reel, "filepath", text=f"✓ {reel.name}")
                else:
                    row.prop(reel, "filepath", text=f"✗ {reel.name}")
                    row.alert = True
                    missing_count += 1
            
            # Scan for missing files
            if missing_count > 0:
                row = box.row()
                row.operator("sequencer.import_edl_findreel", 
                           text=f"Find {missing_count} Missing File(s)", 
                           icon='VIEWZOOM')
        
        layout.separator()
        
        # Options
        box = layout.box()
        box.label(text="Options:", icon='PREFERENCES')
        box.prop(edl_import_info, "frame_offset", text="Global Frame Offset")
        box.prop(edl_import_info, "video_channel", text="Video Channel")
        
        # Audio tracks
        box.label(text="Audio Tracks:")
        for i, track in enumerate(edl_import_info.audio_tracks):
            row = box.row(align=True)
            row.prop(track, "channel", text=f"Track {i+1}")
            row.operator("sequencer.import_edl_remove_audio", text="", icon='X').index = i
        box.operator("sequencer.import_edl_add_audio", text="Add Audio Track", icon='ADD')
        
        layout.separator()
        
        # Import button
        row = layout.row()
        row.scale_y = 1.5
        row.operator("sequencer.import_edl", text="Import EDL", icon='IMPORT')
        row.enabled = bool(edl_import_info.reels)


# ============================================================
# REGISTRATION
# ============================================================

classes = (
    EDLReelInfo,
    EDLAudioTrack,
    EDLImportInfo,
    SEQUENCER_OT_reload_edl,
    SEQUENCER_OT_find_reels,
    SEQUENCER_OT_add_audio_track,
    SEQUENCER_OT_remove_audio_track,
    SEQUENCER_OT_import_edl,
    SEQUENCER_PT_import_edl,
)


def register():
    """Register addon classes and properties."""
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.edl_import_info = PointerProperty(type=EDLImportInfo)


def unregister():
    """Unregister addon classes and properties."""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    del bpy.types.Scene.edl_import_info


if __name__ == "__main__":
    register()


# Blender EDL Exporter

Export Blender VSE timelines to EDL (Edit Decision List) format for use in other video editors.

## What It Does

- Exports video + audio tracks to EDL files
- Supports 4 formats: CMX 3600, OpenShot, GVG, CMX 340
- Dynamic audio track configuration
- Auto-generates format-specific filenames

## Installation

1. Copy `edl_export.py` to Blender addons folder
2. Enable in: Edit → Preferences → Add-ons → "Export EDL"

## Usage

**In VSE Sidebar (N key) → EDL Panel:**

1. Set video channel (default: 1)
2. Add/remove audio tracks with channels
3. Select export format (CMX 3600/OpenShot/GVG/CMX 340)
4. Click "Export EDL"

**Formats:**
- **CMX 3600**: Premiere, Resolve, Media Composer, Final Cut
- **OpenShot**: OpenShot, Kdenlive (with gaps)
- **GVG**: Grass Valley (6-char reel names)
- **CMX 340**: Legacy (3-char reels, 2 audio max)

## Requirements

- Blender 4.0+
- Any FPS (rounded to integer for timecode)
- Strips: MOVIE (video), SOUND (audio)

## Limitations

- No effects/transitions (EDL format limitation)
- No meta strips
- Basic cuts only

## Roadmap

See `FORMATS.md` for planned formats (MLT XML, FCP XML).

---

*Work in progress. Contributions welcome.*

# Blender EDL Exporter

Export Blender VSE timelines to EDL format for use in other video editors.

## Features

- Exports video + audio tracks
- 4 formats: CMX 3600, OpenShot, GVG, CMX 340
- Markers, gaps, dissolves, metadata
- Image sequence support

## Usage

1. Open VSE sidebar (N key) → EDL tab
2. Set video channel
3. Add audio tracks
4. Select format (CMX 3600 recommended)
5. Click "Export EDL"

**Formats:**
- **CMX 3600**: Premiere, Resolve, Media Composer
- **OpenShot**: OpenShot, Kdenlive
- **GVG**: Grass Valley
- **CMX 340**: Legacy (2 audio max)

## Requirements

- Blender 4.0+
- Supported: MOVIE, SOUND, IMAGE strips
- Transitions: CROSS, GAMMA_CROSS

## Limitations

EDL format supports:
- ✅ Cuts and dissolves
- ✅ Markers (as comments)
- ✅ Gaps
- ❌ Effects (except dissolves)
- ❌ Blend modes

For effects/blend modes, use MLT XML or FCP7 XML (planned).

---

**Version**: 0.9.0 | **License**: GPL v2+ | **Blender**: 4.0+

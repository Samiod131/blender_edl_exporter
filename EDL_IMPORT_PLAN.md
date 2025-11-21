# EDL Import Plan

## Flow

1. Parse EDL → list of events
2. Find media files (by filename)
3. Create VSE strips with timecode offsets

---

## Data

```python
class EDLEvent:
    event_id: int
    reel: str
    channels: str  # 'V', 'A1', 'A2'
    src_in: TimeCode
    src_out: TimeCode
    rec_in: TimeCode
    rec_out: TimeCode
    filename: str  # from comment
```

## Steps

**1. Parser (5-8h)**
- Read EDL text
- Regex parse events
- Parse comments for filenames
- Convert timecodes to frames
- Return list of EDLEvent

**2. Media Finder (3-5h)**
- Search by filename in:
  - EDL folder
  - User folder
- File picker for missing

**3. VSE Creator (4-6h)**
- Create sequence editor
- For each event:
  - Create MOVIE/SOUND strip
  - Set frame_start, frame_offset_start, duration
  - Assign channel

**4. UI (2-3h)**
- Import operator
- Folder picker
- Missing file dialog

## Total: 14-22 hours

## Limitations
- Filename matching only
- No effects/transitions
- CMX 3600 initially

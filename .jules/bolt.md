## 2025-05-15 - Redundant Large-Scale Data Fetching
**Learning:** The media library routes were fetching a user's entire watch history (all records in 'progress' table) for every page request or show view, even though the primary SQL queries for those routes already performed a LEFT JOIN with the progress table. This resulted in O(N) database overhead and O(M) memory overhead per request where M is the total size of the user's history.
**Action:** Always check if primary entity queries (like library items) already join with auxiliary data (like user progress) before performing a separate bulk fetch.

## 2025-05-16 - Codec-Aware Filtering for Low-Power Devices
**Learning:** Generic container filtering (like "mp4") is insufficient for low-power devices (Pi Zero/3B) that cannot transcode. These devices need H.264 specific streams, which can be found in various containers (MP4, MKV).
**Action:** Extract specific codec metadata (HEVC, H264, AV1) from stream titles to enable precise compatibility filtering.

## 2025-05-16 - Explicit Error Mapping in Background Workers
**Learning:** Background download workers often fail silently or with generic messages when links expire (401/403) or are deleted (404). This leads to user frustration and "silent failure" reports.
**Action:** Always map specific HTTP status codes to user-friendly actionable instructions (e.g., "Link expired, try refreshing") within background task error handling.

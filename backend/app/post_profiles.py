"""
POST (2026-09-25, Phase 1) -- hardcoded per-profile folder-structure
templates, deliberately NOT a DB-backed template editor. Matches this
codebase's existing "vocabulary as a module-level Python constant"
convention (VENTURE_STATUSES, PROJECT_STATUS_VALUES, etc. are all
"configurable" only in the sense of "edit the code," treated as
sufficient everywhere else). A DB-backed editor implies real added
scope (its own CRUD UI, a retroactive-template-change story for jobs
already created against an older version) that nothing in Josh's own
POST spec names as a feature.

Folder lists are taken verbatim from Josh's own spec, not invented.
Joshx's tree sits directly under the project root; Alpha Mode's tree
nests under CLIENT/PROJECT/ first -- genuinely different depth, not
just different names, so `compute_destination_root` handles the nesting
decision separately from the flat `folders` list.
"""

from pathlib import Path

POST_PROFILES: dict[str, dict] = {
    "joshx": {
        "label": "Joshx",
        "folders": [
            "01_PROJECT",
            "02_FOOTAGE/CAMERA A",
            "02_FOOTAGE/CAMERA B",
            "02_FOOTAGE/DRONE",
            "02_FOOTAGE/PHONE",
            "02_FOOTAGE/OTHER",
            "03_AUDIO",
            "04_MUSIC",
            "05_GRAPHICS",
            "06_STILLS",
            "07_PROXIES",
            "08_EXPORTS/PREVIEWS",
            "08_EXPORTS/CLIENT REVIEW",
            "08_EXPORTS/FINAL",
            "09_PROJECT FILES",
            "10_ARCHIVE",
        ],
    },
    "alpha_mode": {
        "label": "Alpha Mode",
        "folders": [
            "01_ADMIN",
            "02_PROJECT",
            "03_FOOTAGE/A_CAM",
            "03_FOOTAGE/B_CAM",
            "03_FOOTAGE/C_CAM",
            "03_FOOTAGE/DRONE",
            "03_FOOTAGE/GOPRO",
            "03_FOOTAGE/PHONE",
            "04_AUDIO",
            "05_STILLS",
            "06_GRAPHICS",
            "07_MUSIC",
            "08_SFX",
            "09_PROXIES",
            "10_PREMIERE",
            "11_EXPORTS",
            "12_CLIENT_REVIEW",
            "13_ARCHIVE",
        ],
    },
}


def compute_destination_root(profile: str, destination_volume_path: str, client_name: str | None, shoot_name: str) -> Path:
    """Alpha Mode nests under CLIENT/PROJECT/; Joshx sits directly under
    the destination root -- a real structural difference, not just a
    naming one, confirmed from Josh's own two example trees."""
    if profile == "alpha_mode":
        if not client_name:
            raise ValueError("alpha_mode profile requires a client_name")
        return Path(destination_volume_path) / client_name / shoot_name
    return Path(destination_volume_path) / shoot_name


def build_project_structure(profile: str, destination_root: Path) -> list[Path]:
    """Creates every folder in the profile's template under
    destination_root. Idempotent (exist_ok=True) so re-running a
    resumed/retried scan never fails on folders already created by a
    prior attempt."""
    created: list[Path] = []
    for relative in POST_PROFILES[profile]["folders"]:
        folder = destination_root / relative
        folder.mkdir(parents=True, exist_ok=True)
        created.append(folder)
    return created

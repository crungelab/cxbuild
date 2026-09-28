from typing import Any
import os
from enum import Enum
from pathlib import Path
import json

import pydantic

from .runner import CxBuildError


class BuildMode(str, Enum):
    DEBUG = 'DEBUG'
    RELEASE = 'RELEASE'
    PROFILE = 'PROFILE'


class ActivityType(str, Enum):
    ConfigureActivity = 'ConfigureActivity'
    BuildActivity = 'BuildActivity'
    DevelopActivity = 'DevelopActivity'
    InstallActivity = 'InstallActivity'


class Activity(pydantic.BaseModel):
    type: ActivityType = None
    # Factories, not values: Path.cwd() as a plain default is evaluated once, at import.
    root: Path = pydantic.Field(default_factory=Path.cwd)
    path: Path = pydantic.Field(default_factory=lambda: Path.cwd() / '_cxbuild/activity.json')
    mode: BuildMode = BuildMode.RELEASE

    def __new__(cls, *args, **kwargs):
        global _activity
        _activity = super(Activity, cls).__new__(cls)
        return _activity

    @property
    def artifacts_dir(self):
        return self.root / '_cxbuild/artifacts'

    # Note:  I'm tempted to serialize to the environment itself instead of a file ...
    def save(self):
        """Write the activity to its JSON file and point CBX_ACTIVITY at it, for the build hooks."""
        os.environ['CBX_ACTIVITY'] = str(self.path)
        with open(self.path, 'w') as f:
            json.dump({'type': self.type.value, 'object': self.model_dump_json()}, f)
        return self

_activity: Activity = None


class ConfigureActivity(Activity):
    type: ActivityType = ActivityType.ConfigureActivity


class BuildActivity(Activity):
    type: ActivityType = ActivityType.BuildActivity

class DevelopActivity(Activity):
    type: ActivityType = ActivityType.DevelopActivity
    mode: BuildMode = BuildMode.DEBUG


class InstallActivity(Activity):
    type: ActivityType = ActivityType.InstallActivity


ACTIVITY_CLASSES: dict[str, type[Activity]] = {
    cls.__name__: cls for cls in (ConfigureActivity, BuildActivity, DevelopActivity, InstallActivity)
}


def deserialize_activity(path: Path):
    """Deserialize an activity from a JSON file"""
    with open(path, "r") as f:
        data = json.load(f)
    cls = ACTIVITY_CLASSES.get(data["type"])
    if cls is None:
        raise CxBuildError(f"invalid activity type {data['type']!r} in {path}")
    return cls.model_validate_json(data["object"])


def get_activity() -> Activity:
    global _activity
    if _activity:
        return _activity
    location = os.environ.get("CBX_ACTIVITY")
    if not location:
        # The backend only packages what a cxbuild run already built with cmake.
        raise CxBuildError(
            "no cxbuild activity: CBX_ACTIVITY is not set. This backend packages artifacts "
            "built by the cxbuild CLI; run `cxbuild develop` (or build) from the solution root."
        )
    return deserialize_activity(Path(location))
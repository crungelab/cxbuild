from typing import Any
import os
from enum import Enum
from pathlib import Path
import json

import pydantic


class BuildMode(str, Enum):
    DEBUG = 'DEBUG'
    RELEASE = 'RELEASE'
    PROFILE = 'PROFILE'


class ActivityType(str, Enum):
    ConfigureActivity = 'ConfigureActivity'
    BuildActivity = 'BuildActivity'
    DevelopActivity = 'DevelopActivity'


class Activity(pydantic.BaseModel):
    type: ActivityType = None
    root: Path = Path.cwd()
    path: Path = Path.cwd() / '_cxbuild/activity.json'
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
        os.environ['CBX_ACTIVITY'] = str(self.path)
        """Serialize an activity to a JSON string"""
        with open(self.path, 'w') as f:
            json.dump({'type': self.type.value, 'object': self.json()}, f)

_activity: Activity = None


class ConfigureActivity(Activity):
    type: ActivityType = ActivityType.ConfigureActivity


class BuildActivity(Activity):
    type: ActivityType = ActivityType.BuildActivity


class DevelopActivity(Activity):
    type: ActivityType = ActivityType.DevelopActivity
    mode: BuildMode = BuildMode.DEBUG


def deserialize_activity(path: Path):
    """Deserialize an activity from a JSON file"""
    with open(path, "r") as f:
        data = json.load(f)

    if data["type"] == ActivityType.ConfigureActivity.value:
        return ConfigureActivity.parse_raw(data["object"])
    elif data["type"] == ActivityType.BuildActivity.value:
        return BuildActivity.parse_raw(data["object"])
    elif data["type"] == ActivityType.DevelopActivity.value:
        return DevelopActivity.parse_raw(data["object"])
    else:
        raise ValueError("Invalid type")


def get_activity() -> Activity:
    global _activity
    if _activity:
        return _activity
    path = Path(os.environ["CBX_ACTIVITY"])
    return deserialize_activity(path)

from typing import Any
import os
from enum import Enum
from pathlib import Path
import json

import pydantic


class BuildMode(Enum):
    DEBUG = 1
    RELEASE = 2
    PROFILE = 3


class ActivityType(str, Enum):
    BuildActivity = "BuildActivity"
    DevelopActivity = "DevelopActivity"


class Activity(pydantic.BaseModel):
    type: ActivityType = None
    root: Path = Path.cwd()
    path: Path = Path.cwd() / "_cxbuild/activity.json"
    mode: BuildMode = BuildMode.RELEASE

    @property
    def artifacts_dir(self):
        return self.root / "_cxbuild/artifacts"

    def commit(self):
        """Serialize an activity to a JSON string"""
        with open(self.path, "w") as f:
            json.dump({"type": self.type.value, "object": self.json()}, f)

    def make_environ(self):
        os.environ["CBX_ACTIVITY"] = str(self.path)
        environ = os.environ.copy()
        return environ


class BuildActivity(Activity):
    type: ActivityType = ActivityType.BuildActivity


class DevelopActivity(Activity):
    type: ActivityType = ActivityType.DevelopActivity


def deserialize_activity(path: Path):
    """Deserialize an activity from a JSON file"""
    with open(path, "r") as f:
        data = json.load(f)

    if data["type"] == ActivityType.BuildActivity.value:
        return BuildActivity.parse_raw(data["object"])
    elif data["type"] == ActivityType.DevelopActivity.value:
        return DevelopActivity.parse_raw(data["object"])
    else:
        raise ValueError("Invalid type")


_activity: Activity = None


def get_activity() -> Activity:
    global _activity
    if _activity:
        return _activity
    path = Path(os.environ["CBX_ACTIVITY"])
    activity = deserialize_activity(path)
    _activity = activity
    return activity

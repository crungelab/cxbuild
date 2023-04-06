from pathlib import Path
import tomli

class Config:
    def __init__(self, config) -> None:
        self.config = config
        for key, value in config.items():
            if isinstance(value, dict):
                value = Config(value)
            setattr(self, key, value)

class PyProject(Config):
    def __init__(self, config) -> None:
        super().__init__(config)

    @classmethod
    def load(cls, path: Path):
        path = path / 'pyproject.toml'
        with open(path, "rb") as f:
            config = tomli.load(f)
            return PyProject(config)

    """
    @property
    def project(self):
        return self.config["project"]

    @property
    def tool(self):
        return self.config["tool"]
    """
    @property
    def name(self):
        #return self.project["name"]
        return self.project.name

import shutil
import site
import importlib
import tomllib
from pathlib import Path

from loguru import logger

from .cmake_tool import CMakeConfig, CMakeTool

from .activity import (
    get_activity,
    BuildMode,
    Activity,
    ConfigureActivity,
    BuildActivity,
    DevelopActivity,
    InstallActivity,
)
from .project_base import ProjectBase
from .project import Project
from .runner import CxBuildError, Runner


def is_glob(s):
    return any(char in s for char in "*?[]")


def find_solution_root(start: Path) -> Path:
    """The nearest directory, from `start` upward, whose pyproject.toml lists cxbuild projects.

    Lets cxbuild run from anywhere inside a solution: the root itself, a project
    directory, or a directory within a project. Plain TOML is read, not the full
    model, so an unrelated pyproject.toml on the way up can't stop the search.
    """
    start = Path(start).resolve()
    for directory in (start, *start.parents):
        file = directory / "pyproject.toml"
        if not file.is_file():
            continue
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if data.get("tool", {}).get("cxbuild", {}).get("projects"):
            return directory
    raise CxBuildError(f"not inside a cxbuild solution: no pyproject.toml with [tool.cxbuild] projects above {start}")


class Solution(ProjectBase):
    def __init__(self, path: Path, runner: Runner) -> None:
        path = Path(path).resolve()
        super().__init__(path)
        logger.debug(f"solution path: {path}")
        self.runner = runner
        self.build_root = path / "_cxbuild"
        self.ensure()
        self.projects: list[Project] = []
        self.project_map: dict[str, Project] = {}
        self.create_projects()

    def project_containing(self, path: Path) -> Project | None:
        """The project whose directory is `path` or contains it."""
        path = Path(path).resolve()
        for project in self.projects:
            if path == project.path or project.path in path.parents:
                return project
        return None

    def activity(self, kind: type[Activity]) -> Activity:
        """A saved activity rooted at the solution, wherever cxbuild was started from."""
        return kind(root=self.path, path=self.build_root / "activity.json").save()

    def select_projects(self, project_name: str = None):
        if project_name:
            project = self.project_map.get(project_name)
            if project:
                return [project]
            else:
                known = ", ".join(self.project_map) or "none"
                raise CxBuildError(f"project not found: {project_name} (projects: {known})")
        else:
            return self.projects

    def ensure(self):
        if not self.build_root.exists():
            self.build_root.mkdir()

    def create_projects(self):
        if not hasattr(self.pyproject.tool.cxbuild, "projects"):
            return
        project_globs = self.pyproject.tool.cxbuild.projects
        logger.debug(f"project_globs: {project_globs}")
        project_paths = []
        for glob in project_globs:
            if is_glob(glob):
                project_paths += sorted(p.resolve() for p in self.path.glob(glob))
            else:
                project_paths.append((self.path / glob).resolve())
        logger.debug(f"project_paths: {project_paths}")
        for project_path in project_paths:
            self.add_project(Project(project_path, self.runner))

    def add_project(self, project: Project):
        logger.debug(f"add_project: {project}")
        self.projects.append(project)
        self.project_map[project.name] = project

    def create_config(self, activity: Activity):
        prefix_dirs = []
        site_packages = site.getsitepackages()
        logger.debug(f"site_packages: {site_packages}")
        for site_package in site_packages:
            prefix_dirs.append(Path(site_package))

        if hasattr(self.pyproject.tool.cxbuild, "plugins"):
            plugins = self.pyproject.tool.cxbuild.plugins
            logger.debug(f"plugins: {plugins}")
            for plugin in plugins:
                plugin_module = importlib.import_module(plugin)
                logger.debug(f"plugin_module: {plugin_module}")
                plugin_prefix = Path(plugin_module.__file__).parent.parent
                logger.debug(f"plugin_prefix: {plugin_prefix}")
                prefix_dirs.append(plugin_prefix)

        logger.debug(f"prefix_dirs: {prefix_dirs}")
        build_type = "Release"
        # build_type = 'Debug'

        # TODO:  This is chicken&egg, find a better solution
        if activity.mode == BuildMode.DEBUG:
            build_type = "Debug"

        logger.info(f"Configuring in {build_type} mode")
        config = CMakeConfig(
            source_dir=self.path,
            build_dir=self.build_root / "build",
            build_type=build_type,
            generator=None,
            prefix_dirs=prefix_dirs,
            install_dir=activity.artifacts_dir,
        )
        return config

    def create_tool(self, activity: Activity) -> CMakeTool:
        return CMakeTool(self.create_config(activity), self.runner)

    def clean(self):
        logger.info("clean")
        for project in self.projects:
            project.clean()
        dist_dir = self.path / "dist"
        if dist_dir.exists():
            logger.debug(f"removing {dist_dir}")
            shutil.rmtree(dist_dir)
        """
        if activity.mode == BuildMode.DEBUG:
            build_dir = self.path / '_cxbuild/build'
            if build_dir.exists():
                logger.debug(f"removing {build_dir}")
                shutil.rmtree(build_dir)
        """

    def configure(self):
        logger.info("configure")
        activity = self.activity(ConfigureActivity)
        self.runner.expect(1)
        tool = self.create_tool(activity)
        tool.configure()

    def develop(self, project_name: str = None):
        logger.info("develop")
        activity = self.activity(DevelopActivity)
        # Fail on an unknown project or a bad pyproject.toml before a long cmake build, not after.
        builders = [(p, p.wheel_builder(activity.artifacts_dir)) for p in self.select_projects(project_name)]
        self.runner.expect(3 + len(builders))  # configure, build, install, then pip per project

        tool = self.create_tool(activity)
        tool.configure()
        tool.build()
        tool.install()

        for project, builder in builders:
            project.develop(builder)

    def build(self) -> list[Path]:
        """cmake once for the solution, then one wheel per project into <solution>/dist."""
        logger.info("build")
        activity = self.activity(BuildActivity)
        # Fail on a bad pyproject.toml (readme, license files) before a long cmake build, not after.
        builders = [(p, p.wheel_builder(activity.artifacts_dir)) for p in self.projects]
        self.runner.expect(3 + len(builders))  # configure, build, install, then a wheel per project

        tool = self.create_tool(activity)
        tool.configure()
        tool.build()
        tool.install()

        return [project.write_wheel(builder, self.path / "dist") for project, builder in builders]

    def install(self):
        logger.info("install")
        activity = self.activity(InstallActivity)
        self.runner.expect(1)
        tool = self.create_tool(activity)
        tool.install()

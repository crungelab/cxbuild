import os
import site
import importlib
from pathlib import Path

from .cmake_tool import CMakeConfig, CMakeTool

from .activity import BuildActivity, DevelopActivity
from .project_base import ProjectBase
from .project import Project

def is_glob(s):
    return any(char in s for char in '*?[]')

class Solution(ProjectBase):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        print(path)
        self.projects: list[Project] = []
        self.create_projects()

    def create_projects(self):
        if not hasattr(self.pyproject.tool.cxbuild, 'projects'):
            return
        project_globs = self.pyproject.tool.cxbuild.projects
        print(project_globs)
        project_paths = []
        for glob in project_globs:
            if is_glob(glob):
                project_paths += list(self.path.glob(glob))
            else:
                project_paths.append(self.path / glob)
        print(project_paths)
        for project_path in project_paths:
            self.add_project(Project(project_path))

    def add_project(self, project: Project):
        self.projects.append(project)

    def create_config(self):
        prefix_dirs = []
        site_packages = site.getsitepackages()
        print('site_packages', site_packages)
        for site_package in site_packages:
            prefix_dirs.append(Path(site_package))

        if hasattr(self.pyproject.tool.cxbuild, 'plugins'):
            plugins = self.pyproject.tool.cxbuild.plugins
            print('plugins: ', plugins)
            for plugin in plugins:
                plugin_module = importlib.import_module(plugin)
                print('plugin_module: ', plugin_module)
                plugin_prefix = Path(plugin_module.__file__).parent.parent
                print('plugin_prefix: ', plugin_prefix)
                prefix_dirs.append(plugin_prefix)
                
        print('prefix_dirs: ', prefix_dirs)
        config = CMakeConfig(source_dir=Path('.'), build_dir=Path('_cxbuild/build'), build_type='Release', generator=None, prefix_dirs=prefix_dirs)
        return config
    
    def configure(self):
        print('configure')
        config = self.create_config()
        tool = CMakeTool(config)
        tool.configure()

    def develop(self):
        print('develop')
        config = self.create_config()
        tool = CMakeTool(config)
        tool.build()
        tool.install()

        activity = DevelopActivity()
        activity.commit()

        for project in self.projects:
            project.develop(activity.make_environ())

    def build(self):
        print('build')
        config = self.create_config()
        tool = CMakeTool(config)
        tool.build()
        tool.install()

        activity = BuildActivity()
        activity.commit()

        for project in self.projects:
            project.build(activity.make_environ())

    def install(self):
        print('install')
        config = self.create_config()
        tool = CMakeTool(config)
        tool.install()

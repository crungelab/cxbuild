import os
import site
import importlib
from pathlib import Path

from .cmake_tool import CMakeConfig, CMakeTool

from .project_base import ProjectBase
from .project import Project


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
            project_paths += list(self.path.glob(glob))
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
            prefix_dirs += Path(site_package).as_posix() #TODO: this is returning a string.  Convert to posix

        if hasattr(self.pyproject.tool.cxbuild, 'plugins'):
            plugins = self.pyproject.tool.cxbuild.plugins
            print('plugins: ', plugins)
            for plugin in plugins:
                plugin_module = importlib.import_module(plugin)
                print('plugin_module: ', plugin_module)
                plugin_prefix = Path(plugin_module.__file__).parent.parent.as_posix()
                print('plugin_prefix: ', plugin_prefix)
                prefix_dirs += plugin_prefix
        #exit()
        config = CMakeConfig(source_dir=Path('.'), build_dir=Path('_cxbuild'), build_type='Release', generator=None, prefix_dirs=prefix_dirs)
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

        env = os.environ.copy()
        env["CX_INSTALL_DIR"] = str(self.path / '_cxinstall')

        for project in self.projects:
            project.develop(env)

    def build(self):
        print('build')
        config = self.create_config()
        tool = CMakeTool(config)
        tool.build()
        tool.install()
        
        env = os.environ.copy()
        env["ROOT_DIR"] = str(self.path)
        env["CX_INSTALL_DIR"] = str(self.path / '_cxinstall')

        for project in self.projects:
            """
            cxbuild_path = self.path / 'pkg' / 'cxbuild'
            requirements = [
                #str(cxbuild_path.resolve()),
                str(cxbuild_path),
            ]
            project.write_requirements(requirements)
            """
            project.build(env)

    def install(self):
        print('install')
        config = self.create_config()
        tool = CMakeTool(config)
        tool.install()

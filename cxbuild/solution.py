import site
import importlib
from pathlib import Path

from loguru import logger

from .cmake_tool import CMakeConfig, CMakeTool

from .activity import get_activity, BuildMode, ConfigureActivity, BuildActivity, DevelopActivity
from .project_base import ProjectBase
from .project import Project

def is_glob(s):
    return any(char in s for char in '*?[]')

class Solution(ProjectBase):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        logger.debug(path)
        self.build_root = path / '_cxbuild'
        self.ensure()
        self.projects: list[Project] = []
        self.create_projects()

    def ensure(self):
        if not self.build_root.exists():
            self.build_root.mkdir()

    def create_projects(self):
        if not hasattr(self.pyproject.tool.cxbuild, 'projects'):
            return
        project_globs = self.pyproject.tool.cxbuild.projects
        logger.debug(project_globs)
        project_paths = []
        for glob in project_globs:
            if is_glob(glob):
                project_paths += list(self.path.glob(glob))
            else:
                project_paths.append(self.path / glob)
        logger.debug(project_paths)
        for project_path in project_paths:
            self.add_project(Project(project_path))

    def add_project(self, project: Project):
        self.projects.append(project)

    def create_config(self):
        prefix_dirs = []
        site_packages = site.getsitepackages()
        logger.debug('site_packages', site_packages)
        for site_package in site_packages:
            prefix_dirs.append(Path(site_package))

        if hasattr(self.pyproject.tool.cxbuild, 'plugins'):
            plugins = self.pyproject.tool.cxbuild.plugins
            logger.debug('plugins: ', plugins)
            for plugin in plugins:
                plugin_module = importlib.import_module(plugin)
                logger.debug('plugin_module: ', plugin_module)
                plugin_prefix = Path(plugin_module.__file__).parent.parent
                logger.debug('plugin_prefix: ', plugin_prefix)
                prefix_dirs.append(plugin_prefix)
                
        logger.debug('prefix_dirs: ', prefix_dirs)
        #build_type = 'Release'
        build_type = 'Debug'

        # TODO:  This is chicken&egg, find a better solution
        """
        activity = get_activity()
        if activity.mode == BuildMode.DEBUG:
            build_type = 'Debug'
        """
        logger.info(f'Configuring in {build_type} mode')
        config = CMakeConfig(source_dir=Path('.'), build_dir=Path('_cxbuild/build'), build_type=build_type, generator=None, prefix_dirs=prefix_dirs)
        return config
    
    def configure(self):
        logger.info('configure')
        ConfigureActivity().save()
        config = self.create_config()
        tool = CMakeTool(config)
        tool.configure()

    def develop(self):
        logger.info('develop')
        DevelopActivity().save()
        
        config = self.create_config()
        tool = CMakeTool(config)
        tool.build()
        tool.install()

        for project in self.projects:
            project.develop()

    def build(self):
        logger.info('build')
        BuildActivity().save()

        config = self.create_config()
        tool = CMakeTool(config)
        tool.build()
        tool.install()

        for project in self.projects:
            project.build()

    def install(self):
        logger.info('install')
        config = self.create_config()
        tool = CMakeTool(config)
        tool.install()

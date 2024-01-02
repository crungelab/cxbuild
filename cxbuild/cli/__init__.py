import click
from click import Context

from ..cxbuild import CxBuild

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        build()


@cli.command()
@click.pass_context
def clean(ctx: Context):
    builder = CxBuild()
    builder.clean()

@cli.command()
@click.pass_context
def configure(ctx: Context):
    builder = CxBuild()
    builder.configure()

@cli.command()
@click.pass_context
@click.argument("project_name", required=False)
def develop(ctx: Context, project_name: str):
    builder = CxBuild()
    builder.develop(project_name)

@cli.command()
@click.pass_context
def build(ctx: Context):
    builder = CxBuild()
    builder.clean()
    builder.build()

@cli.command()
@click.pass_context
def install(ctx: Context):
    builder = CxBuild()
    builder.install()

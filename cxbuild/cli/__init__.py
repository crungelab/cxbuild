import os
import importlib.util
from pathlib import Path

import click

from ..cxbuild import CxBuild

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        build()


@cli.command()
@click.pass_context
def configure(ctx):
    builder = CxBuild()
    builder.configure()

@cli.command()
@click.pass_context
def develop(ctx):
    builder = CxBuild()
    builder.develop()

@cli.command()
@click.pass_context
def build(ctx):
    builder = CxBuild()
    builder.build()

@cli.command()
@click.pass_context
def install(ctx):
    builder = CxBuild()
    builder.install()

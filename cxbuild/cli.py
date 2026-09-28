from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import click
from click import Context

from .console import console
from .cxbuild import CxBuild
from .logsetup import configure_logging
from .runner import BuildStepError, CxBuildError, Runner


@contextmanager
def session(ctx: Context, label: str) -> Iterator[CxBuild]:
    """Log and report one CLI command. The only place cxbuild turns errors into an exit code."""
    root = Path.cwd()
    os.environ["CXBUILD_ROOT"] = str(root.resolve())  # hooks run by pip put their reports beside ours
    configure_logging(root)
    try:
        with Runner(root, label, verbose=ctx.obj["verbose"]) as runner:
            yield CxBuild(runner)
    except CxBuildError as e:
        if not isinstance(e, BuildStepError):  # the runner already printed those
            console.print(f"[red]cxbuild: {e}[/]")
        ctx.exit(1)
    # Anything else is a bug: it propagates with its traceback, which the report also has.


@click.group(invoke_without_command=True)
@click.option("-v", "--verbose", is_flag=True, help="Stream command output to the terminal.")
@click.pass_context
def cli(ctx: Context, verbose: bool):
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    if verbose:
        os.environ["CXBUILD_VERBOSE"] = "1"  # inherited by the hooks when we run pip
    if ctx.invoked_subcommand is None:
        ctx.invoke(build)


@cli.command()
@click.pass_context
def clean(ctx: Context):
    with session(ctx, "clean") as builder:
        builder.clean()


@cli.command()
@click.pass_context
def configure(ctx: Context):
    with session(ctx, "configure") as builder:
        builder.configure()


@cli.command()
@click.pass_context
@click.argument("project_name", required=False)
def develop(ctx: Context, project_name: str):
    with session(ctx, "develop") as builder:
        builder.develop(project_name)


@cli.command()
@click.pass_context
def build(ctx: Context):
    with session(ctx, "build") as builder:
        builder.clean()
        builder.build()


@cli.command()
@click.pass_context
def install(ctx: Context):
    with session(ctx, "install") as builder:
        builder.install()

from __future__ import annotations

import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

import click
from click import Context

from .console import console
from .cxbuild import CxBuild
from .logsetup import configure_logging
from .runner import BuildStepError, CxBuildError, Runner
from .solution import find_solution_root


@contextmanager
def session(ctx: Context, label: str) -> Generator[CxBuild, None, None]:
    """Log and report one CLI command. The only place cxbuild turns errors into an exit code."""
    start = Path.cwd()
    try:
        root = find_solution_root(start)  # cxbuild runs from anywhere inside the solution
    except CxBuildError as e:
        console.print(f"[red]cxbuild: {e}[/]")
        ctx.exit(1)

    os.environ["CXBUILD_ROOT"] = str(root)  # hooks run by pip put their reports beside ours
    configure_logging(root)

    try:
        with Runner(root, label, verbose=ctx.obj["verbose"]) as runner:
            yield CxBuild(runner, root, start)
    except CxBuildError as e:
        if not isinstance(e, BuildStepError):  # the runner already printed those
            console.print(f"[red]cxbuild: {e}[/]")
        ctx.exit(1)
    # Anything else is a bug: it propagates with its traceback, which the report also has.


@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Stream command output to the terminal.")
@click.pass_context
def cli(ctx: Context, verbose: bool) -> None:
    """Build the cmake projects of a cxbuild solution. With no command, runs develop."""
    ctx.obj = {"verbose": verbose}
    if verbose:
        os.environ["CXBUILD_VERBOSE"] = "1"  # inherited by the hooks when we run pip
    if ctx.invoked_subcommand is None:
        ctx.invoke(develop)


def command(fn: Callable[..., None]) -> click.Command:
    """Register fn as a cxbuild command that runs inside a session.

    fn takes the CxBuild first, then any click parameters declared beneath @command.
    The command's name and help text come from fn's name and docstring.
    """

    @cli.command(name=fn.__name__)
    @click.pass_context
    @wraps(fn)  # carries over __doc__ and the click params stacked on fn
    def wrapper(ctx: Context, **params) -> None:
        with session(ctx, fn.__name__) as builder:
            fn(builder, **params)

    return wrapper


@command
@click.argument("project_name", required=False)
def develop(builder: CxBuild, project_name: str | None) -> None:
    """Build and install editable, copying binaries into the source tree (the default)."""
    builder.develop(project_name)


@command
def configure(builder: CxBuild) -> None:
    """Run cmake configure."""
    builder.configure()


@command
def build(builder: CxBuild) -> None:
    """Clean, then build wheels."""
    builder.clean()
    builder.build()


@command
def install(builder: CxBuild) -> None:
    """Build and install."""
    builder.install()


@command
def clean(builder: CxBuild) -> None:
    """Remove build output."""
    builder.clean()
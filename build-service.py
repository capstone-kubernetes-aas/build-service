#!/usr/bin/env python3

"""
KaaS Repo Build Script

Usage:
    build-service [-v] <repo-url> [--config=<path/to/config.yml>]

Options:
    -h --help         Show this help message
    -c --config=FILE  Path to config file (default: <repo>/kaas.yml)
    -v --verbose      Show more output
"""

from git import Repo
from docopt import docopt
import docker
import tempfile
import yaml
import logging

dclient = docker.from_env()


def build_repo(repo, config_file):
    # do work in temp dir
    with tempfile.TemporaryDirectory() as repo_dir:

        logging.info(f"cloning repo {repo} to {repo_dir}")
        repo = Repo.clone_from(repo, repo_dir)

        # parse options from config -- default to repo/kaas.yml
        if config_file is None:
            # this doesn't use docopt's defaults mechanism since we can't
            # calculate the default until we make the tempdir in this function
            config_file = f"{repo_dir}/kaas.yml"
            logging.info(f"using default config file location: {config_file}")

        # load file
        with open(config_file, "r") as f:
            config = yaml.load(f, Loader=yaml.Loader)

        dclient.images.build(path=repo_dir, tag=config["metadata"]["labels"]["app"])


if __name__ == "__main__":
    args = docopt(__doc__)

    if args["--verbose"]:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.WARN

    logging.basicConfig(format='%(name)s - %(levelname)s - %(message)s', level=loglevel)

    logging.debug(args)

    build_repo(args["<repo-url>"], args["--config"])

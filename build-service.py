#!/usr/bin/env python3

"""
KaaS Repo Build Script

Usage:
    build-service [-v] <repo-url> [--branch=<branch>] [--config=<path/to/config.yml>]
    build-service [-v] --daemon [--port=<port>]

Options:
    -h --help           Show this help message
    -v --verbose        Show verbose/debug output
    -b --branch=BRANCH  Branch/tag to checkout repo to [default: main]
    -c --config=FILE    Path to config file, if not at /kaas.yml in repo
    -d --daemon         Run in the background and listen for connections
    -p --port=PORT      Port to listen for connections on [default: 8800]
"""

import json
import logging
import tempfile

import docker
import yaml
from docopt import docopt
from flask import Flask, request
from git import Repo, exc

app = Flask(__name__)
dclient = docker.from_env()


# custom exceptions
class MissingConfigFile(FileNotFoundError):
    """Raised when a config file is not found in the supplied repo"""

    def __init__(self, message="config file not found in repo or specified in request"):
        self.message = message
        super().__init__(self.message)


def build_repo(repo, branch, config):
    # do work in temp dir
    with tempfile.TemporaryDirectory(prefix="kaas-repo-build-") as repo_dir:

        logging.info(f"cloning repo {repo} to {repo_dir}")
        # add empty creds to clone url
        repo = Repo.clone_from(repo, repo_dir)

        if branch is not None:
            repo.git.checkout(branch)

        # parse options from default config ($REPO/kaas.yml) if none given
        if config is None:
            # this doesn't use docopt's defaults mechanism since we can't
            # calculate the default until we make the tempdir in this function
            config_file = f"{repo_dir}/kaas.yml"
            logging.info(f"using default config file location: {config_file}")

            # load file
            try:
                with open(config_file, "r") as f:
                    config = yaml.load(f, Loader=yaml.Loader)
            except FileNotFoundError:
                raise MissingConfigFile from FileNotFoundError

        dclient.images.build(path=repo_dir, tag=config["metadata"]["labels"]["app"])

    # return label of build image
    return config["metadata"]["labels"]["app"]


# site.com/build: JSON API to start new build
# request structure:
# {
#     "repo_url": "https://the.repo/url",
#     "repo_branch": null || "thebranch"
#     "config": null || "valid json string" || { valid json object }
# }
@app.route("/build", methods=["POST"])
def build_request():
    reqj = request.get_json()

    logging.debug(f"request: {reqj}")

    if not ("repo_url" in reqj and "repo_branch" in reqj and "config" in reqj):
        logging.error("missing keys")
        return {"err": "Bad request: missing keys"}, 400

    # accepts json as string or as part of request json
    config = reqj["config"]
    try:
        if config is not None and not isinstance(config, dict):
            config = json.loads(config)
    except Exception:
        logging.error("malformed config payload")
        return {"err": "Bad request: malformed config payload"}, 400

    try:
        image_name = build_repo(reqj["repo_url"], reqj['repo_branch'], config)
    except exc.GitCommandError:
        logging.error(f"failed to build: branch {config} does not exist")
        return {"err": f"Failed to build: branch {config} does not exist"}, 500
    except Exception as e:
        logging.error(f"failed to build: {str(e)}")
        return {"err": f"Failed to build: {str(e)}"}, 500

    return {"image": image_name}


if __name__ == "__main__":
    args = docopt(__doc__)

    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        level=logging.DEBUG if args["--verbose"] else logging.WARN,
    )

    logging.debug(f"args: {args}")

    # run as daemon and listen for build requests on --port
    if args["--daemon"]:
        app.run(host="0.0.0.0", port=args["--port"], debug=args["--verbose"])
        exit(0)

    # load config from custom file if specified
    config = None
    if args["--config"] is not None:
        # this doesn't use docopt's defaults mechanism since we can't
        # calculate the default until the clone function makes the repo tempdir
        logging.info(f"using custom config file location: {args['--config']}")

        # load file
        try:
            with open(args["--config"], "r") as f:
                config = yaml.load(f, Loader=yaml.Loader)
        except FileNotFoundError:
            logging.error("Cannot open config file")
            exit(1)

    try:
        image_name = build_repo(args["<repo-url>"], args["--branch"], config)
    except exc.GitCommandError:
        logging.error(f"Error building repo: branch '{args['--branch']}' does not exist")
        exit(1)
    except Exception as e:
        logging.error(f"Error building repo: {e}")
        exit(1)

    print(f"Repository built successfully as '{image_name}'")

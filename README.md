# build-service

This script accepts a repo, branch, and config file and builds the corresponding Docker image.

The build service works as both a command line tool, and as a daemon.

Both the CLI and daemon take in a repository URL, and optional custom config file location. If no config is specified,
it will look for `/kaas.yml` in the repository.

The repo must be public and must contain a Dockerfile at `/Dockerfile`.

## Installation

Install dependencies with [Pipenv](https://github.com/pypa/pipenv):

```sh
pipenv install  # install deps from Pipfile
pipenv shell    # activate project venv
```

## Usage

See the [documentation](documentation/build-service.md).

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

## CLI Usage

See `-h`:

```
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
```

## Daemon usage

Start the script with `--daemon`. By default, this listens on port `8800`.

Make a `POST` request to `<host>:8800/build` with the following JSON content:

```sh
python build-service.py --daemon &
curl --header "Content-Type: application/json" --request POST --data '{"repo_url": "https://site.com/some-repo", "repo_branch": "null", "config": null}' localhost:8800/build
```

```jsonc
{
  "repo_url": "https://the.repo",
  "repo_branch": null || "thebranch",
  // ONE of the following
  "config": null,   // to use repo config
  "config": { /* JSON of custom config */ },
  "config": "{ JSON string of custom config }",
}
```

The daemon will return the name of the build image on success, or an error message and description:

```jsonc
200 {"image": "<image-name>"}

400 {"err": "Bad request: missing keys"}
400 {"err": "Bad request: malformed config payload"}

500 {"err": "Failed to build: <build error>"}
```

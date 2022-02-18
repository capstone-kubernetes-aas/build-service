# Build Daemon Documentation

The build service works as both a command line tool, and as a daemon.

Both the CLI and daemon take in a repository URL, and optional custom config
file location. If no config is specified, it will look for `/kaas.yml` in the
repository.

The repo must be public and must contain a Dockerfile at `/Dockerfile`.

## CLI Usage

See `-h`:

```
KaaS Repo Build Script

Usage:
    build-service [-v | -vv] <repo-url> [--branch=<branch>]
                  [--deploy-conf=<path/to/deploy.yml>] [--service-conf=<path/to/service.yml>]
    build-service [-v | -vv] --daemon [--port=<port>]

CLI Options:
    -h --help               Show this help message
    -v --verbose            Show verbose/debug output. More v's for more verbosity.
    -b --branch=BRANCH      Branch/tag to checkout repo to [default: main]
    -c --deploy-conf=FILE   Path to config file in repo, if not at /kaas.deploy.yml
    -s --service-conf=FILE  Path to config file in repo, if not at /kaas.service.yml

Daemon Options:
    -d --daemon             Run in the background and listen for connections
    -p --port=PORT          Port to listen for connections on [default: 8800]
```

## Daemon usage

Start the script with `--daemon`. By default, this listens on port `8800`.

Make a `POST` request to `<host>:8800/build` with the following JSON content:

```jsonc
{
  "repo_url": "https://the.repo",
  "repo_branch": null || "thebranch",

  // ONE of the following
  "deploy_config": null,  // use default path
  "deploy_config": "path/to/deploy.yml",
  "deploy_config": { /* custom JSON config object */ },

   // ONE of the following
  "service_config": null,  // use default path
  "service_config": "path/to/deploy.yml",
  "service_config": { /* custom JSON config object */ },
}
```

The daemon will return the name of the build image on success, or an error
message and description:

```jsonc
200 {"image": "<image-name>"}

400 {"err": "Bad request: missing keys"}
400 {"err": "Bad request: malformed config payload"}

500 {"err": "Failed to build: <build error>"}
```

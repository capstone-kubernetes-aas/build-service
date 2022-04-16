#!/usr/bin/env python3

"""
KaaS Repo Build Script

Usage:
    build-service [-v | -vv] <repo-url> [--branch=<branch>]
                  [--deploy-conf=<path/to/deploy.yml>] [--service-conf=<path/to/service.yml>]
                  [--restart=<image_name> | --delete=<image_name>]
    build-service [-v | -vv] --daemon [--port=<port>]

CLI Options:
    -h --help               Show this help message
    -v --verbose            Show verbose/debug output. More v's for more verbosity.
    -b --branch=BRANCH      Branch/tag to checkout repo to [default: main]
    -c --deploy-conf=FILE   Path to config file in repo, if not at /kaas.deploy.yml
    -s --service-conf=FILE  Path to config file in repo, if not at /kaas.service.yml
    -r --restart=NAME       Restart kubernetes deployment
    -d --delete=NAME        Delete kubernetes deployment

Daemon Options:
    -d --daemon             Run in the background and listen for connections
    -p --port=PORT          Port to listen for connections on [default: 8800]
"""

import logging
import platform
import re
import tempfile

import docker
import git
import kubernetes
import yaml
from docopt import docopt
from flask import Flask, request
from kubernetes.client.rest import ApiException

app = Flask(__name__)
dclient = docker.from_env()


# custom exceptions
class MissingConfigFile(FileNotFoundError):
    def __init__(
        self, filename, message="config file not found in repo or specified in request"
    ):
        self.message = message
        self.filename = filename

    def __str__(self):
        return f"{self.message}: {self.filename}"


class BadGitRepo(git.exc.GitError):
    def __init__(self, message="unable to clone repo"):
        self.message = message

    def __str__(self):
        return self.message


class BadGitBranch(git.exc.GitError):
    def __init__(self, branch, message="unable to checkout branch"):
        self.branch = branch
        self.message = message

    def __str__(self):
        return f"{self.message} '{self.branch}'"


class ArchNotSupported(Exception):
    def __init__(self, image, arch, supported, message="image not supported for arch"):
        self.image = image
        self.arch = arch
        self.message = message
        self.supported = supported

    def __str__(self):
        return f"image '{self.image}' does not support {self.arch} (supports {', '.join(self.supported)})"


def load_config_file(filename):
    logging.info(f"reading config file from {filename}")

    # load file
    try:
        with open(filename, "r") as f:
            config = yaml.load(f, Loader=yaml.Loader)
    except FileNotFoundError:
        raise MissingConfigFile(filename) from FileNotFoundError

    return config


def get_deploy_conf(deploy_conf, repo_dir):
    # parse options from default config if none given
    if deploy_conf is None:
        deploy_conf = "kaas.deploy.yml"
    if isinstance(deploy_conf, str):
        return load_config_file(f"{repo_dir}/{deploy_conf}")


def get_service_conf(service_conf, repo_dir):
    # parse options from default config if none given
    if service_conf is None:
        service_conf = "kaas.service.yml"
    if isinstance(service_conf, str):  # if string, its a filepath to load from
        return load_config_file(f"{repo_dir}/{service_conf}")


def clone_repo(repo, branch, repo_dir):
    logging.info(f"cloning repo {repo} to {branch}")

    # add empty creds to clone url
    # git asks for auth if repo isnt public
    # we're only supporting public repos for now
    repo = re.sub(r"^https?://(:@)?", "https://:@", repo)

    try:
        repo = git.Repo.clone_from(repo, repo_dir)
    except git.exc.GitCommandError:
        raise BadGitRepo

    if branch is not None:
        try:
            repo.git.checkout(branch)
        except git.exc.GitCommandError:
            raise BadGitBranch(branch)


def build_repo(repo_dir, branch, deploy_conf, service_conf):
    # do work in temp dir
    logging.debug(
        f"building repo '{repo_dir}@{branch}' with deploy conf '{deploy_conf}' and service conf '{service_conf}'"
    )
    # pull image before building to make sure its supported
    with open(f"{repo_dir}/Dockerfile", "r") as df:
        fromregex = re.compile(r"^FROM (.+:?.+)", re.IGNORECASE | re.MULTILINE)
        fromname = fromregex.search(df.read()).groups()[0]

    logging.info(f"pulling base image {fromname} to check architecture")

    # plat.machine() arch string doesn't match docker's arch string
    platform_mappings = {
        "python": "docker",
        "x86": "386",
        "x86_64": "amd64",
        "armv7l": "arm",
        "aarch64": "arm64",
    }
    platform_str = (
        f"{platform.system()}/{platform_mappings[platform.machine()]}".lower()
    )

    fromdata = dclient.images.get_registry_data(fromname)
    platforms = [f"{p['os']}/{p['architecture']}" for p in fromdata.attrs["Platforms"]]
    if platform_str not in platforms:
        raise ArchNotSupported(fromdata.image_name, platform_str, platforms)

    logging.info(f"base image {fromname} good, continuing build")

    image_name = deploy_conf["spec"]["template"]["spec"]["containers"][0]["image"]
    dclient.images.build(path=repo_dir, tag=image_name)

    # push image to local repository
    logging.debug(f"pushing image to localhost:5000/{image_name}")
    dclient.images.push(f"localhost:5000/{image_name}")

    # return label of build image
    return image_name


# POST /build: JSON API to start new build
@app.route("/build", methods=["POST"])
def build_request():
    reqj = request.get_json()
    logging.debug(f"request: {reqj}")

    if not (
        "repo_url" in reqj
        and "repo_branch" in reqj
        and "deploy_config" in reqj
        and "service_config" in reqj
    ):
        logging.error("missing keys")
        return {"err": "Bad request: missing keys"}, 400

    # accepts json as string or as part of request json
    try:
        deploy_conf_location = reqj["deploy_config"]
        service_conf_location = reqj["service_config"]
    except Exception:
        logging.error("malformed config payload")
        return {"err": "Bad request: malformed config payload"}, 400

    with tempfile.TemporaryDirectory(prefix="kaas-repo-build-") as repo_dir:
        clone_repo(reqj["repo_url"], reqj["repo_branch"], repo_dir)
        deploy_conf = get_deploy_conf(deploy_conf_location, repo_dir)
        service_conf = get_service_conf(service_conf_location, repo_dir)

        try:
            image_name = build_repo(
                repo_dir, reqj["repo_branch"], deploy_conf, service_conf
            )
        except Exception as e:
            logging.error(f"failed to build: {e}")
            return {"err": f"Failed to build: {e}"}, 500

        logging.debug("deploying to k8s")
        # load kube config from ~/.kube/config
        kubernetes.config.load_kube_config()
        kubernetes_api = kubernetes.client.AppsV1Api()
        try:
            kubernetes_api.create_namespaced_deployment(
                body=deploy_conf, namespace="default"
            )
        except ApiException as e:
            logging.error(f"failed to deploy: {e}")
            return {"err": f"Failed to deploy: {e}"}, 500

        logging.info(f"Repository built and deployed successfully as '{image_name}'")

        return {"image": image_name}


# DELETE /build: JSON API to delete existing deployment
@app.route("/build/<image_name>", methods=["DELETE"])
def delete_request(image_name):
    reqj = request.get_json()
    logging.debug(f"request: {reqj}")

    logging.debug(f"deleting {image_name} from k8s")
    # load kube config from ~/.kube/config
    kubernetes.config.load_kube_config()
    kubernetes_api = kubernetes.client.AppsV1Api()
    try:
        kubernetes_api.delete_namespaced_deployment(
            name=image_name, namespace="default"
        )
    except ApiException as e:
        logging.error(f"failed to deploy: {e}")
        return {"err": f"Failed to deploy: {e}"}, 500

    logging.info(f"Successfully deleted '{image_name}'")

    return {"image": image_name}


# PATCH /build: JSON API to restart existing deployment
@app.route("/build/<image_name>", methods=["PATCH"])
def restart_request(image_name):
    reqj = request.get_json()
    logging.debug(f"request: {reqj}")

    if not ("repo_url" in reqj and "repo_branch" in reqj and "deploy_config" in reqj):
        logging.error("missing keys")
        return {"err": "Bad request: missing keys"}, 400

    # accepts json as string or as part of request json
    try:
        deploy_conf_location = reqj["deploy_config"]
    except Exception:
        logging.error("malformed config payload")
        return {"err": "Bad request: malformed config payload"}, 400

    with tempfile.TemporaryDirectory(prefix="kaas-repo-build-") as repo_dir:
        clone_repo(reqj["repo_url"], reqj["repo_branch"], repo_dir)
        deploy_conf = get_deploy_conf(deploy_conf_location, repo_dir)

        logging.debug(f"restarting {image_name} in k8s")
        # load kube config from ~/.kube/config
        kubernetes.config.load_kube_config()
        kubernetes_api = kubernetes.client.AppsV1Api()
        try:
            kubernetes_api.patch_namespaced_deployment(
                name=image_name, namespace="default", body=deploy_conf
            )
        except ApiException as e:
            logging.error(f"failed to restart: {e}")
            return {"err": f"Failed to restart: {e}"}, 500

        logging.info(f"Successfully restarted '{image_name}'")

        return {"image": image_name}


# if called from commandline, parse options and build image || start server
if __name__ == "__main__":
    args = docopt(__doc__)

    if args["--verbose"] == 2:
        level = logging.DEBUG
    elif args["--verbose"] == 1:
        level = logging.INFO
    else:
        level = logging.WARN

    logging.basicConfig(format="%(levelname)s: %(message)s", level=level)

    logging.debug(f"args: {args}")

    # run as daemon and listen for build requests on --port
    if args["--daemon"]:
        app.run(host="0.0.0.0", port=args["--port"], debug=args["--verbose"])
        exit(0)

    with tempfile.TemporaryDirectory(prefix="kaas-repo-build-") as repo_dir:
        repo = args["<repo-url>"]
        branch = args["--branch"]
        clone_repo(repo, branch, repo_dir)
        deploy_conf = get_deploy_conf(args["--deploy-conf"], repo_dir)
        service_conf = get_service_conf(args["--service-conf"], repo_dir)

        # load kube config from ~/.kube/config
        kubernetes.config.load_kube_config()
        kubernetes_api = kubernetes.client.AppsV1Api()
        try:
            if args["--restart"]:
                image_name = args["--restart"]
                kubernetes_api.patch_namespaced_deployment(
                    name=image_name, namespace="default", body=deploy_conf
                )
                logging.info(f"Successfully restarted '{image_name}'")

            elif args["--delete"]:
                image_name = args["--delete"]
                kubernetes_api.delete_namespaced_deployment(
                    name=image_name, namespace="default"
                )
                logging.info(f"Successfully deleted '{image_name}'")

            else:
                try:
                    image_name = build_repo(repo_dir, branch, deploy_conf, service_conf)
                except Exception as e:
                    logging.error(f"Error building repo: {e}")
                    exit(1)

                kubernetes_api.create_namespaced_deployment(
                    body=deploy_conf, namespace="default"
                )

                logging.info(
                    f"Repository built and deployed successfully as '{image_name}'"
                )

        except ApiException as e:
            logging.error(f"Error deploying repo: {e}")
            exit(1)

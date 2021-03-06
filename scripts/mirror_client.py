#!/usr/bin/env python
"""mirror_client.py - Clinet for oVirt CI transactional mirrors
"""
from six.moves import StringIO, range
from six.moves.configparser import RawConfigParser
from six.moves.urllib.parse import urlparse
import requests
from requests.exceptions import ConnectionError, Timeout
from os import environ
import glob
import logging
import yaml
from collections import Mapping
from time import sleep
import argparse

HTTP_TIMEOUT = 30
HTTP_RETRIES = 3
HTTP_RETRY_DELAY_SEC = 0.2

logger = logging.getLogger(__name__)


def main():
    (mirrors_uri, configs, allow_proxy) = parse_args()
    mirrors_data = mirrors_from_uri(mirrors_uri)
    for conf in configs:
        inject_yum_mirrors_file(mirrors_data, conf, allow_proxy)


def parse_args():
    """Parse positional arguments and return their values"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mirrors",
        help="Path or URL to a mirrors file."
    )
    parser.add_argument(
        "configs", nargs='+',
        help="A list of yum configs to modify."
    )
    parser.add_argument(
        "-p", "--proxy", action='store_true', default=False,
        help="If not specified, proxy will be set to _none_."
    )
    args = parser.parse_args()
    return args.mirrors, args.configs, args.proxy


def inject_yum_mirrors(mirrors, yum_cfg, out_cfg, allow_proxy=False):
    """Inject yum mirrors into the given yum configuration

    :param Mapping mirrors:  A mapping of mirror names to URLs
    :param file yum_cfg:     YUM configuration file object to adjust
    :param file out_cfg:     File object to write adjusted configuration into
    :param bool allow_proxy: Wether to allow accessing the mirrors via HTTP
                             proxies (defaults to False)

    yum_cfg can be read-only, out_cfg should not be the same as yum_cfg.

    :returns: None
    """
    cfg = RawConfigParser()
    cfg.readfp(yum_cfg)
    for section in cfg.sections():
        if section not in mirrors:
            continue
        cfg.set(section, 'baseurl', mirrors[section])
        cfg.remove_option(section, 'mirrorlist')
        cfg.remove_option(section, 'metalink')
        if not allow_proxy:
            cfg.set(section, 'proxy', '_none_')
    cfg.write(out_cfg)


def inject_yum_mirrors_str(mirrors, yum_cfg_str, allow_proxy=False):
    """Inject yum mirrors into the given yum configuration string

    :param Mapping mirrors:  A mapping of mirror names to URLs
    :param str yum_cfg:      YUM configuration string to adjust
    :param bool allow_proxy: Wether to allow accessing the mirrors via HTTP
                             proxies (defaults to False)

    :rtype: str
    :returns: A string of the adjusted configuration
    """
    out_cfg = StringIO()
    inject_yum_mirrors(mirrors, StringIO(yum_cfg_str), out_cfg, allow_proxy)
    out_cfg.seek(0)
    return out_cfg.read()


def inject_yum_mirrors_file(mirrors, file_name, allow_proxy=False):
    """Inject yum mirrors into the given yum configuration file

    :param Mapping mirrors:  A mapping of mirror names to URLs
    :param str file_name:    YUM configuration file to adjust
    :param bool allow_proxy: Wether to allow accessing the mirrors via HTTP
                             proxies (defaults to False)

    :returns: None
    """
    with open(file_name, 'r') as rf:
        with open(file_name, 'r+') as wf:
            inject_yum_mirrors(mirrors, rf, wf, allow_proxy)
            wf.truncate()
    logger.info('Injected mirrors into: {0}'.format(file_name))


def inject_yum_mirrors_file_by_pattern(
    mirrors, file_pattern, allow_proxy=False
):
    """Inject yum mirrors into the given yum configuration file

    :param Mapping mirrors:  A mapping of mirror names to URLs
    :param str file_pattern: YUM configuration file glob pattern to adjust
    :param bool allow_proxy: Wether to allow accessing the mirrors via HTTP
                             proxies (defaults to False)
    :returns: None
    """
    for file_name in glob.glob(file_pattern):
        inject_yum_mirrors_file(mirrors, file_name, allow_proxy)


def mirrors_from_http(
    url='http://mirrors.phx.ovirt.org/repos/yum/all_latest.json',
    json_varname='latest_ci_repos',
    allow_proxy=False,
):
    """Load mirrors from given URL

    :param str url:          Where to find mirrors JSON file
    :param str json_varname: The variable in the file pointing to the mirror
                             dictionary
    :param bool allow_proxy: Wether to allow accessing the mirrors via HTTP
                             proxies (defaults to False)

    :rtype: dict
    :returns: Loaded mirrors data or an empty dict if could not be loaded
    """
    if allow_proxy:
        proxies = dict()
    else:
        proxies = dict(http=None, https=None)
    try:
        loop_exception = None
        for attempt in range(0, HTTP_RETRIES):
            try:
                resp = requests.get(url, proxies=proxies, timeout=HTTP_TIMEOUT)
                if resp.status_code == 200:
                    return resp.json().get(json_varname, dict())
                else:
                    return dict()
            except ValueError as e:
                # When JSON parsing fails we get a ValueError
                loop_exception = e
            logger.warn('Encountered error getting data from mirrors server' +
                        ' in attempt {0}/{1}'.format(attempt, HTTP_RETRIES))
            # Sleep a short while to let server sort its issues
            sleep(HTTP_RETRY_DELAY_SEC)
        else:
            raise loop_exception
    except ConnectionError:
        logger.warn('Failed to connect to mirrors server')
        return dict()
    except Timeout:
        logger.warn('Timed out connecting to mirrors server')
        return dict()


def mirrors_from_file(file_name):
    """Load mirrors from a local file

    :param str filename: The file to load mirrors from

    The file can be JNOS or YAML formatted

    :rtype: dict
    """
    data = None
    with open(file_name, 'r') as f:
        data = yaml.safe_load(f)
    if not isinstance(data, Mapping):
        raise ValueError("Invalid mirrors data in '{0}'".format(file_name))
    return data


def mirrors_from_uri(uri, json_varname='latest_ci_repos', allow_proxy=False):
    """Load mirrors from URI

    :param str uri: The URI to mirrors JSON file
    :param str json_varname: The variable in the file pointing to the mirror
                             dictionary
    :param bool allow_proxy: Wether to allow accessing the mirrors via HTTP
                             proxies (defaults to False)

    :rtype: dict
    :returns: Loaded mirrors data or an empty dict if could not be loaded
    """
    parsed = urlparse(uri)
    if parsed.scheme == 'http' or parsed.scheme == 'https':
        return mirrors_from_http(parsed.geturl(), json_varname, allow_proxy)
    if parsed.scheme == '' or parsed.scheme == 'file':
        return mirrors_from_file(parsed.path)


def mirrors_from_environ(
    env_varname='CI_MIRRORS_URL',
    json_varname='latest_ci_repos',
    allow_proxy=False,
):
    """Load mirrors from URL given in an environment variable

    :param str env_varname:  The environment variable containing URL to mirrors
                             JSON file
    :param str json_varname: The variable in the file pointing to the mirror
                             dictionary
    :param bool allow_proxy: Wether to allow accessing the mirrors via HTTP
                             proxies (defaults to False)

    :rtype: dict
    :returns: Loaded mirrors data or an empty dict if could not be loaded or
              the environment variable was not defined
    """
    if env_varname not in environ:
        return dict()
    return mirrors_from_uri(environ[env_varname])


def setupLogging(level=logging.INFO):
    """Basic logging setup for users of this script who don't what to bother
    with it

    :param int level: The logging level to setup (set to consts from the
                      logging module, default is INFO)
    """
    logging.basicConfig()
    logging.getLogger().level = logging.INFO


def ovirt_tested_as_mirrors(
    ovirt_release,
    distributions=('el7', 'fc24', 'fc25', 'fc26'),
    repos_base='http://resources.ovirt.org/repos/ovirt/tested',
):
    """Generate a mirrors dict that points to the oVirt tested repos

    :param str ovirt_release:      The oVirt release which tested repos we want
    :param Iterable distributions: (optional) the list of distributions oVirt
                                   is released for
    :param str repos_base:         (optional) the base URL for the 'tested'
                                   repos

    The list passed to 'distributions' does not have to be accurate. The
    resulting dict is used in mirror injection (one of the inject_* functions
    above) so for a repo to be used, someone needs to ask for it by including a
    repo with the correct repo id in a yum configuration file. Therefore it is
    quite safe to include non-existent distros here, and it is also safe to
    omit some exiting distros as long as they are not asked for.

    :rtype: dict
    :returns: A mirrors dict that will cause the URLs for tested repos to be
              injected for repos called 'ovirt-<version>-<distro>'
    """
    return dict(
        (
            'ovirt-{0}-{1}'.format(ovirt_release, distribution),
            '{0}/{1}/rpm/{2}/'.format(repos_base, ovirt_release, distribution)
        ) for distribution in distributions
    )


if __name__ == "__main__":
    main()

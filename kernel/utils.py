import sys
import os
from pygrading import *
import re
import tempfile
from urllib.parse import urlsplit, urlunsplit


def mask_repo_url(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    if not parts.username and not parts.password:
        return url

    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"{parts.username or '***'}:***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def sanitize_config_for_log(config):
    sanitized = dict(config)
    if sanitized.get('repo_url'):
        sanitized['repo_url'] = mask_repo_url(sanitized['repo_url'])
    if sanitized.get('server_password'):
        sanitized['server_password'] = '***'
    return sanitized


def console_log(text):
    try:
        f = open("/mnt/cghook/console_log", "a+")
        f.write(text)
        f.write("\n")
        f.close()
    except Exception as e:
        pass


def Singleton(cls):
    _instance = {}

    def inner():
        if cls not in _instance:
            _instance[cls] = cls()
        return _instance[cls]

    return inner


@Singleton
class Env:
    def __init__(self):
        self.is_debug = True
        self.config = {
            'submit_dir': '/coursegrader/submit',
            'testcase_dir': '/coursegrader/testdata',
            'return_code': 0,
            "exec_dir": tempfile.mkdtemp(),
            'id_rsa_path': '/cg/id_rsa'
        }

    def load_config(self, config_src=None):
        if os.environ.get("CONFIG_SRC"):
            self.config.update(load_config(os.environ.get("CONFIG_SRC")))
        if not config_src:
            config_src = os.path.join(self.config['testcase_dir'], "config.json")
        if os.path.exists(config_src):
            self.config.update(load_config(config_src))
        self.is_debug = self.config.get("debug", True)
        if "testcase_num" not in self.config:
            self.config["testcase_num"] = count_testcase(self.config["testcase_dir"])
        self.config["exec_src"] = os.path.join(self.config["exec_dir"], "exec.out")

        # set env here!!
        os.environ['PATH'] = '/root/.cargo/bin:'+os.environ['PATH']
        os.environ['PATH'] = '/usr/local/bin/riscv64-linux-musl-cross/bin:'+os.environ['PATH']
        os.environ['PATH'] = '/opt/kendryte-toolchain/bin:'+os.environ['PATH']
        # os.environ['PATH'] = '/usr/local/bin/riscv64-unknown-elf-gcc-8.3.0-2020.04.0-x86_64-linux-ubuntu14/bin:'+os.environ['PATH']

        self.config['server_ip'] = os.environ.get('SERVER_IP')
        self.config['server_port'] = os.environ.get('SERVER_PORT', 22)
        self.config['server_password'] = os.environ.get('SERVER_PSW', None)
        self.config['server_user'] = os.environ.get('SERVER_USER', 'root')
        self.config['server_dev'] = os.environ.get('SERVER_DEV', "QEMU")
        self.config['repo_url'] = os.environ.get('REPO_URL', self.config.get('repo_url'))
        self.config['repo_ref'] = os.environ.get('REPO_REF', self.config.get('repo_ref'))
        self.config['repo_subdir'] = os.environ.get('REPO_SUBDIR', self.config.get('repo_subdir'))
        self.config['repo_depth'] = os.environ.get('REPO_DEPTH', self.config.get('repo_depth'))

        # test_track_config = {track_grading_enable_config_key: self.config.get(track_grading_enable_config_key, True),
        #                      track_auth_jwt_config_key: "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
        #                                                 "eyJpc3MiOiJodHRwOi8vbGVhcm5pbmcuZWR1Y2"
        #                                                 "cubmV0IiwibmFtZSI6IlB5dGhvbiBHcmFkaW5n"
        #                                                 "IEtlcm5lbCJ9.pf0vDkYc4TTgCUhxpCIobv7ST7NcMPovDWihidxzYBg",
        #                      track_lrs_endpoint_config_key: 'http://218.28.198.182:8080/cglearning'}
        # self.config.update(test_track_config)

        loge(sanitize_config_for_log(self.config))
        return self

    def __getitem__(self, item):
        return self.config[item]

    def __setitem__(self, key, value):
        self.config[key] = value


def loge(*args, **kwargs):
    if Env().is_debug:
        print(*args, file=sys.stderr, flush=True, **kwargs)


def count_testcase(input_dir: str):
    input_dir = os.path.join(input_dir)
    testcase_num = len(list(filter(lambda x: re.match(r"input\d+\.txt", x), os.listdir(input_dir))))
    return testcase_num

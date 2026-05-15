import time

import pytz

from pygrading import *
from exception import CG
from utils import loge, console_log, mask_repo_url, sanitize_config_for_log
from datetime import datetime

import pygrading as gg
import os
import shutil
import subprocess


def clone_submit_repo(job: Job, config):
    repo_url = config.get('repo_url')
    if not repo_url:
        return

    clone_dir = os.path.join(config['exec_dir'], 'submit_repo')
    git_env = make_git_env(config)
    if os.path.exists(clone_dir):
        shutil.rmtree(clone_dir)

    cmd = ['git', 'clone', '--recursive']
    repo_ref = config.get('repo_ref')
    repo_depth = config.get('repo_depth')
    if repo_ref and repo_depth:
        cmd.extend(['--branch', repo_ref])
    if repo_depth:
        cmd.extend(['--depth', str(repo_depth)])
    cmd.extend([repo_url, clone_dir])

    display_cmd = [mask_repo_url(arg) if arg == repo_url else arg for arg in cmd]
    loge("[os autotest]: clone submit repo: " + mask_repo_url(repo_url))
    console_log("正在拉取仓库")
    clone_result = subprocess.run(
        cmd,
        env=git_env,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    job.add_log_detail(
        f"CMD: {' '.join(display_cmd)}\nSTDOUT:\n{clone_result.stdout}\nSTDERR:\n{clone_result.stderr}",
        "仓库拉取输出",
    )
    if clone_result.returncode != 0:
        raise CG.CompileError("仓库拉取失败")

    if repo_ref and not repo_depth:
        checkout_result = subprocess.run(
            ['git', 'checkout', repo_ref],
            cwd=clone_dir,
            env=git_env,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        job.add_log_detail(
            f"CMD: git checkout {repo_ref}\nSTDOUT:\n{checkout_result.stdout}\nSTDERR:\n{checkout_result.stderr}",
            "仓库切换输出",
        )
        if checkout_result.returncode != 0:
            raise CG.CompileError("仓库版本切换失败")

        submodule_result = subprocess.run(
            ['git', 'submodule', 'update', '--init', '--recursive'],
            cwd=clone_dir,
            env=git_env,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        job.add_log_detail(
            "CMD: git submodule update --init --recursive\n"
            f"STDOUT:\n{submodule_result.stdout}\nSTDERR:\n{submodule_result.stderr}",
            "子模块更新输出",
        )
        if submodule_result.returncode != 0:
            raise CG.CompileError("仓库子模块更新失败")

    submit_dir = clone_dir
    repo_subdir = config.get('repo_subdir')
    if repo_subdir:
        submit_dir = os.path.abspath(os.path.join(clone_dir, repo_subdir))
        if os.path.commonpath([os.path.abspath(clone_dir), submit_dir]) != os.path.abspath(clone_dir):
            raise CG.CompileError("仓库子目录非法")
        if not os.path.isdir(submit_dir):
            raise CG.CompileError("仓库子目录不存在")

    config['submit_dir'] = submit_dir
    backup_host_shells(job, clone_dir)
    patch_starry_shell_scripts(job, clone_dir)
    patch_starry_host_shell_restore(job, clone_dir)
    patch_starry_build_rules(job, clone_dir)
    patch_lwext4_arch_env(job, clone_dir)
    console_log("仓库拉取完成")


def make_git_env(config):
    env = os.environ.copy()
    git_home = os.path.join(config['exec_dir'], 'git-home')
    git_config_home = os.path.join(config['exec_dir'], 'git-config')
    os.makedirs(git_home, exist_ok=True)
    os.makedirs(git_config_home, exist_ok=True)

    env['GIT_CONFIG_NOSYSTEM'] = '1'
    env['GIT_CONFIG_GLOBAL'] = os.devnull
    env['GIT_TERMINAL_PROMPT'] = '0'
    env['HOME'] = git_home
    env['XDG_CONFIG_HOME'] = git_config_home

    for key in ('GIT_ASKPASS', 'SSH_ASKPASS', 'GIT_EXEC_PATH', 'GIT_DIR', 'GIT_WORK_TREE'):
        env.pop(key, None)
    for key in list(env):
        if key.startswith('GIT_CONFIG_') and key not in ('GIT_CONFIG_NOSYSTEM', 'GIT_CONFIG_GLOBAL'):
            env.pop(key, None)

    return env


def is_elf_file(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def backup_host_shells(job: Job, repo_dir):
    backup_dir = os.path.join(repo_dir, ".autotest-shell-backup")
    os.makedirs(backup_dir, exist_ok=True)
    backed_up = []

    for shell_name in ("bash", "dash"):
        src = os.path.join("/bin", shell_name)
        if not is_elf_file(src):
            continue
        dst = os.path.join(backup_dir, shell_name)
        shutil.copy2(src, dst)
        os.chmod(dst, 0o755)
        backed_up.append(dst)

    if backed_up:
        job.add_log_detail("\n".join(backed_up), "宿主 shell 备份")


def shell_restore_recipe():
    return (
        'if [ -f "$(CURDIR)/../../.autotest-shell-backup/bash" ]; then '
        'tmp="/bin/bash.autotest.$$"; '
        'cp "$(CURDIR)/../../.autotest-shell-backup/bash" "$$tmp" && '
        'chmod 755 "$$tmp" && '
        'mv -f "$$tmp" /bin/bash; '
        'fi; '
        'if [ -f "$(CURDIR)/../../.autotest-shell-backup/dash" ]; then '
        'tmp="/bin/dash.autotest.$$"; '
        'cp "$(CURDIR)/../../.autotest-shell-backup/dash" "$$tmp" && '
        'chmod 755 "$$tmp" && '
        'mv -f "$$tmp" /bin/dash; '
        'fi'
    )


def patch_starry_host_shell_restore(job: Job, repo_dir):
    patched = []
    restore = shell_restore_recipe()
    old_build = (
        '\t@make -C "$(AX_ROOT)" A="$(CURDIR)" ARCH="$(ARCH)" '
        'EXTRA_CONFIG="$(EXTRA_CONFIG)" BLK=y NET=y build\n'
    )
    new_build = (
        '\t@make -C "$(AX_ROOT)" A="$(CURDIR)" ARCH="$(ARCH)" '
        'EXTRA_CONFIG="$(EXTRA_CONFIG)" BLK=y NET=y build; status=$$?; \\\n'
        f'\t\t{restore}; \\\n'
        '\t\texit $$status\n'
    )
    old_pack = (
        '\t@if [ "$(ARCH)" = "riscv64" ]; then \\\n'
        '\t\t"$(RV_LD)" -m elf64lriscv -T "$(RV_QEMU_KERNEL_LD)" -o kernel-rv -b binary "$(OUT_BIN)"; \\\n'
        '\telse \\\n'
        '\t\tcp "$(OUT_ELF)" kernel-la; \\\n'
        '\tfi\n'
    )
    new_pack = (
        '\t@if [ "$(ARCH)" = "riscv64" ]; then \\\n'
        '\t\t"$(RV_LD)" -m elf64lriscv -T "$(RV_QEMU_KERNEL_LD)" -o kernel-rv -b binary "$(OUT_BIN)"; \\\n'
        '\telse \\\n'
        '\t\tcp "$(OUT_ELF)" kernel-la; \\\n'
        '\tfi; status=$$?; \\\n'
        f'\t{restore}; \\\n'
        '\texit $$status\n'
    )

    for root, _dirs, files in os.walk(repo_dir):
        if "Makefile" not in files:
            continue
        path = os.path.join(root, "Makefile")
        normalized = path.replace(os.sep, "/")
        if not normalized.endswith("/starry-next/Makefile"):
            continue

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = content
        if old_build in new_content:
            new_content = new_content.replace(old_build, new_build, 1)
        if old_pack in new_content:
            new_content = new_content.replace(old_pack, new_pack, 1)
        if new_content == content:
            continue

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        patched.append(path)

    if patched:
        job.add_log_detail("\n".join(patched), "宿主 shell 恢复规则修补")
        console_log("已修补宿主 shell 恢复规则")


def patch_starry_build_rules(job: Job, repo_dir):
    old_rule = "$(OUT_BIN): _cargo_build $(OUT_ELF)"
    new_rule = "$(OUT_BIN): _cargo_build"
    patched = []

    for root, _dirs, files in os.walk(repo_dir):
        if "build.mk" not in files:
            continue
        path = os.path.join(root, "build.mk")
        normalized = path.replace(os.sep, "/")
        if not normalized.endswith("/arceos/scripts/make/build.mk"):
            continue

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if old_rule not in content:
            continue

        with open(path, "w", encoding="utf-8") as f:
            f.write(content.replace(old_rule, new_rule, 1))
        patched.append(path)

    if patched:
        job.add_log_detail("\n".join(patched), "Starry 构建规则修补")
        console_log("已修补 Starry 构建规则")


def patch_starry_shell_scripts(job: Job, repo_dir):
    old_shebang = "#/bin/bash"
    new_shebang = "#!/bin/bash"
    patched = []

    for root, _dirs, files in os.walk(repo_dir):
        if "set_ax_root.sh" not in files:
            continue
        path = os.path.join(root, "set_ax_root.sh")
        normalized = path.replace(os.sep, "/")
        if not normalized.endswith("/starry-next/scripts/set_ax_root.sh"):
            continue

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.startswith(old_shebang):
            continue

        with open(path, "w", encoding="utf-8") as f:
            f.write(content.replace(old_shebang, new_shebang, 1))
        patched.append(path)

    if patched:
        job.add_log_detail("\n".join(patched), "Starry shell 脚本修补")
        console_log("已修补 Starry shell 脚本")


def patch_lwext4_arch_env(job: Job, repo_dir):
    old_cmd = 'cd build_$(1) && cmake -G"Unix Makefiles"'
    old_arch_cmd = 'cd build_$(1) && ARCH=$(ARCH) cmake -G"Unix Makefiles"'
    new_cmd = (
        'cd build_$(1) && ARCH=$(ARCH) cmake -G"Unix Makefiles" '
        '-DCMAKE_C_COMPILER_WORKS=TRUE -DCMAKE_CXX_COMPILER_WORKS=TRUE'
    )
    old_make_cmd = 'cd build_$@ && make lwext4'
    old_make_cmd_with_shell = 'cd build_$@ && $(MAKE) SHELL=/bin/bash lwext4'
    new_make_cmd = 'cd build_$@ && env -u MAKEFLAGS -u MFLAGS $(MAKE) -j1 SHELL=/bin/bash lwext4'
    patched = []

    for root, _dirs, files in os.walk(repo_dir):
        if "Makefile" not in files:
            continue
        path = os.path.join(root, "Makefile")
        normalized = path.replace(os.sep, "/")
        if "/lwext4" not in normalized or not normalized.endswith("/c/lwext4/Makefile"):
            continue

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = content
        if "SHELL := /bin/bash\n" not in new_content:
            new_content = new_content.replace("#Release\n", "SHELL := /bin/bash\n\n#Release\n", 1)
        if old_arch_cmd in new_content:
            new_content = new_content.replace(old_arch_cmd, new_cmd, 1)
        elif old_cmd in new_content:
            new_content = new_content.replace(old_cmd, new_cmd, 1)
        if old_make_cmd_with_shell in new_content:
            new_content = new_content.replace(old_make_cmd_with_shell, new_make_cmd, 1)
        elif old_make_cmd in new_content:
            new_content = new_content.replace(old_make_cmd, new_make_cmd, 1)
        if new_content == content:
            continue

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        patched.append(path)

    if patched:
        job.add_log_detail("\n".join(patched), "lwext4 ARCH 环境修补")
        console_log("已修补 lwext4 ARCH 环境")


@CG.catch
def prework(job: Job):
    with open("/mnt/cghook/cancel_purge", "w") as f:
        f.write("pkill qemu-system-riscv64\n")
        f.write("pkill qemu-system-loongarch64\n")
    job.add_log(str(datetime.now(tz=pytz.timezone("Asia/Shanghai"))), "START TIME")
    config = job.get_config()
    clone_submit_repo(job, config)
    # need to be done when run in platform
    # config['submit_dir'] = os.path.join(config['submit_dir'], os.listdir(config['submit_dir'])[0])

#     check_result = subprocess.run("tar xavf /cg/STCheck.tar.gz -C /tmp", shell=True,
#                                     stderr=subprocess.PIPE, stdout=subprocess.PIPE)
#     check_result = subprocess.run("/tmp/STCheck/RunTest.sh", shell=True,
#                                     cwd='/tmp/STCheck',
#                                     stderr=subprocess.PIPE, stdout=subprocess.PIPE)
#
    if len(os.listdir(config['submit_dir'])) == 0:
        raise CG.CompileError("No submit file")

    forbidden_files = ["os_flash_out.txt", "os_serial_out.txt", "sdcard_write.txt", "sdcard_flash.txt", "os.bin"]
    for file in os.listdir(config['submit_dir']):
        if file in forbidden_files:
            raise CG.CompileError(f"You cannot submit a {file}")

    # start compile
    loge("\n[os autotest]: Compile Start\n")

    # execute make command
    loge("\n[os autotest]: call make to compile\n")
    os.system("mkdir -p /mnt/cghook")
    f = open("/mnt/cghook/console_log", "w")
    f.write("正在编译\n")
    f.flush()
    compile_result = subprocess.run("make all", shell=True,
                                    cwd=config['submit_dir'],
                                    stderr=f, stdout=f)
    f.close()
    job.add_log_detail(str(sanitize_config_for_log(config)), "CONFIG")
    job.add_log(open("/mnt/cghook/console_log", errors='ignore').read(), "编译输出")
    open("/mnt/cghook/console_log", "w").close()

    # has_sbi = os.path.exists(os.path.join(config['submit_dir'], 'sbi-rv'))

    config['sbi_file'] = 'default'

    if compile_result.returncode != 0:
        raise CG.CompileError("编译出错")

    console_log("编译完成")

    def logexec(cmd):
        # print("cmd" + cmd)
        job.add_log_detail(cmd, "cmd")
        loge("[os autotest]:" + cmd)
        start_time = time.time()
        res = gg.exec(cmd)
        job.add_log_detail(f"STDOUT:\n{res.stdout}\nSTDERR:{res.stderr}\nTIME:{datetime.now()}\nDURATION:{time.time() - start_time}", cmd)
        if res.returncode != 0:
            raise RuntimeError(f"run command error {cmd} \n{res.stdout}\n{res.stderr}")
        return res

    loge("[os autotest]: Compile Succeed")

    testcases = TestCases()
    testcases.append("TestCase 1", 100, "", "")
    job.set_testcases(testcases)

import sys
import json
import re

template = '''
RUN LTP CASE writev01
tst_tmpdir.c:316: TINFO: Using /tmp/LTP_wriRnYU84 as tmpdir (ext2/ext3/ext4 filesystem)
tst_test.c:1860: TINFO: LTP version: 20240930
tst_test.c:1864: TINFO: Tested kernel: 5.15.153.1-microsoft-standard-WSL2 #1 SMP Fri Mar 29 23:14:13 UTC 2024 x86_64
tst_test.c:1703: TINFO: Timeout per run is 0h 00m 30s
writev01.c:124: TPASS: invalid iov_len, expected: -1 (EINVAL), got: -1 (EINVAL)
writev01.c:124: TPASS: invalid fd, expected: -1 (EBADF), got: -1 (EBADF)
writev01.c:124: TPASS: invalid iovcnt, expected: -1 (EINVAL), got: -1 (EINVAL)
writev01.c:129: TPASS: zero iovcnt, expected: 0, got: 0
writev01.c:129: TPASS: NULL and zero length iovec, expected: 64, got: 64
writev01.c:124: TPASS: write to closed pipe, expected: -1 (EPIPE), got: -1 (EPIPE)

Summary:
passed   6
failed   0
broken   0
skipped  0
warnings 0
END LTP CASE writev01 : 0
RUN LTP CASE setegid02
tst_test.c:1860: TINFO: LTP version: 20240930
tst_test.c:1864: TINFO: Tested kernel: 5.15.153.1-microsoft-standard-WSL2 #1 SMP Fri Mar 29 23:14:13 UTC 2024 x86_64
tst_test.c:1703: TINFO: Timeout per run is 0h 00m 30s
setegid02.c:29: TPASS: setegid(65534) : EPERM (1)

Summary:
passed   1
failed   0
broken   0
skipped  0
warnings 0
END LTP CASE setegid02: 0
'''

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
LTP_RESULT_KEYS = {
    "TPASS": "passed",
    "TFAIL": "failed",
    "TBROK": "broken",
    "TCONF": "skipped",
    "TWARN": "warnings",
}


def parse_ltp_log(content):
    lines = content.split('\n')
    result = {}
    current_case = None
    counts = None
    summary_data = None
    in_summary = False

    def reset_counts():
        return {'passed': 0, 'failed': 0, 'broken': 0, 'skipped': 0, 'warnings': 0}

    def finish_case():
        nonlocal current_case, counts, summary_data, in_summary
        if not current_case:
            return
        active = counts if counts and sum(counts.values()) > 0 else summary_data
        active = active or reset_counts()
        result[current_case] = {
            'passed': active['passed'],
            'failed': active['failed'],
            'broken': active['broken'],
            'skipped': active['skipped'],
            'warnings': active['warnings'],
            'all': sum(active.values()),
            'success': active['passed']
        }
        current_case = None
        counts = None
        summary_data = None
        in_summary = False

    for line in lines:
        stripped_line = ANSI_RE.sub("", line).strip()

        if stripped_line.startswith('RUN LTP CASE'):
            finish_case()
            current_case = stripped_line.split()[-1]
            counts = reset_counts()
            summary_data = reset_counts()
            in_summary = False

        elif current_case and (
            stripped_line.startswith(f'PASS LTP CASE {current_case}')
            or stripped_line.startswith(f'FAIL LTP CASE {current_case}')
            or stripped_line.startswith(f'END LTP CASE {current_case}')
        ):
            finish_case()

        elif current_case:
            if stripped_line == 'Summary:':
                in_summary = True
                continue

            if in_summary:
                if not stripped_line:
                    in_summary = False
                    continue

                parts = stripped_line.split()
                if len(parts) >= 2 and parts[0] in ['passed', 'failed', 'broken', 'skipped', 'warnings']:
                    key = parts[0]
                    try:
                        summary_data[key] += int(parts[1])
                    except ValueError:
                        pass
                    continue

            for marker, key in LTP_RESULT_KEYS.items():
                if f"{marker}:" in stripped_line:
                    counts[key] += 1
                    break

    finish_case()

    return result

result =  parse_ltp_log(sys.stdin.read())
result = [{
    "name": k,
    "pass": v["success"],
    "all": v["all"],
    "score": v["success"]  # 暂时用 success 值做分数
} for k, v in result.items()]

print(json.dumps(result))

# Auto-resolve git merge conflict markers by keeping the incoming block (after =======)
# Backs up original files with extension .orig_merge_bak

import subprocess
import sys
import os
import time

def git_grep_files():
    try:
        out = subprocess.check_output([
            'git','grep','-n','-e','^<<<<<<<','-e','^=======','-e','^>>>>>>>'
        ], stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError as e:
        # no matches -> exit
        return []
    files = set()
    for line in out.splitlines():
        if ':' in line:
            files.add(line.split(':',1)[0])
    return sorted(files)


def process_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    out_lines = []
    i = 0
    changed = False
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith('<<<<<<<'):
            # enter conflict, skip until '=======', then keep until '>>>>>>>'
            changed = True
            # skip local block
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith('======='):
                i += 1
            # if no separator, abort: preserve original remainder
            if i >= len(lines):
                # malformed conflict; abort
                print(f"Malformed conflict in {path}, leaving file unchanged")
                return False
            # skip the '=======' line
            i += 1
            # copy incoming block until '>>>>>>>'
            while i < len(lines) and not lines[i].lstrip().startswith('>>>>>>>'):
                out_lines.append(lines[i])
                i += 1
            # skip the '>>>>>>>' line
            if i < len(lines) and lines[i].lstrip().startswith('>>>>>>>'):
                i += 1
            continue
        else:
            out_lines.append(line)
            i += 1
    if changed:
        # create a timestamped backup to avoid skipping files with existing backups
        bak = path + '.orig_merge_bak.' + str(int(time.time()))
        try:
            os.rename(path, bak)
        except Exception:
            # fallback to copying if rename fails
            with open(path, 'r', encoding='utf-8') as src, open(bak, 'w', encoding='utf-8') as dst:
                dst.writelines(src.readlines())
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(out_lines)
        print(f"Fixed {path} (backup saved to {bak})")
        return True
    return False


def main():
    files = git_grep_files()
    if not files:
        print('No conflict markers found.')
        return 0
    fixed = []
    skipped = []
    for p in files:
        if not os.path.isfile(p):
            skipped.append(p)
            continue
        ok = process_file(p)
        if ok:
            fixed.append(p)
        else:
            skipped.append(p)
    if fixed:
        try:
            subprocess.check_call(['git','add'] + fixed)
            msg = 'chore: auto-resolve merge markers (keep incoming blocks)'
            subprocess.check_call(['git','commit','-m', msg])
            print('Committed fixes:')
            for f in fixed:
                print('  ' + f)
        except subprocess.CalledProcessError as e:
            print('Git add/commit failed:', e)
            return 2
    if skipped:
        print('Skipped files:')
        for s in skipped:
            print('  ' + s)
    return 0

if __name__ == '__main__':
    sys.exit(main())

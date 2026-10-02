"""Native folder selection for the loopback-only desktop service."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

_picker_lock = threading.Lock()


def choose_directory(initial=''):
    if not _picker_lock.acquire(blocking=False):
        raise RuntimeError('文件夹选择窗口已经打开，请先完成选择。')
    try:
        result = subprocess.run(
            [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--dialog'],
            input=json.dumps({'initial': initial}), capture_output=True,
            text=True, encoding='utf-8', timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        if result.returncode:
            raise RuntimeError('无法打开本机文件夹窗口，请直接填写目录。')
        selected = json.loads(result.stdout).get('path')
        if not selected:
            return None
        folder = Path(selected)
        if not folder.is_absolute() or not folder.is_dir():
            raise RuntimeError('所选文件夹已不可用，请重新选择。')
        return str(folder.resolve())
    except subprocess.TimeoutExpired:
        raise RuntimeError('文件夹选择已超时，请重新打开。') from None
    finally:
        _picker_lock.release()


def show_dialog():
    import tkinter as tk
    from tkinter import filedialog
    initial = json.loads(sys.stdin.read()).get('initial', '')
    # No shell interpolation; an invalid or remote path never becomes a command.
    local = Path(initial) if initial and not initial.startswith(('\\\\', '//')) else None
    initial_dir = str(local) if local and local.is_absolute() and local.is_dir() else str(Path.home())
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        selected = filedialog.askdirectory(parent=root, title='选择素材文件夹',
                                           initialdir=initial_dir, mustexist=True)
        print(json.dumps({'path': selected or None}, ensure_ascii=False))
    finally:
        root.destroy()


if __name__ == '__main__' and '--dialog' in sys.argv:
    show_dialog()

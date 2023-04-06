import os
import fnmatch

import shutil
from pathlib import Path

def copy_directory_contents(src: Path, dest: Path):
    # Create the destination directory if it doesn't exist
    dest.mkdir(parents=True, exist_ok=True)

    # Iterate through the source directory contents and copy each item to the destination directory
    for item in src.iterdir():
        if item.is_file():
            shutil.copy2(item, dest / item.name)
        elif item.is_dir():
            # Recursively copy subdirectories
            copy_directory_contents(item, dest / item.name)

def recursive_copy(src: Path, dst: Path, exclude_files=[], exclude_dirs=[]):
    src = Path(src)
    dst = Path(dst)
    
    if not src.is_dir():
        raise ValueError(f"Source {src} is not a directory")
    if not dst.is_dir():
        raise ValueError(f"Destination {dst} is not a directory")
    if src == dst:
        raise Exception("Source and Destination directories are the same!")

    for item in src.iterdir():
        # If the item is a directory and does not match any of the exclude patterns
        if item.is_dir() and not any(fnmatch.fnmatch(item, pattern) for pattern in exclude_dirs):
            new_dst = dst / item.name
            new_dst.mkdir(exist_ok=True)
            recursive_copy(item, new_dst, exclude_files, exclude_dirs)
        # If the item is a file and does not match any of the exclude patterns
        elif item.is_file() and not any(fnmatch.fnmatch(item, pattern) for pattern in exclude_files):
            shutil.copy(item, dst)

"""
def recursive_copy(src, dst, exclude_files=None, exclude_dirs=None):
    if exclude_files is None:
        exclude_files = []
    if exclude_dirs is None:
        exclude_dirs = []

    if not os.path.exists(dst):
        os.makedirs(dst)

    for item in os.listdir(src):
        src_item = os.path.join(src, item)
        dst_item = os.path.join(dst, item)

        if os.path.isdir(src_item):
            # Check if the directory matches any of the exclude patterns
            if not any(fnmatch.fnmatch(item, pattern) for pattern in exclude_dirs):
                recursive_copy(src_item, dst_item, exclude_files, exclude_dirs)
        else:
            # Check if the file matches any of the exclude patterns
            if not any(fnmatch.fnmatch(item, pattern) for pattern in exclude_files):
                shutil.copy2(src_item, dst_item)
"""

# Example usage:
"""
src = 'source_directory'
dst = 'destination_directory'
exclude_files = ['*.tmp', '*.log']
exclude_dirs = ['__pycache__', 'temp']

recursive_copy(src, dst, exclude_files, exclude_dirs)
"""
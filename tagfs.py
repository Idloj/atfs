#!/usr/bin/env python
from __future__ import print_function, absolute_import, division

from errno import EACCES, ENODATA
from fusepy import FUSE, FuseOSError, Operations
import os
from sys import argv, exit
from xattr import xattr

class Tagfs(Operations):
    def __init__(self, root_fd):
        # should only be used by `init`, it's closed immediately afterwards
        self.root_fd = root_fd

    def __call__(self, op, path, *args):
        try:
            return super(Tagfs, self).__call__(op, "." + path, *args)
        except EnvironmentError as err:
            raise FuseOSError(err.errno)

    def init(self, path):
        os.fchdir(self.root_fd)
        os.close(self.root_fd)

    def statfs(self, path):
        stv = os.statvfs(path)
        return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
            'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
            'f_frsize', 'f_namemax'))

    def fsync(self, path, datasync, fh):
        if datasync != 0:
          return os.fdatasync(fh)
        else:
          return os.fsync(fh)

    def access(self, path, mode):
        if not os.access(path, mode):
            raise FuseOSError(EACCES)

    def getattr(self, path, fh=None):
        st = os.lstat(path)
        return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
            'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))

    chmod = os.chmod

    chown = os.chown
    
    readlink = os.readlink

    mknod = os.mknod

    mkdir = os.mkdir

    rmdir = os.rmdir

    def readdir(self, path, fh):
        return ['.', '..'] + os.listdir(path)

    def link(self, target, source):
        return os.link(source, target)

    unlink = os.unlink

    def symlink(self, target, source):
        return os.symlink(source, target)

    def rename(self, old, new):
        return os.rename(old, "." + new)

    def listxattr(self, path):
        return xattr(path).list()

    def getxattr(self, path, name):
        return xattr(path).get(name)

    def setxattr(self, path, name, value, options):
        xattr(path).set(name, value, options)

    def removexattr(self, path, name):
        xattr(path).remove(name)

    utimens = os.utime

    open = os.open

    def create(self, path, mode):
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)

    def read(self, path, size, offset, fh):
        os.lseek(fh, offset, 0)
        return os.read(fh, size)

    def write(self, path, data, offset, fh):
        os.lseek(fh, offset, 0)
        return os.write(fh, data)

    def truncate(self, path, length, fh=None):
        with open(path, 'r+') as f:
            f.truncate(length)

    def flush(self, path, fh):
        return os.fsync(fh)
    
    def release(self, path, fh):
        return os.close(fh)


if __name__ == '__main__':
    if len(argv) != 2:
        print('usage: %s <root>' % argv[0])
        exit(1)

    # we CAN actually write to the directory (e.g., creating a new dir in it),
    # we use O_RDONLY just to work around python not allowing to open dirs with O_RDWR
    root_fd = os.open(os.path.realpath(argv[1]), os.O_RDONLY)
    fuse = FUSE(Tagfs(root_fd), argv[1], fsname="tagfs",
                foreground=True, nothreads=True, nonempty=True, allow_other=True)#, debug=True)
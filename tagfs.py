#!/usr/bin/env python
from __future__ import print_function, absolute_import, division

from ast import literal_eval
from errno import *
from fusepy import FUSE, FuseOSError, Operations
import os
from sys import argv, exit
from xattr import xattr

def notsup():
    raise FuseOSError(ENOTSUP)

def base(path):
    return path.split('/')[-1]

def real(path):
    return './' + base(path)

def set_tags_xattr(path, tags):
    xattr(path).set('user.tags', ','.join(tags).encode('utf-8'))

def path2tags(path):
    comps = path.rstrip('/').split('/')
    return set(comps[1:-1])
    
def xattr2tags(path):
    try:
        tags = {tag.decode('utf-8') for tag in xattr(path).get('user.tags').split(',')}
        if tags == {''}:
            return set()
        return tags
    except IOError:
        set_tags_xattr(path, [])
        return set()

def stat(path):
    st = os.lstat(path)
    return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
        'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))

class Tagfs(Operations):
    def __init__(self, root_fd):
        self.root_fd = root_fd # should only be used by `init`, which closes it
        self.tags = {}

    def __call__(self, op, path, *args):
        try:
            return super(Tagfs, self).__call__(op, path, *args)
        except EnvironmentError as err:
            raise FuseOSError(err.errno)

    def tags_operation(self, path, files_fn, tags_fn=notsup):
        tags = self.tags if (base(path) in self.tags) else xattr2tags(real(path))
        if not path2tags(path).issubset(tags):
            raise FuseOSError(ENOENT)
        if base(path) in self.tags:
            return tags_fn()
        else:
            return files_fn()

    def update_fs_xattr(self):
        xattr('.').set('user.tagfs.tags', str(self.tags))

    def init(self, path):
        os.fchdir(self.root_fd)
        os.close(self.root_fd)
        self.tags = literal_eval(xattr('.').get('user.tagfs.tags'))

    def statfs(self, path):
        stv = os.statvfs('./')
        return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
            'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
            'f_frsize', 'f_namemax'))

    def fsync(self, path, datasync, fh):
        if datasync != 0:
            return os.fdatasync(fh)
        else:
            return os.fsync(fh)

    def access(self, path, mode):
        def files():
            if not os.access(real(path), mode):
                raise FuseOSError(EACCES)
        def tags(): pass
        self.tags_operation(path, files, tags)            

    def getattr(self, path, fh=None):
        if path == './':
            return stat('.')
        def files(): return stat(real(path))
        def tags():  return self.tags[base(path)]
        return self.tags_operation(path, files, tags)

    def chmod(self, path, mode):
        def files(): os.chmod(real(path), mode)
        self.tags_operation(path, files)

    def chown(self, path, uid, gid):
        def files(): os.chown(real(path), uid, gid)
        self.tags_operation(path, files)
    
    def readlink(self, path):
        def files(): return os.readlink(real(path))
        return self.tags_operation(path, files)

    def mknod(self, path, mode, dev):
        def files(): os.mknod(real(path), mode, dev)
        self.tags_operation(path, files)

    def mkdir(self, path, mode):
        if not path2tags(path).issubset(self.tags):
            raise FuseOSError(ENOENT)
        os.mkdir(real(path), mode) # let the os generate a stat for us
        self.tags[base(path)] = stat(real(path))
        os.rmdir(real(path))
        self.update_fs_xattr()

    def rmdir(self, path):
        def files(): os.rmdir(real(path)) # this will result in the correct error (ENOENT/ENOTDIR)
        def tags():
            if any(base(path) in xattr2tags('./' + filename) for filename in os.listdir('.')):
                raise FuseOSError(ENOTEMPTY)
            else:
                del self.tags[base(path)]
                self.update_fs_xattr()
        self.tags_operation(path, files, tags)

    def readdir(self, path, fh):
        if path == '/':
            tags = set()
        else:
            tags = path2tags(path) | {base(path)}
        return ['.', '..'] + list(set(self.tags) - tags) + [
            filename.decode('utf-8') for filename in os.listdir('.')
                if tags.issubset(xattr2tags('./' + filename))]

    def link(self, link, source):
        def files():
            os.link(real(source), real(link))
            set_tags_xattr(real(link), path2tags(link))
        def tags(): raise FuseOSError(EPERM)
        self.tags_operation(source, files, tags)

    def unlink(self, path):
        def files(): os.unlink(real(source))
        def tags():  raise FuseOSError(EISDIR)
        self.tags_operation(path, files, tags)

    def symlink(self, link, source):
        if link != "" and source != "" and path2tags(link).issubset(xattr2tags(real(link))):
            if base(link) in self.tags:
                raise FuseOSError(EEXIST)
            else:
                os.symlink(source, real(link))
                set_tags_xattr(real(link), path2tags(link))
        else:
            raise FuseOSError(ENOENT)

    def rename(self, old, new):
        def files():
            os.rename(real(old), real(new))
            to_remove = path2tags(old) - path2tags(new)
            to_add    = path2tags(new) - path2tags(old)
            tags = (xattr2tags(real(new)) - to_remove) | to_add
            set_tags_xattr(real(new), tags)
        def tags(): self.tags[base(new)] = self.tags.pop(base(old))
        self.tags_operation(old, files, tags)

    def listxattr(self, path):
        def files(): return xattr(real(path)).list()
        return self.tags_operation(path, files)

    def getxattr(self, path, name):
        def files(): return xattr(real(path)).get(name)
        return self.tags_operation(path, files)

    def setxattr(self, path, name, value, options):
        def files(): xattr(real(path)).set(name, value, options)
        self.tags_operation(path, files)

    def removexattr(self, path, name):
        def files(): xattr(real(path)).remove(name)
        self.tags_operation(path, files)

    def utimens(self, path, times):
        def files(): os.utime(real(path), times)
        return self.tags_operation(path, files)

    def open(self, path, flags):
        def files(): return os.open(real(path), flags)
        def tags():  raise FuseOSError(EPERM)
        return self.tags_operation(path, files, tags)

    def create(self, path, mode):
        def files(): return os.open(real(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        def tags():  raise FuseOSError(EEXIST)
        return self.tags_operation(path, files, tags)

    def read(self, path, size, offset, fh):
        os.lseek(fh, offset, 0)
        return os.read(fh, size)

    def write(self, path, data, offset, fh):
        os.lseek(fh, offset, 0)
        return os.write(fh, data)

    def truncate(self, path, length, fh=None):
        def files():
            with open(real(path), 'r+') as f:
                f.truncate(length)
        def tags(): raise FuseOSError(EISDIR)
        return self.tags_operation(path, files, tags)

    def flush(self, path, fh):
        return os.fsync(fh)
    
    def release(self, path, fh):
        return os.close(fh)


if __name__ == '__main__':
    if len(argv) != 2:
        print('usage: %s <root>' % argv[0])
        exit(1)

    root_fd = os.open(os.path.realpath(argv[1]), os.O_RDONLY)
    fuse = FUSE(Tagfs(root_fd), argv[1], fsname='tagfs',
                foreground=True, nothreads=True, nonempty=True, allow_other=True, debug=True)

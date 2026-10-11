"""Kernel-enforced exclusion for this build's regular image files.

The lease checks the inode in the kernel, including users outside our PID/mount
namespace. /proc is used only for a readable project-QEMU inventory, never to
infer that an inaccessible descriptor is safe. Keep the same fd open throughout
all operations; closing another same-inode fd can drop POSIX record locks.
"""
from __future__ import annotations

import fcntl
import errno
import json
import os
from pathlib import Path
import signal
import stat
import tempfile


class ImageGuardError(RuntimeError):
    pass


def project_qemu_inventory(base: Path, image: Path) -> dict:
    count = 0
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            command = (process / 'cmdline').read_bytes()
            comm = (process / 'comm').read_text().strip()
            executable = Path(os.fsdecode(command.split(b'\0', 1)[0])).name
            count += 1
            if not (executable.startswith('qemu-system') or comm.startswith('qemu-system')):
                continue
            if not command:
                raise ImageGuardError(f'Cannot classify QEMU process {process.name} with an empty command.')
            if os.fsencode(str(base)) in command or os.fsencode(str(image)) in command:
                raise ImageGuardError(f'Project QEMU process {process.name} is still running; stop the VMs first.')
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as error:
            raise ImageGuardError(f'Cannot read process {process.name} for the QEMU inventory.') from error
    return {'project_qemu_stopped': True, 'readable_processes_checked': count,
            'scope': 'All processes visible in the mounted /proc; inode writer exclusion is enforced by the kernel lease'}


class ImageUseGuard:
    def __init__(self, fd: int, image: Path, base: Path, *, write: bool = False):
        self.fd = fd
        self.image = Path(image)
        self.base = Path(base)
        self.write = write
        self.lease_type = fcntl.F_WRLCK if write else fcntl.F_RDLCK
        self.initial = os.fstat(fd)
        self.broken = False
        self.active = False
        self.lease_attempted = False
        self.previous_handler = None
        self.publications = []
        self.inventory = {}

    def _identity(self) -> None:
        current = os.fstat(self.fd)
        named = self.image.lstat()
        expected = (self.initial.st_dev, self.initial.st_ino, self.initial.st_size, self.initial.st_uid)
        for actual in (current, named):
            if (not stat.S_ISREG(actual.st_mode)
                    or (actual.st_dev, actual.st_ino, actual.st_size, actual.st_uid) != expected):
                raise ImageGuardError('Image path/inode, size, ownership or regular-file identity changed.')
        if not self.write and (current.st_mtime_ns, current.st_ctime_ns) != (
                self.initial.st_mtime_ns, self.initial.st_ctime_ns):
            raise ImageGuardError('Read-only image changed during guarded verification.')

    def _lease_break(self, signum, frame) -> None:
        # Raising asynchronously can interrupt report rollback itself. Every
        # operation/checkpoint instead observes this flag and aborts normally.
        self.broken = True

    def __enter__(self):
        uid_line = next(line for line in Path('/proc/self/status').read_text().splitlines()
                        if line.startswith('Uid:'))
        fsuid = int(uid_line.split()[4])
        if self.initial.st_uid != fsuid:
            raise ImageGuardError('Image owner does not match this process filesystem UID.')
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL) & os.O_ACCMODE
        if flags != (os.O_RDWR if self.write else os.O_RDONLY):
            raise ImageGuardError('Guard requires an O_RDWR write fd or an O_RDONLY read fd.')
        self._identity()
        self.inventory = project_qemu_inventory(self.base, self.image)
        self.previous_handler = signal.signal(signal.SIGIO, self._lease_break)
        try:
            fcntl.fcntl(self.fd, fcntl.F_SETOWN, os.getpid())
            fcntl.fcntl(self.fd, fcntl.F_SETSIG, signal.SIGIO)
            fcntl.lockf(self.fd, (fcntl.LOCK_EX if self.write else fcntl.LOCK_SH) | fcntl.LOCK_NB,
                        0, 0, os.SEEK_SET)
            # A read lease refuses all existing writers; a write lease refuses
            # all other open descriptions. Unsupported/denied leases are fatal.
            self.lease_attempted = True
            fcntl.fcntl(self.fd, fcntl.F_SETLEASE, self.lease_type)
            self.active = True
            self.check(inventory=True)
            return self
        except BaseException:
            self._release()
            raise

    def check(self, *, inventory: bool = False) -> None:
        if not self.active or self.broken:
            raise ImageGuardError('Image lease is inactive or has received a break notification.')
        if fcntl.fcntl(self.fd, fcntl.F_GETLEASE) != self.lease_type:
            raise ImageGuardError('Image lease no longer has the required type; a break may be pending.')
        self._identity()
        if inventory:
            self.inventory = project_qemu_inventory(self.base, self.image)

    def receipt(self) -> dict:
        self.check()
        return {**self.inventory, 'owner_filesystem_uid_matched': True,
                'lease_type': 'write' if self.write else 'read', 'kernel_file_lease_obtained': True,
                'lease_break_detected': False, 'full_file_nonblocking_posix_record_lock_obtained': True}

    def publish_json(self, target: Path, value: dict, *, replace: bool = False) -> None:
        """Publish under the lease; roll back this publication if the guard fails."""
        self.check(inventory=True)
        target = Path(target)
        if target.is_symlink() or (target.exists() and not replace):
            raise ImageGuardError('Refusing to overwrite the report or follow a report symlink.')
        old_backup = None
        if target.exists():
            if not target.is_file():
                raise ImageGuardError('Previous report is not a regular file.')
            backup_fd, backup_name = tempfile.mkstemp(prefix=target.name + '.previous-', dir=target.parent)
            os.close(backup_fd)
            old_backup = Path(backup_name)
            old_backup.unlink()
            os.link(target, old_backup)
        try:
            temp_fd, temp_name = tempfile.mkstemp(prefix=target.name + '.guarded-', dir=target.parent)
        except BaseException:
            if old_backup is not None:
                old_backup.unlink(missing_ok=True)
            raise
        temporary = Path(temp_name)
        publication = None
        try:
            with os.fdopen(temp_fd, 'wb') as handle:
                self.check()
                handle.write((json.dumps(value, indent=2) + '\n').encode())
                handle.flush()
                self.check()
                os.fsync(handle.fileno())
                info = os.fstat(handle.fileno())
            self.check(inventory=True)
            publication = {'target': target, 'identity': (info.st_dev, info.st_ino), 'backup': old_backup}
            # Register before publication so SIGIO between link/replace and the
            # next Python instruction also triggers cleanup in __exit__.
            self.publications.append(publication)
            if replace:
                os.replace(temporary, target)
            else:
                os.link(temporary, target)
            self.check()
            directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                self.check()
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self.check()
        finally:
            temporary.unlink(missing_ok=True)
            if publication is None and old_backup is not None:
                old_backup.unlink(missing_ok=True)

    def _finish_publications(self, successful: bool) -> None:
        for publication in reversed(self.publications):
            target, identity, backup = publication['target'], publication['identity'], publication['backup']
            try:
                info = target.lstat()
            except FileNotFoundError:
                info = None
            try:
                if not successful and info is not None and (info.st_dev, info.st_ino) == identity:
                    if backup is None:
                        target.unlink()
                    else:
                        os.replace(backup, target)
            except OSError as error:
                # Never remove the only preserved old report after a failed
                # restoration. The caller must see failure and its location.
                preserved = str(backup) if backup is not None else '(no previous report)'
                try:
                    if (target.lstat().st_dev, target.lstat().st_ino) == identity:
                        target.unlink()
                except OSError:
                    pass
                raise ImageGuardError(f'Report rollback failed; preserved previous report: {preserved}') from error
            if backup is not None:
                try:
                    backup.unlink(missing_ok=True)
                except OSError as error:
                    # A failed final cleanup must not leave a new success
                    # publication after __exit__ reports failure.
                    if successful:
                        try:
                            current = target.lstat()
                            if (current.st_dev, current.st_ino) == identity:
                                os.replace(backup, target)
                        except OSError as rollback_error:
                            try:
                                if (target.lstat().st_dev, target.lstat().st_ino) == identity:
                                    target.unlink()
                            except OSError:
                                pass
                            raise ImageGuardError(f'Report cleanup/rollback failed; preserved backup: {backup}') from rollback_error
                    raise ImageGuardError('Report backup cleanup failed; new publication was rolled back.') from error
        self.publications.clear()

    def _release(self, *, restore_handler: bool = True) -> None:
        try:
            if self.lease_attempted:
                try:
                    fcntl.fcntl(self.fd, fcntl.F_SETLEASE, fcntl.F_UNLCK)
                except OSError as error:
                    # Kernel cleanup can return EAGAIN after a lease has
                    # already disappeared. Still try the unlock first:
                    # F_GETLEASE=UNLCK alone can mean a pending break.
                    if (error.errno != errno.EAGAIN
                            or fcntl.fcntl(self.fd, fcntl.F_GETLEASE) != fcntl.F_UNLCK):
                        raise
        finally:
            self.active = False
            self.lease_attempted = False
            try:
                fcntl.lockf(self.fd, fcntl.LOCK_UN, 0, 0, os.SEEK_SET)
            finally:
                if restore_handler and self.previous_handler is not None:
                    signal.signal(signal.SIGIO, self.previous_handler)
                    self.previous_handler = None

    def __exit__(self, exc_type, exc_value, traceback):
        # Keep rollback state until lease release succeeds. Blocking SIGIO
        # makes final check/release/rollback immune to asynchronous exceptions;
        # pending notifications still make the operation fail closed.
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGIO})
        previous_handler = self.previous_handler
        failure = None
        success = exc_type is None
        try:
            if success:
                try:
                    self.check(inventory=True)
                except BaseException as error:
                    success = False
                    failure = error
            try:
                self._release(restore_handler=False)
            except BaseException as error:
                success = False
                failure = error
            while signal.SIGIO in signal.sigpending():
                signal.sigwait({signal.SIGIO})
                self.broken = True
            if self.broken:
                success = False
                failure = failure or ImageGuardError('Image lease break detected; no success report may remain.')
            self._finish_publications(success)
        finally:
            if previous_handler is not None:
                signal.signal(signal.SIGIO, previous_handler)
            self.previous_handler = None
            signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        if failure is not None:
            raise failure
        return False

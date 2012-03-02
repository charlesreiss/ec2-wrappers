import os
import pwd
import fcntl
import datetime
import errno

from cs61cpaths import LOG_FILE

FAKE_MODE = False

def audit_log(message):
    fh = open(LOG_FILE, 'a')
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    fh.write(
        "%s: %s: %s\n" % (
            datetime.datetime.now().isoformat(),
            real_username(),
            message.replace("\n", '\\n')
        )
    )
    fh.close

def real_username():
    if FAKE_MODE:
        return os.environ['REAL_USERNAME']
    else:
        return pwd.getpwuid(os.getuid()).pw_name


def safe_open_write(the_file, may_overwrite=False):
    real_uid = os.getuid()
    effective_uid = os.geteuid()
    os.setreuid(effective_uid, real_uid)
    if may_overwrite:
        print "Writing %s (possibly overwriting)..." % (the_file)
    else:
        print "Writing %s (if it doesn't exist)..." % (the_file)
    try:
        try:
            if may_overwrite:
                fd = os.open(the_file, os.O_WRONLY | os.O_TRUNC | os.O_CREAT, 0600)
            else:
                fd = os.open(the_file, os.O_WRONLY | os.O_TRUNC | os.O_EXCL | os.O_CREAT, 0600)
        except OSError, e:
            fd = -1
    finally:
        os.setreuid(real_uid, effective_uid)
    if fd != -1:
        fh = os.fdopen(fd, 'w')
        return fh
    else:
        return None

def home():
    if FAKE_MODE and 'FAKE_HOMEDIR' in os.environ:
        return os.environ['FAKE_HOMEDIR']
    else:
        return pwd.getpwuid(os.getuid()).pw_dir

def safe_make_dir(the_dir):
    print "Creating directory %s (if it doesn't exist)..."  % (the_dir)
    real_uid = os.getuid()
    effective_uid = os.geteuid()
    os.setreuid(effective_uid, real_uid)
    try:
        try:
            os.mkdir(the_dir)
        except OSError, e:
            if e.errno != errno.EISDIR and e.errno != errno.EEXIST:
                raise
    finally:
        os.setreuid(real_uid, effective_uid)

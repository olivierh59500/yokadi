import os
from cmd import Cmd
from collections import defaultdict
from difflib import Differ

from yokadi.core import basepaths
from yokadi.core import db
from yokadi.core.yokadioptionparser import YokadiOptionParser
from yokadi.sync.conflictingobject import BothModifiedConflictingObject
from yokadi.sync.pullui import PullUi
from yokadi.sync.vcsimplerrors import VcsImplError, NotFastForwardError
from yokadi.sync.syncmanager import SyncManager
from yokadi.sync import ALIASES_DIRNAME, PROJECTS_DIRNAME, TASKS_DIRNAME
from yokadi.ycli import tui


LOCAL_PREFIX = "L> "
REMOTE_PREFIX = "R> "

SHORTENED_SUFFIX = " (...)"
SHORTENED_TEXT_MAX_LENGTH = 40

# Keys are a tuple of (prompt, fieldName)
HEADER_INFO = {
    ALIASES_DIRNAME: ("Alias named \"{}\"", "name"),
    PROJECTS_DIRNAME: ("Project named \"{}\"", "name"),
    TASKS_DIRNAME: ("Task \"{}\"", "title"),
}


def printConflictObjectHeader(obj):
    prompt, fieldName = HEADER_INFO[obj.domain]
    value = "UNKNOWN"
    for dictName in "ancestor", "local", "remote":
        dct = getattr(obj, dictName)
        if dct:
            value = dct[fieldName]
            break
    prompt = prompt.format(value)
    print("\n# {}".format(prompt))


def prepareConflictText(local, remote):
    differ = Differ()
    diff = differ.compare(local.splitlines(keepends=True),
                          remote.splitlines(keepends=True))
    lines = []
    for line in diff:
        code = line[0]
        rest = line[2:]
        if rest[-1] != "\n":
            rest += "\n"
        if code == "?":
            continue
        if code == "-":
            lines.append(LOCAL_PREFIX + rest)
        elif code == "+":
            lines.append(REMOTE_PREFIX + rest)
        else:
            lines.append(rest)
    return "".join(lines)


def shortenText(text):
    """Takes a potentially multi-line text and returns a one-line, shortened version of it"""
    if text is None:
        return None
    cr = text.find("\n")
    if cr >= 0:
        text = text[:cr]
    if cr >= 0 or len(text) > SHORTENED_TEXT_MAX_LENGTH:
        text = text[:SHORTENED_TEXT_MAX_LENGTH - len(SHORTENED_SUFFIX)] + SHORTENED_SUFFIX
    return text


class TextPullUi(PullUi):
    def __init__(self):
        self._renames = defaultdict(list)

    def resolveConflicts(self, conflictingObjects):
        count = len(conflictingObjects)
        if count > 1:
            print("{} conflicts to resolve".format(count))
        else:
            print("One conflict to resolve")
        for obj in conflictingObjects:
            if isinstance(obj, BothModifiedConflictingObject):
                self.resolveBothModifiedObject(obj)
            else:
                self.resolveModifiedDeletedObject(obj)
            assert obj.isResolved()

    def resolveBothModifiedObject(self, obj):
        printConflictObjectHeader(obj)
        for key in set(obj.conflictingKeys):
            oldValue = obj.ancestor[key]
            print("\nConflict on \"{}\" key. Old value was \"{}\".\n".format(key, shortenText(oldValue)))
            answers = (
                (1, "Local value: \"{}\"".format(shortenText(obj.local[key]))),
                (2, "Remote value: \"{}\"".format(shortenText(obj.remote[key]))),
                (3, "Edit"),
            )
            answer = tui.selectFromList(answers, prompt="Which version do you want to keep".format(key), default=None)
            if answer == 1:
                value = obj.local[key]
            elif answer == 2:
                value = obj.remote[key]
            else:
                conflictText = prepareConflictText(obj.local[key], obj.remote[key])
                value = tui.editText(conflictText)
            obj.selectValue(key, value)

    def resolveModifiedDeletedObject(self, obj):
        printConflictObjectHeader(obj)
        if obj.remote:
            print("This object has been modified remotely and deleted locally")
            modified = obj.remote
        else:
            print("This object has been modified locally and deleted remotely")
            modified = obj.local
        for key, value in obj.ancestor.items():
            modifiedValue = modified[key]
            if value == modifiedValue:
                print("- {}: {}".format(key, value))
            else:
                print("- {}: {} => {}".format(key, value, modifiedValue))
        answers = (
            (1, "Local"),
            (2, "Remote")
        )
        answer = tui.selectFromList(answers, prompt="Which version do you want to keep", default=None)
        if answer == 1:
            obj.selectLocal()
        else:
            obj.selectRemote()

    def addRename(self, domain, old, new):
        self._renames[domain].append((old, new))

    def getRenames(self):
        return self._renames


class SyncCmd(Cmd):
    def __init__(self, dumpDir=None):
        self.dumpDir = dumpDir or os.path.join(basepaths.getCacheDir(), 'db')
        # As soon as we create a SyncManager, it monitors SQL events and start
        # dumping objects. We don't want this to happen if the user has not
        # initialized sync, so do not create a SyncManager if the dump dir does
        # not exist.
        if os.path.exists(self.dumpDir):
            self._createSyncManager()
        else:
            self.syncManager = None

    def do_s_sync(self, line):
        """Synchronize the database with the remote one. Get the latest
        changes, import them in the database and push local changes"""
        pullUi = TextPullUi()

        if self.syncManager.hasChangesToCommit():
            print("Committing local changes")
            self.syncManager.commitChanges("s_sync")

        while True:
            print("Pulling remote changes")
            self.syncManager.pull(pullUi=pullUi)
            if self.syncManager.hasChangesToImport():
                print("Importing changes")
                self.syncManager.importSinceLastSync(pullUi=pullUi)
            else:
                print("No remote changes")

            if not self.syncManager.hasChangesToPush():
                break
            print("Pushing local changes")
            try:
                self.syncManager.push()
                break
            except NotFastForwardError:
                print("Remote has other changes, need to pull again")
            except VcsImplError as exc:
                print("Failed to push: {}".format(exc))
                break
        self._printPullResults(pullUi)

    def do_s_init(self, line):
        """Create a dump directory."""
        self._createSyncManager()
        self.syncManager.initDumpRepository()
        self.syncManager.dump()
        print('Synchronization initialized, dump directory is in {}'.format(self.dumpDir))

    def do__s_dump(self, line):
        parser = self.parser__s_dump()
        args = parser.parse_args(line)
        if args.clear:
            self.syncManager.clearDump()
        self.syncManager.dump()

        print("Database dumped in {}".format(self.dumpDir))

    def parser__s_dump(self):
        parser = YokadiOptionParser()
        parser.usage = "_s_dump [options]"
        parser.description = "Dump database in the dump directory."
        parser.add_argument("--clear", dest="clear", default=False, action="store_true",
                            help="Clear the current dump before. This can be dangerous: any change present in the dump but not in the database will be lost.")
        return parser

    def do__s_pull(self, line):
        """Pull the changes from a remote repository in the dump directory.
        This command does *not* import the changes in the database. You need to call _s_import to do so."""
        pullUi = TextPullUi()
        self.syncManager.pull(pullUi=pullUi)
        self._printPullResults(pullUi)

    def do__s_import(self, line):
        parser = self.parser__s_import()
        args = parser.parse_args(line)
        pullUi = TextPullUi()
        if args.all:
            self.syncManager.importAll(pullUi=pullUi)
        else:
            self.syncManager.importSinceLastSync(pullUi=pullUi)
        self._printPullResults(pullUi)

    def parser__s_import(self):
        parser = YokadiOptionParser()
        parser.usage = "_s_import [options]"
        parser.description = "Import changes from the dump directory in the database."
        parser.add_argument("--all", dest="all", default=False, action="store_true",
                            help="Import all changes, regardless of the current synchronization status")
        return parser

    def do_s_push(self, line):
        """Push changes from the dump directory to the remote repository."""
        try:
            self.syncManager.push()
        except NotFastForwardError:
            print("Remote has other changes, you need to run _s_pull")
        except VcsImplError as exc:
            print("Failed to push: {}".format(exc))

    def do__s_check(self, line):
        """Check the dump integrity, report any error."""
        self.syncManager.checkDumpIntegrity()

    def _printPullResults(self, pullUi):
        renameDict = pullUi.getRenames()
        if not renameDict:
            return
        for domain, renames in renameDict.items():
            print("Elements renamed in {}".format(domain))
            for old, new in renames:
                print("- {} => {}".format(old, new))

    def _createSyncManager(self):
        self.syncManager = SyncManager(self.dumpDir, session=db.getSession())
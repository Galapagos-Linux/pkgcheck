# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: BSD/GPL2

import os.path
import operator, itertools
from pkgcore_checks import base, addons
from pkgcore.ebuild.repository import SlavedTree
from snakeoil.osutils import listdir_dirs
from snakeoil import mappings
from pkgcore.package.errors import MissingChksum

from snakeoil.demandload import demandload
demandload(globals(),
    'snakeoil.xml:escape',
    'snakeoil.osutils:listdir_files,pjoin',
    'snakeoil.lists:iflatten_instance',
    'pkgcore:fetch',
    'pkgcore.ebuild:misc',
)


class UnusedLocalFlagsResult(base.Result):

    """
    unused use.local.desc flag(s)
    """

    __slots__ = ("category", "package", "flags")

    threshold = base.package_feed

    def __init__(self, pkg, flags):
        base.Result.__init__(self)
        # tricky, but it works; atoms have the same attrs
        self._store_cp(pkg)
        self.flags = tuple(sorted(flags))

    @property
    def short_desc(self):
        return "use.local.desc unused flag(s) %s" % ', '.join(self.flags)


class UnusedLocalFlags(base.Template):

    """
    check for unused use.local.desc entries
    """

    feed_type = base.package_feed
    required_addons = (addons.UseAddon,)
    known_results = (UnusedLocalFlagsResult,) + addons.UseAddon.known_results

    def __init__(self, options, use_handler):
        base.Template.__init__(self, options)
        self.iuse_handler = use_handler

    def start(self):
        self.collapsed = misc.non_incremental_collapsed_restrict_to_data(
            self.iuse_handler.specific_iuse)

    def feed(self, pkgs, reporter):
        unused = set()
        for pkg in pkgs:
            unused.update(self.collapsed.iter_pull_data(pkg))
        for pkg in pkgs:
            unused.difference_update(self.iuse_handler.iuse_strip(pkg.iuse))
        if unused:
            reporter.add_report(UnusedLocalFlagsResult(pkg, unused))


class UnusedGlobalFlagsResult(base.Result):

    """
    unused use.desc flag(s)
    """

    __slots__ = ("flags",)

    threshold = base.repository_feed

    def __init__(self, flags):
        base.Result.__init__(self)
        # tricky, but it works; atoms have the same attrs
        self.flags = tuple(sorted(flags))

    @property
    def short_desc(self):
        return "use.desc unused flag(s): %s" % ', '.join(self.flags)


class UnusedGlobalFlags(base.Template):
    """
    check for unused use.desc entries
    """

    feed_type = base.versioned_feed
    scope = base.repository_scope
    required_addons = (addons.UseAddon,)
    known_results = (UnusedGlobalFlagsResult,) + addons.UseAddon.known_results

    def __init__(self, options, iuse_handler):
        base.Template.__init__(self, options)
        self.flags = None
        self.iuse_handler = iuse_handler

    def start(self):
        if not isinstance(self.options.target_repo,SlavedTree):
            self.flags = set(self.iuse_handler.global_iuse)

    def feed(self, pkg, reporter):
        if self.flags:
            self.flags.difference_update(self.iuse_handler.iuse_strip(pkg.iuse))

    def finish(self, reporter):
        if self.flags:
            reporter.add_report(UnusedGlobalFlagsResult(self.flags))
            self.flags.clear()


class UnusedLicenseReport(base.Result):
    """
    unused license(s) detected
    """

    __slots__ = ("licenses",)

    threshold = base.repository_feed

    def __init__(self, licenses):
        base.Result.__init__(self)
        self.licenses = tuple(sorted(licenses))

    @property
    def short_desc(self):
        return "unused license(s): %s" % ', '.join(self.licenses)


class UnusedLicense(base.Template):
    """
    unused license file(s) check
    """

    feed_type = base.versioned_feed
    scope = base.repository_scope
    required_addons = (addons.LicenseAddon,)
    known_results = (UnusedLicenseReport,)

    def __init__(self, options, licenses):
        base.Template.__init__(self, options)
        self.licenses = None

    def start(self):
        self.licenses = set()
        if isinstance(self.options.target_repo,SlavedTree):
            if 'licenses' in listdir_dirs(self.options.target_repo.location):
                self.licenses.update(listdir_files(pjoin(self.options.target_repo.location,"licenses")))
        else:
            for license_dir in self.options.license_dirs:
                self.licenses.update(listdir_files(license_dir))

    def feed(self, pkg, reporter):
        self.licenses.difference_update(iflatten_instance(pkg.license))

    def finish(self, reporter):
        if self.licenses:
            reporter.add_report(UnusedLicenseReport(self.licenses))
        self.licenses = None


def reformat_chksums(iterable):
    for chf, val1, val2 in iterable:
        if chf == "size":
            yield chf, val1, val2
        else:
            yield chf, "%x" % val1, "%x" % val2


class ConflictingChksums(base.Result):

    """
    checksum conflict detected between two files
    """

    __slots__ = ("category", "package", "version",
        "filename", "chksums", "others")

    threshold = base.versioned_feed

    _sorter = staticmethod(operator.itemgetter(0))

    def __init__(self, pkg, filename, chksums, others):
        base.Result.__init__(self)
        self._store_cpv(pkg)
        self.filename = filename
        self.chksums = tuple(sorted(reformat_chksums(chksums),
            key=self._sorter))
        self.others = tuple(sorted(others))

    @property
    def short_desc(self):
        return "conflicts with (%s) for file %s chksum %s" % (
            ', '.join(self.others), self.filename, self.chksums)


class MissingChksum(base.Result):
    """
    a file in the chksum data lacks required checksums
    """
    threshold = base.versioned_feed
    __slots__ = ('category', 'package', 'version', 'filename', 'missing',
        'existing')

    def __init__(self, pkg, filename, missing, existing):
        self._store_cpv(pkg)
        self.filename, self.missing = filename, tuple(sorted(missing))
        self.existing = tuple(sorted(existing))

    @property
    def short_desc(self):
        return "file %s is missing required chksums: %s; has chksums: %s" % \
            (self.filename, ', '.join(self.missing), ', '.join(self.existing))


class RequiredChksums(base.Template):

    """
    Check to ensure that the required manifest hashes are in use.
    """

    feed_type = base.package_feed
    known_results = (MissingChksum,)

    repo_grabber = operator.attrgetter("repo")

    def __init__(self, options):
        base.Template.__init__(self, options)
        self.required_checksums = mappings.defaultdictkey(
            lambda repo: frozenset(repo.config.manifests.hashes if hasattr(repo, 'config') else ()))
        self.seen_checksums = {}

    def feed(self, full_pkgset, reporter):
        # sort it by repo.
        for repo, pkgset in itertools.groupby(full_pkgset, self.repo_grabber):
            required_checksums = self.required_checksums[repo]
            pkgset = list(pkgset)
            manifest = pkgset[0].manifest

            seen = set()
            for pkg in pkgset:
                for f_inst in (iflatten_instance(pkg.fetchables, fetch.fetchable)):
                    if f_inst.filename in seen:
                        continue
                    missing = required_checksums.difference(f_inst.chksums)
                    if missing:
                        reporter.add_report(
                            MissingChksum(pkg, f_inst.filename, missing,
                                f_inst.chksums))
                    seen.add(f_inst.filename)
                    existing = self.seen_checksums.get(f_inst.filename)
                    if existing is None:
                        existing = ([pkg], dict(f_inst.chksums.iteritems()))
                        continue
                    seen_pkgs, seen_chksums = existing
                    for chf_type, value in seen_chksums.iteritems():
                        our_value = f_inst.chksums.get(chf_type)
                        if our_value is not None and our_value != value:
                            reporter.add_result(ConflictingChksums(
                                pkg, f_inst.filename, f_inst.chksums, seen_chksums))
                            break
                    else:
                        seen_chksums.update(f_inst.chksums)
                        seen_pkgs.append(pkg)

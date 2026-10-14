"""Start Ink/Stitch with a no-op thread catalog.

    python inkstitch_launcher.py /opt/inkstitch --extension=zip ... design.svg

Every Ink/Stitch run parses ~150 commercial thread palettes (each one twice)
just to label colours with the nearest brand thread name. We never use those
names - the factory colour list comes from our own spec sheet - and the
parsing cost ~20% of a compile, so the catalog is replaced before the
extension runs. Ink/Stitch's own source is left untouched.

Running from source also puts Ink/Stitch in "development" logging mode, which
writes a DEBUG log to <inkstitch dir>/inkstitch.log on every run. That
directory is read-only for the unprivileged service user (the run then dies
before compiling), so logging is switched to release-mode behaviour: off.
"""
import logging
import os
import runpy
import sys


class _NoThreadCatalog:
    def match_and_apply_palette(self, *args, **kwargs):
        return None

    def palette_names(self):
        return []

    def get_palette_by_name(self, name):
        return None

    def __iter__(self):
        return iter(())


def main() -> None:
    inkstitch_dir = os.path.abspath(sys.argv[1])
    script = os.path.join(inkstitch_dir, "inkstitch.py")
    sys.argv = [script, *sys.argv[2:]]
    sys.path.insert(0, inkstitch_dir)
    import lib.threads.catalog as catalog  # noqa: E402 - needs the Ink/Stitch dir on sys.path
    catalog._catalog = _NoThreadCatalog()  # ThreadCatalog() returns this singleton
    import lib.debug.logging as debug_logging  # noqa: E402

    def _release_logging(*_args, **_kwargs):
        logging.disable()
        debug_logging.disable_warnings()

    debug_logging.activate_logging = _release_logging
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()

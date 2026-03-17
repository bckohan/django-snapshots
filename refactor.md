* replace export with backup
* replace import with restore
* the group commands are always invoked even when a specific subcommand is being invoked so the _init helper methods are unnecessary - their logic should just appear on the group functions
* use asyncer package to simplify library by replacing _run_async - use task groups
* The media backup/restore Protocol should be a specialization of a generic directory backup/restore protocol (that can be reused for project specific directories)
* There is way too much artifact specific logic in finalize. Artifact specific logic should be avoided at all costs in finalize because this CLI is meant to be pluggable. By default it should be executing all subcommand plugins. For example see the tutorial at: https://django-typer.readthedocs.io/en/stable/extensions.html
* Artifact and implementation specific logic including further prompting should exist as much as possible in the subcommand functions.

.. include:: ../refs.rst

.. _how-to-admin:

=================================
Browse snapshots in the admin
=================================

django-snapshots includes a read-only Django admin page that lists the
snapshots in the configured storage and shows the details of each one.

Enable it
---------

The page is registered automatically when ``django.contrib.admin`` is in
``INSTALLED_APPS``. Run ``migrate`` so the ``snapshots.view_snapshot``
permission is created:

.. code-block:: bash

    python manage.py migrate

It appears on the admin index under **Snapshots**, at
``/admin/snapshots/snapshot/`` if the admin is mounted at ``/admin/``.

Who can see it
--------------

Superusers can always see it. To let other staff users see it, grant them the
**Snapshots | snapshot | Can view snapshot** permission
(``snapshots.view_snapshot``) directly or through a group.

What it shows
-------------

The list shows every readable snapshot in storage, newest first: its name,
when it was created, its format (``directory`` or ``archive``), the host and
Django version it was created with, its artifact types, and its artifact count
and total size. Snapshots whose manifest can't be read are left out, as they
are by ``snapshots list``.

Each snapshot links to a detail page with its full manifest: the Python and
Django versions, each artifact's file name, size, SHA-256 checksum and
metadata, and the ``pip freeze`` output captured when it was taken.

The pages only read from storage. Snapshots are created, restored and deleted
with the :ref:`management commands <tutorial-getting-started>`. If storage
can't be reached, the page shows the error instead of failing.

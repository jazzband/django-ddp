Change Log
==========

0.3.0
-----
* New DB field: Connection.server_addr -- **you must `migrate` your 
  database after upgrading**.
* Cleanup connections on shutdown (and purge associated subscriptions).
* Make `dddp` management command a subclass of the `runserver` command 
  so that `staticfiles` work as expected.
* Fix non-threadsafe failure in serializer - now using thread local 
  serializer instance.
* Fix `unsubscribe` from publications.
* Fix `/schema` method call.

0.2.5
-----
* Fix foreign key references in change messages to correctly reference 
  related object rather than source object.

0.2.4
-----
* Fix unicode rendering bug in DDP admin for ObjectMapping model.

0.2.3
-----
* Add `dddp` console script to start DDP service in more robust manner than using the dddp Django mangement command.

Change Log
==========

0.6.5
-----
* Use OrderedDict for geventwebsocket.Resource spec to support
  geventwebsockets 0.9.4 and above.

0.6.4
-----
* Send `removed` messages when client unsubscribes from publications.
* Add support for SSL options and --settings=SETTINGS args in dddp tool.
* Add `optional` and `label` attributes to ManyToManyField simple 
  schema.
* Check order of added/changed when emitting WebSocket frames rather 
  than when queuing messages.
* Move test projects into path that can be imported post install.

0.6.3
-----
* Refactor pub/sub functionality to fix support for `removed` messages.

0.6.2
-----
* Bugfix issue where DDP connection thread stops sending messages after 
  changing item that has subscribers for other connections but not self.

0.6.1
-----
* Fix `createUser` method to login new user after creation.
* Dump stack trace to console on error for easier debugging DDP apps.
* Fix handing of F expressions in object change handler.
* Send `nosub` in response to invalid subscription request.
* Per connection tracking of sent objects so changed/added sent 
  appropriately.

0.6.0
-----
* Add dddp.accounts module which provides password based auth mapping to
  django.contrib.auth module.
* Fix ordering of change messages and result message in method calls.

0.5.0
-----
* Drop relations to sessions.Session as WebSocket requests don't have
  HTTP cookie support -- **you must `migrate` your database after
  upgrading**.
* Refactor core to support custom serialization per collection, and
  correctly dispatch change messages per collection.
* Allow specifying specific collection for publication queries rather
  than assuming the auto-named default collections.
* Improve schema introspection to include options for fields with
  choices.
* Cleanup transaction handling to apply once at the entry point for DDP
  API calls.

0.4.0
-----
* Make live updates honour user_rel restrictions, also allow superusers
  to see everything.
* Support serializing objects that are saved with F expressions by
  reading field values for F expressions from database explicitly before
  serializing.
* Allow `fresh` connections from browsers that have not established a
  session in the database yet, also allow subscriptions from
  unauthenticated sessions (but don't show any data for collections that
  have user_rel items defined).  This change includes a schema change,
  remember to run migrations after updating.

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

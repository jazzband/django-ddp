"""
Django DDP authentication.

Matches Meteor 1.1 Accounts package: https://www.meteor.com/accounts

See http://docs.meteor.com/#/full/accounts_api for details of each method.
"""
from binascii import Error
import collections

from ejson import loads, dumps

from django.contrib import auth
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.auth.signals import user_login_failed
from django.dispatch import Signal
from django.utils import timezone

from dddp import THREAD_LOCAL as this, ADDED, REMOVED
from dddp.models import get_meteor_id, get_object, Subscription
from dddp.api import API, APIMixin, api_endpoint, Collection, Publication
from dddp.websocket import MeteorError


create_user = Signal(providing_args=['request', 'params'])
password_changed = Signal(providing_args=['request', 'user'])
forgot_password = Signal(providing_args=['request', 'user', 'token', 'expiry'])
password_reset = Signal(providing_args=['request', 'user'])


class Users(Collection):

    """Mimic `users` collection of Meteor's `accounts-password` package."""

    name = 'users'
    api_path_prefix = '/users/'
    model = auth.get_user_model()

    user_rel = [
        'pk',
    ]

    def serialize(self, obj, *args, **kwargs):
        """Serialize user as per Meteor accounts serialization."""
        # use default serialization, then modify to suit our needs.
        data = super(Users, self).serialize(obj, *args, **kwargs)

        # everything that isn't handled explicitly ends up in `profile`
        profile = data.pop('fields')
        profile.setdefault('name', obj.get_full_name())
        fields = data['fields'] = {
            'username': obj.get_username(),
            'emails': [],
            'profile': profile,
        }

        # clear out sensitive data
        for sensitive in [
                'password',
                'user_permissions_ids',
                'is_active',
                'is_staff',
                'is_superuser',
                'groups_ids',
        ]:
            profile.pop(sensitive, None)

        # createdAt (default is django.contrib.auth.models.User.date_joined)
        try:
            fields['createdAt'] = profile.pop('date_joined')
        except KeyError:
            date_joined = getattr(
                obj, 'get_date_joined',
                lambda: getattr(obj, 'date_joined', None)
            )()
            if date_joined:
                fields['createdAt'] = date_joined

        # email (default is django.contrib.auth.models.User.email)
        try:
            email = profile.pop('email')
        except KeyError:
            email = getattr(
                obj, 'get_email',
                lambda: getattr(obj, 'email', None)
            )()
        if email:
            fields['emails'].append({'address': email, 'verified': True})

        return data

    @staticmethod
    def deserialize_profile(user, profile, key_prefix='', pop=False):
        """De-serialize user profile fields into concrete model fields."""
        result = {}
        if pop:
            getter = profile.pop
        else:
            getter = profile.get

        def prefixed(name):
            """Return name prefixed by `key_prefix`."""
            return '%s%s' % (key_prefix, name)

        for key in profile.keys():
            val = getter(key)
            if key == prefixed('name'):
                result['full_name'] = val
            else:
                raise ValueError('Bad profile key: %r' % key)
        return result

    @api_endpoint
    def update(self, selector, update, options=None):
        """Update user data."""
        user = get_object(
            self.model, selector['_id'],
            pk=this.request.user.pk,
        )
        profile_update = self.deserialize_profile(
            user, update['$set'], key_prefix='profile.', pop=True,
        )
        if len(update['$set']) != 0:
            raise MeteorError(400, 'Invalid update fields: %r')

        for key, val in profile_update.items():
            setattr(user, key, val)
        user.save()


class LoginPublication(Publication):

    """Meteor Accounts emulation."""

    name = 'meteor.loginServiceConfiguration'

    queries = [
        (Users.model.objects.all(), 'users'),
    ]


class Auth(APIMixin):

    """Meteor Passwords emulation."""

    api_path_prefix = ''  # auth endpoints don't have a common prefix
    user_model = auth.get_user_model()

    def update_subs(self, new_user_id):
        """Update subs to send added/removed for collections with user_rel."""
        for sub in Subscription.objects.filter(connection=this.ws.connection):
            params = loads(sub.params_ejson)
            pub = API.get_pub_by_name(sub.publication)

            # calculate the querysets prior to update
            pre = collections.OrderedDict([
                (col, qs) for col, qs
                in API.sub_unique_objects(sub, params, pub)
            ])

            # save the subscription with the updated user_id
            sub.user_id = new_user_id
            sub.save()

            # calculate the querysets after the update
            post = collections.OrderedDict([
                (col, qs) for col, qs
                in API.sub_unique_objects(sub, params, pub)
            ])

            # first pass, send `added` for objs unique to `post`
            for col_post, qs in post.items():
                try:
                    qs_pre = pre[col_post]
                    qs = qs.exclude(pk__in=qs_pre.order_by().values('pk'))
                except KeyError:
                    # collection not included pre-auth, everything is added.
                    pass
                for obj in qs:
                    this.ws.send(col.obj_change_as_msg(obj, ADDED))

            # second pass, send `removed` for objs unique to `pre`
            for col_pre, qs in pre.items():
                try:
                    qs_post = post[col_pre]
                    qs = qs.exclude(pk__in=qs_post.order_by().values('pk'))
                except KeyError:
                    # collection not included post-auth, everything is removed.
                    pass
                for obj in qs:
                    this.ws.send(col.obj_change_as_msg(obj, REMOVED))

    @staticmethod
    def auth_failed(**credentials):
        """Consistent fail so we don't provide attackers with valuable info."""
        if credentials:
            user_login_failed.send_robust(
                sender=__name__,
                credentials=auth._clean_credentials(credentials),
            )
        raise MeteorError(403, 'Authentication failed.')

    def validated_user_and_session(self, token):
        """Resolve and validate auth token, returns user and session objects."""
        try:
            username, session_key, auth_hash = loads(token.decode('base64'))
        except (ValueError, Error):
            self.auth_failed(token=token)
        try:
            user = self.user_model.objects.get(**{
                self.user_model.USERNAME_FIELD: username,
            })
            user.backend = 'django.contrib.auth.backends.ModelBackend'
        except self.user_model.DoesNotExist:
            self.auth_failed(username=username, token=token)
        if user.get_session_auth_hash() != auth_hash:
            self.auth_failed(username=username, token=token)
        session = SessionStore(
            session_key=session_key,
        )
        if session.get_expiry_date() <= timezone.now():
            self.auth_failed(username=username, token=token)
        return (user, session)

    @staticmethod
    def get_user_token(user, session_key, expiry_date):
        """Return login token info for given user."""
        token = ''.join(
            dumps([
                user.get_username(),
                session_key,
                user.get_session_auth_hash(),
            ]).encode('base64').split('\n')
        )
        return {
            'id': get_meteor_id(user),
            'token': token,
            'tokenExpires': expiry_date,
        }

    @staticmethod
    def check_secure():
        """Check request, return False if using SSL or local connection."""
        if this.request.is_secure():
            return True  # using SSL
        elif this.request.META['REMOTE_ADDR'] in [
                'localhost',
                '127.0.0.1',
        ]:
            return True  # localhost
        raise MeteorError(403, 'Authentication refused without SSL.')

    def get_username(self, user):
        """Retrieve username from user selector."""
        if isinstance(user, basestring):
            return user
        elif isinstance(user, dict) and len(user) == 1:
            [(key, val)] = user.items()
            if key == 'username' or (key == self.user_model.USERNAME_FIELD):
                # username provided directly
                return val
            elif key == 'emails.address':
                email_field = getattr(self.user_model, 'EMAIL_FIELD', 'email')
                if self.user_model.USERNAME_FIELD == email_field:
                    return val  # email is username
                # find username by email
                return self.user_model.objects.values_list(
                    self.user_model.USERNAME_FIELD, flat=True,
                ).get(**{email_field: val})
            elif key in ('id', 'pk'):
                # find username by primary key (ID)
                return self.user_model.objects.values_list(
                    self.user_model.USERNAME_FIELD, flat=True,
                ).get(
                    pk=val,
                )
            else:
                raise MeteorError(400, 'Invalid user lookup: %r' % key)
        else:
            raise MeteorError(400, 'Invalid user expression: %r' % user)

    @staticmethod
    def get_password(password):
        """Return password in plain-text from string/dict."""
        if isinstance(password, basestring):
            # regular Django authentication - plaintext password... but you're
            # using HTTPS (SSL) anyway so it's protected anyway, right?
            return password
        else:
            # Meteor is trying to be smart by doing client side hashing of the
            # password so that passwords are "...not sent in plain text over the
            # wire".  This behaviour doesn't make HTTP any more secure - it just
            # gives a false sense of security as replay attacks and
            # code-injection are both still viable attack vectors for the
            # malicious MITM.  Also as no salt is used with hashing, the
            # passwords are vulnerable to rainbow-table lookups anyway.
            #
            # If you're doing security, do it right from the very outset.  Fors
            # web services that means using SSL and not relying on half-baked
            # security concepts put together by people with no security
            # background.
            #
            # We protest loudly to anyone who cares to listen in the server logs
            # until upstream developers see the light and drop the password
            # hashing mis-feature.
            raise MeteorError(
                400,
                "Outmoded password hashing, run "
                "`meteor add tysonclugg:accounts-secure` to fix.",
            )

    @api_endpoint('createUser')
    def create_user(self, params):
        """Register a new user account."""
        receivers = create_user.send(
            sender=__name__,
            request=this.request,
            params=params,
        )
        if len(receivers) == 0:
            raise MeteorError(501, 'Handler for `create_user` not registered.')
        user = receivers[0][1]
        user = auth.authenticate(
            username=user.get_username(), password=params['password'],
        )
        auth.login(this.request, user)
        self.update_subs(user.pk)
        return self.get_user_token(
            user=user,
            session_key=this.request.session.session_key,
            expiry_date=this.request.session.get_expiry_date(),
        )

    @api_endpoint
    def logout(self):
        """Logout current user."""
        auth.logout(this.request)
        self.update_subs(None)

    @api_endpoint
    def login(self, params):
        """Login either with resume token or password."""
        if 'password' in params:
            return self.login_with_password(params)
        elif 'resume' in params:
            return self.login_with_resume_token(params)
        else:
            self.auth_failed(**params)

    def login_with_password(self, params):
        """Authenticate using credentials supplied in params."""
        # never allow insecure login
        self.check_secure()

        username = self.get_username(params['user'])
        password = self.get_password(params['password'])

        user = auth.authenticate(username=username, password=password)
        if user is not None:
            # the password verified for the user
            if user.is_active:
                auth.login(this.request, user)
                self.update_subs(user.pk)
                this.request.session.save()
                return self.get_user_token(
                    user=user,
                    session_key=this.request.session.session_key,
                    expiry_date=this.request.session.get_expiry_date(),
                )

        # Call to `authenticate` was unable to verify the username and password.
        # It will have sent the `user_login_failed` signal, no need to pass the
        # `username` argument to auth_failed().
        self.auth_failed()

    def login_with_resume_token(self, params):
        """
        Login with existing resume token.

        Either the token is valid and the user is logged in, or the token is
        invalid and a non-specific ValueError("Login failed.") exception is
        raised - don't be tempted to give clues to attackers as to why their
        logins are invalid!
        """
        # never allow insecure login
        self.check_secure()

        # pull the username, session_key and session_auth_hash from the token
        user, session = self.validated_user_and_session(params['resume'])

        auth.login(this.request, user)
        self.update_subs(user.pk)
        this.request.session.save()
        return self.get_user_token(
            user=user,
            session_key=session.session_key,
            expiry_date=session.get_expiry_date(),
        )

    @api_endpoint('changePassword')
    def change_password(self, params):
        """Change password."""
        user = auth.authenticate(
            username=this.request.user.get_username(),
            password=self.get_password(params['oldPassword']),
        )
        if user is None:
            self.auth_failed()
        else:
            user.set_password(self.get_password(params['newPassword']))
            user.save()
            password_changed.send(
                sender=__name__,
                request=this.request,
                user=user,
            )

    @api_endpoint('forgotPassword')
    def forgot_password(self, params):
        """Request password reset email."""
        username = self.get_username(params['user'])
        try:
            user = self.user_model.objects.get(**{
                self.user_model.USERNAME_FIELD: username,
            })
        except self.user_model.DoesNotExist:
            self.auth_failed()

        expiry_date = this.request.session.get_expiry_date()
        token = self.get_user_token(
            user=user, session_key=this.request.session.session_key,
            expiry_date=expiry_date,
        )

        forgot_password.send(
            sender=__name__,
            user=user,
            token=token,
            request=this.request,
            expiry_date=expiry_date,
        )

    @api_endpoint('resetPassword')
    def reset_password(self, params):
        """Reset password using a token received in email then logs user in."""
        user, _ = self.validated_user_and_session(params['token'])
        user.set_password(params['newPassword'])
        user.save()
        auth.login(this.request, user)
        self.update_subs(user.pk)


API.register([Users, LoginPublication, Auth])

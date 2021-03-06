from flask import g, json, jsonify, request
from flask_classy import FlaskView, route
from sqlalchemy.exc import IntegrityError, DBAPIError
from sqlalchemy.orm.exc import NoResultFound
from werkzeug.exceptions import BadRequest, NotFound

from app.authorization import login_required
import app.database
import app.queue
from app.rest import get_int_arg, get_paging_arguments, \
                     get_sort_arguments, isodate, url_for
from model import Avatar, Post, Profile, Label
from model.profile import avatar_join_profile, profile_join_self
import worker


class ProfileView(FlaskView):
    ''' Data about social media profiles. '''

    decorators = [login_required]

    def get(self, id_):
        '''
        .. http:get:: /api/profile/(int:id_)

            Get the profile identified by `id`.

            **Example Response**

            .. sourcecode:: json

                {
                    "avatar_url": "https://quickpin/api/file/1",
                    "avatar_thumb_url": "https://quickpin/api/file/2",
                    "description": "A human being.",
                    "follower_count": 71,
                    "friend_count": 28,
                    "id": 1,
                    "is_stub": false,
                    "is_interesting": false,
                    "join_date": "2012-01-30T15:11:35",
                    "labels": [
                        {
                            "id": 1,
                            "name": "male"
                        },
                    ],
                    "last_update": "2015-08-18T10:51:16",
                    "location": "Washington, DC",
                    "name": "John Doe",
                    "post_count": 1666,
                    "private": false,
                    "score": "-2.0621606863",
                    "site": "twitter",
                    "site_name": "Twitter",
                    "time_zone": "Central Time (US & Canada)",
                    "upstream_id": "11009418",
                    "url": "https://quickpin/api/profile/1",
                    "username": "mehaase",
                    "usernames": [
                        {
                            "end_date": "2012-06-30T15:00:00",
                            "start_date": "2012-01-01T12:00:00",
                            "username": "mehaase"
                        },
                        ...
                    ]
                }

            :<header Content-Type: application/json
            :<header X-Auth: the client's auth token

            :>header Content-Type: application/json
            :>json str avatar_url: URL to the user's current avatar
            :>json str avatar_thumb_url: URL to a 32x32px thumbnail of the user's
                current avatar
            :>json str description: profile description
            :>json int follower_count: number of followers
            :>json int friend_count: number of friends (a.k.a. followees)
            :>json int id: unique identifier for profile
            :>json bool is_stub: indicates that this is a stub profile, e.g.
                related to another profile but has not been fully imported
            :>json bool is_interesting: indicates whether this profile has been
                marked as interesting. The value can be null.
            :>json str join_date: the date this profile joined its social network
                (ISO-8601)
            :>json list labels: list of labels for this profile
            :>json int label[n].id: the unique id for this label
            :>json str label[n].name: the label
            :>json str last_update: the last time that information about this
                profile was retrieved from the social media site (ISO-8601)
            :>json str location: geographic location provided by the user, as free
                text
            :>json str name: the full name provided by this user
            :>json int note[n].body: the text body of of the note
            :>json str note[n].category: the category of the note.
            :>json str note[n].created_at: time at which the note was created.
            :>json int post_count: the number of posts made by this profile
            :>json bool private: true if this is a private account (i.e. not world-
                readable)
            :>json str score: user defined score for this profile
            :>json str site: machine-readable site name that this profile belongs to
            :>json str site_name: human-readable site name that this profile belongs
                to
            :>json str time_zone: the user's provided time zone as free text
            :>json str upstream_id: the user ID assigned by the social site
            :>json str url: URL endpoint for retriving more data about this profile
            :>json str username: the current username for this profile
            :>json list usernames: list of known usernames for this profile
            :>json str usernames[n].end_date: the last known date this username was
                used for this profile
            :>json str usernames[n].start_date: the first known date this username
                was used for this profile
            :>json str usernames[n].username: a username used for this profile

            :status 200: ok
            :status 400: invalid argument[s]
            :status 401: authentication required
            :status 404: user does not exist
        '''

        # Get profile.
        id_ = get_int_arg('id_', id_)

        try:
            profile, avatar = g.db.query(Profile, Avatar) \
                                  .outerjoin(Profile.current_avatar) \
                                  .filter(Profile.id == id_).one()
        except NoResultFound:
            raise NotFound("Profile '%s' does not exist." % id_)

        response = profile.as_dict()
        response['url'] = url_for('ProfileView:get', id_=profile.id)

        # Create usernames list.
        usernames = list()

        for username in profile.usernames:
            if username.end_date is not None:
                end_date = username.end_date.isoformat()
            else:
                end_date = None

            if username.start_date is not None:
                start_date = username.start_date.isoformat()
            else:
                start_date = None

            usernames.append({
                'end_date': end_date,
                'username': username.username,
                'start_date': start_date,
            })

        response['usernames'] = usernames

        # Create avatar attributes.
        if avatar is not None:
            response['avatar_url'] = url_for(
                'FileView:get',
                id_=avatar.file.id
            )
            response['avatar_thumb_url'] = url_for(
                'FileView:get',
                id_=avatar.thumb_file.id
            )
        else:
            response['avatar_url'] = url_for(
                'static',
                filename='img/default_user.png'
            )
            response['avatar_thumb_url'] = url_for(
                'static',
                filename='img/default_user_thumb.png'
            )

        # Send response.
        return jsonify(**response)

    @route('/<id_>/posts')
    def get_posts(self, id_):
        '''
        Return an array of posts by this profile.

        **Example Response**

        .. sourcecode:: json

            {
              "posts": [
                {
                  "content": "If your #Tor relay is stolen or you lose control of it, please report it so we can blacklist it: https://t.co/imVnrh1FbD @TorProject",
                  "id": 4,
                  "language": "en",
                  "last_update": "2015-08-19T18:17:07",
                  "location": [
                    null,
                    null
                  ],
                  "upstream_created": "2014-11-07T16:24:05",
                  "upstream_id": "530878388605423616"
                },
                ...
              ],
              "username": "johndoe"
            }

        :<header Content-Type: application/json
        :<header X-Auth: the client's auth token
        :query page: the page number to display (default: 1)
        :query rpp: the number of results per page (default: 10)

        :>header Content-Type: application/json
        :>json list posts: List of post objects.
        :>json str posts[n].content: Text content of the post.
        :>json int posts[n].id: Unique identifier for post.
        :>json str posts[n].language: Language of post, e.g. 'en'.
        :>json str posts[n].last_update: The date and time that this record was
            updated from the social media site.
        :>json str posts[n].location: 2-element array of longitude and latitude.
        :>json str posts[n].upstream_created: The date this was posted.
        :>json str posts[n].upstream_id: The unique identifier assigned by the
            social media site.
        :>json str username: Username of the requested profile
        :>json str site_name: Site name associated with the requested profile
        :>json int total_count: Total count of all posts by this profile, not
            just those displayed on this page

        :status 200: ok
        :status 400: invalid argument[s]
        :status 401: authentication required
        :status 404: user does not exist
        '''

        page, results_per_page = get_paging_arguments(request.args)
        profile = g.db.query(Profile).filter(Profile.id == id_).first()

        if profile is None:
            raise NotFound('No profile exists for id={}.'.format(id_))

        posts = list()
        post_query = g.db.query(Post) \
                         .filter(Post.author_id == id_)

        total_count = post_query.count()

        post_query = post_query.order_by(Post.upstream_created.desc()) \
                               .limit(results_per_page) \
                               .offset((page - 1) * results_per_page)

        for post in post_query:
            post_dict = {
                'content': post.content,
                'id': post.id,
                'language': post.language,
                'last_update': isodate(post.last_update),
                'location': (post.longitude, post.latitude),
                'upstream_created': isodate(post.upstream_created),
                'upstream_id': post.upstream_id,
            }

            if len(post.attachments) > 0:
                attachment = post.attachments[0]

                post_dict['attachment'] = {
                    'mime': attachment.mime,
                    'name': attachment.name,
                    'url': url_for('FileView:get', id_=attachment.id)
                }

            posts.append(post_dict)

        return jsonify(
            posts=posts,
            site_name=profile.site_name(),
            total_count=total_count,
            username=profile.username
        )

    @route('/<id_>/posts/fetch')
    def get_older_posts(self, id_):
        '''
        Request fetching of older posts by this profile.

        **Example Response**

        .. sourcecode:: json

            {
            "message": "Fetching older posts for profile ID 22."
            }


        :>header Content-Type: application/json
        :>json str message: API request confirmation message

        :status 202: accepted for background processing
        :status 400: invalid argument[s]
        :status 401: authentication required
        :status 404: profile does not exist
        '''
        profile = g.db.query(Profile).filter(Profile.id == id_).first()

        if profile is None:
            raise NotFound('No profile with id={}.'.format(id_))

        app.queue.schedule_posts(profile, recent=False)

        message = "Fetching older posts for profile ID {} " \
                  .format(profile.id)

        response = jsonify(message=message)
        response.status_code = 202

        return response

    @route('/<id_>/relations/<reltype>')
    def get_relations(self, id_, reltype):
        '''
        Return an array of profiles that are related to the specified profile
        by `reltype`, either "friends" or "followers".

        **Example Response**

        .. sourcecode:: json

            {
              "relations": [
                {
                  "avatar_thumb_url": "https://quickpin/api/file/1",
                  "id": 3,
                  "url": "https://quickpin/api/profile/3",
                  "username": "rustlang"
                },
                {
                  "avatar_thumb_url": "https://quickpin/api/file/2",
                  "id": 4,
                  "url": "https://quickpin/api/profile/4",
                  "username": "ORGANICBUTCHER"
                },
                ...
            }

        :>header Content-Type: application/json
        :>json list relations: list of related profiles.
        :>json int relations[n].avatar_thumb_url: a URL to a thumbnail of the
            user's current avatar
        :>json int relations[n].id: Unique identifier for relation's profile.
        :>json str relations[n].url: The URL to fetch this relation's profile.
        :>json str relations[n].username: This relation's username.
        :>json int total_count: Total count of all related profiles, not just
            those on the current page.

        :<header Content-Type: application/json
        :<header X-Auth: the client's auth token
        :query page: the page number to display (default: 1)
        :query rpp: the number of results per page (default: 10)

        :>header Content-Type: application/json
        :>json object relations Array of related profiles.
        :>json int relations[n].avatar_thumb_url a URL to a thumbnail of the
            user's current avatar
        :>json int relations[n].id Unique identifier for relation's profile.
        :>json str relations[n].url The URL to fetch this relation's profile.
        :>json str relations[n].username This relation's username.
        :>json int total_count Total count of all related profiles, not just
            those on the current page.

        :status 200: ok
        :status 400: invalid argument[s]
        :status 401: authentication required
        :status 404: user does not exist
        '''

        page, results_per_page = get_paging_arguments(request.args)
        profile = g.db.query(Profile).filter(Profile.id == id_).first()

        if profile is None:
            raise NotFound('No profile with id={}.'.format(id_))

        if reltype == 'friends':
            join_cond = (profile_join_self.c.friend_id == Profile.id)
            filter_cond = (profile_join_self.c.follower_id == id_)
        elif reltype == 'followers':
            join_cond = (profile_join_self.c.follower_id == Profile.id)
            filter_cond = (profile_join_self.c.friend_id == id_)
        else:
            raise NotFound('Invalid relation type "{}".'.format(reltype))

        relationship_query = \
            g.db.query(Profile, Avatar) \
                .outerjoin(Profile.current_avatar) \
                .join(profile_join_self, join_cond) \
                .filter(filter_cond)

        total_count = relationship_query.count()

        relationship_query = relationship_query \
            .order_by(Profile.is_stub, Profile.username) \
            .limit(results_per_page) \
            .offset((page - 1) * results_per_page)

        relations = list()

        for relation, avatar in relationship_query:
            if avatar is not None:
                thumb_url = url_for(
                    'FileView:get',
                    id_=avatar.thumb_file.id
                )
            else:
                thumb_url = url_for(
                    'static',
                    filename='img/default_user_thumb.png'
                )

            relations.append({
                'avatar_thumb_url': thumb_url,
                'id': relation.id,
                'url': url_for('ProfileView:get', id_=relation.id),
                'username': relation.username,
            })

        return jsonify(
            site_name=profile.site_name(),
            relations=relations,
            total_count=total_count,
            username=profile.username
        )

    @route('/<id_>/relations/fetch')
    def get_more_relations(self, id_):
        '''
        Schedule jobs to fetch more relations for this profile.

        **Example Response**

        .. sourcecode:: json

            {
                "message": 
                    "Fetching more friends & followers for profile ID 22.",
            }

        :>header Content-Type: application/json
        :<header X-Auth: the client's auth token

        :>header Content-Type: application/json
        :>json str message: API request confirmation message

        :status 202: accepted for background processing
        :status 400: invalid argument[s]
        :status 401: authentication required
        :status 404: profile does not exist
        '''
        profile = g.db.query(Profile).filter(Profile.id == id_).first()

        if profile is None:
            raise NotFound('No profile with id={}.'.format(id_))

        app.queue.schedule_relations(profile)

        message = "Fetching more friends & followers posts for profile ID {} " \
                  .format(profile.id)

        response = jsonify(message=message)
        response.status_code = 202

        return response

    def index(self):
        '''
        Return an array of data about profiles.

        **Example Response**

        .. sourcecode:: json

            {
                "profiles": [
                    {
                        "avatar_url": "https://quickpin/api/file/5",
                        "avatar_thumb_url": "https://quickpin/api/file/6",
                        "description": "A human being.",
                        "follower_count": 12490,
                        "friend_count": 294,
                        "id": 5,
                        "is_stub": False,
                        "is_interesting": False,
                        "join_date": "2010-01-30T18:21:35",
                        "last_update": "2015-08-18T10:51:16",
                        "location": "Washington, DC",
                        "name": "John Q. Doe",
                        "post_count": 230,
                        "private": false,
                        "score": "-2.0621606863",
                        "site": "twitter",
                        "time_zone": "Central Time (US & Canada)",
                        "upstream_id": "123456",
                        "url": "https://quickpin/api/profile/5",
                        "username": "johndoe"
                    },
                    ...
                ],
                "total_count": 5
            }

        :<header Content-Type: application/json
        :<header X-Auth: the client's auth token
        :query page: the page number to display (default: 1)
        :query rpp: the number of results per page (default: 10)
        :query interesting: filter by whether profile is set as interesting
        :query label: comma seperated list of labels to filter by
        :query site: name of site to filter by
        :query stub: filter by whether profile is stub

        :>header Content-Type: application/json
        :>json list profiles: a list of profile objects
        :>json str profiles[n].avatar_url: a URL to the user's current avatar
            image
        :>json str profiles[n].avatar_thumb_url: a URL to a 32x32px thumbnail of
            the user's current avatar image
        :>json str profiles[n].description: profile description
        :>json int profiles[n].follower_count: number of followers
        :>json int profiles[n].friend_count: number of friends (a.k.a.
            followees)
        :>json int profiles[n].id: unique identifier for profile
        :>json bool profiles[n].is_stub: indicates that this is a stub profile,
            e.g. related to another profile but has not been fully imported (for
            this particular endpoint, is_stub will always be false)
        :>json bool is_interesting: indicates whether this profile has been
            tagged as interesting. The value can be null.
        :>json str profiles[n].join_date: the date this profile joined its
            social network (ISO-8601)
        :>json str profiles[n].last_update: the last time that information about
            this profile was retrieved from the social media site (ISO-8601)
        :>json str profiles[n].location: geographic location provided by the
            user, as free text
        :>json str profiles[n].name: the full name provided by this user
        :>json int profiles[n].post_count: the number of posts made by this
            profile
        :>json bool profiles[n].private: true if this is a private account (i.e.
            not world-readable)
        :>json str profiles[n].score: user-defined score for this profile
        :>json str profiles[n].site: machine-readable site name that this
            profile belongs to
        :>json str profiles[n].site_name: human-readable site name that this
            profile belongs to
        :>json str profiles[n].time_zone: the user's provided time zone as free
            text
        :>json str profiles[n].upstream_id: the user ID assigned by the social
            site
        :>json str profiles[n].url: URL endpoint for retriving more data about
            this profile
        :>json str profiles[n].username: the current username for this profile
        :>json int total_count: count of all profile objects, not just those on
            the current page

        :status 200: ok
        :status 400: invalid argument[s]
        :status 401: authentication required
        '''

        page, results_per_page = get_paging_arguments(request.args)
        allowed_sort_fields = {
            'score': Profile.score,
            'updated': Profile.last_update,
            'added': Profile.id
        }
        sort_arguments = get_sort_arguments(request.args,
                                            '-added',
                                            allowed_sort_fields)

        query = g.db.query(Profile, Avatar) \
                    .outerjoin(Profile.current_avatar)

        # Parse filter arguments
        is_stub = request.args.get('stub', None)
        site = request.args.get('site', None)
        is_interesting = request.args.get('interesting', None)
        labels = request.args.get('label', None)

        if site is not None:
            query = query.filter(Profile.site == site)

        if is_stub is not None:
            if is_stub == '1':
                query = query.filter(Profile.is_stub == True)
            elif is_stub == '0':
                query = query.filter(Profile.is_stub == False)

        if is_interesting is not None:
            if is_interesting == 'yes':
                query = query.filter(Profile.is_interesting == True)
            elif is_interesting == 'no':
                query = query.filter(Profile.is_interesting == False)
            elif is_interesting == 'unset':
                query = query.filter(Profile.is_interesting == None)

        if labels is not None:
            for label in labels.split(','):
                query = query.filter(
                    Profile.labels.any(Label.name==label.lower())
                )

        total_count = query.count()

        for argument in sort_arguments:
            query = query.order_by(argument)

        query = query.limit(results_per_page) \
                     .offset((page - 1) * results_per_page)

        profiles = list()

        for profile, avatar in query:
            data = profile.as_dict()
            data['url'] = url_for('ProfileView:get', id_=profile.id)

            if avatar is not None:
                data['avatar_url'] = url_for(
                    'FileView:get',
                    id_=avatar.file.id
                )
                data['avatar_thumb_url'] = url_for(
                    'FileView:get',
                    id_=avatar.thumb_file.id
                )
            else:
                data['avatar_url'] = url_for(
                    'static',
                    filename='img/default_user.png'
                )
                data['avatar_thumb_url'] = url_for(
                    'static',
                    filename='img/default_user_thumb.png'
                )

            profiles.append(data)

        return jsonify(
            profiles=profiles,
            total_count=total_count
        )

    def post(self):
        '''
        Request creation of new profiles.

        We don't know if a profile exists until we contact its social media
        site, and we don't want to do that on the main request thread. Instead,
        profiles are processed in the background and notifications are sent as
        profiles are discovered and scraped. Therefore, this endpoint does not
        return any new entities.

        **Example Request**

        .. sourcecode:: json

            {
                "profiles": [
                    {
                        "username": "johndoe",
                        "site": "instagram",
                        "stub": true,
                        "labels":  ["female", "american"]
                    },
                    {
                        "upstream_id": "2232324",
                        "site": "twitter"
                    },
                    ...
                ],
                "stub": true
            }

        **Example Response**

        .. sourcecode:: json

            {
                "message": "21 new profiles submitted."
            }

        :<header Content-Type: application/json
        :<header X-Auth: the client's auth token
        :<json list profiles: a list of profiles to create
        :<json str profiles[n].username: username of profile to create
        :<json str profiles[n].upstream_id: upstream id of profile to create
        :<json str profiles[n].site: machine-readable name of social media site
        :<json bool stub: whether to fetch profiles as stubs

        :>header Content-Type: application/json
        :>json int id: unique identifier for new profile
        :>json str username: username of new profile
        :>json str site: machine-readable name of profile's social media site
        :>json str site_name: human-readable name of profile's social media site
        :>json str url: URL endpoint for more information about this profile

        :status 202: accepted for background processing
        :status 400: invalid request body
        :status 401: authentication required
        '''
        labels = {}
        request_json = request.get_json()
        # Validate post data
        if request_json is None:
            raise BadRequest("Post request requires json data")

        if 'profiles' not in request_json:
            raise BadRequest("'profiles' is a required json dictionary key")

        if 'stub' in request_json:
            if not isinstance(request_json['stub'], bool):
                raise BadRequest("'stub' must be boolean.")
            else:
                stub = request_json['stub']
        else:
            stub = False

        for profile in request_json['profiles']:

            if 'username' not in profile and 'upstream_id' not in profile:
                raise BadRequest('Username or upstream_id required for all profiles.')

            if 'username' in profile:
                if profile['username'].strip() == '':
                    raise BadRequest('Username cannot be an empty string.')

            if 'upstream_id' in profile:
                if profile['upstream_id'].strip() == '':
                    raise BadRequest('Upstream ID cannot be an empty string.')

            if 'site' not in profile or profile['site'].strip() == '':
                raise BadRequest('Site is required for all profiles.')

            if profile['site'].strip() == '':
                raise BadRequest('Site cannot be an empty string.')

            if 'labels' in profile:
                if not isinstance(profile['labels'], list):
                    raise BadRequest('`labels` must be a list')
                else:
                    # Transform string labels into IDs.
                    profile['labels'] = [self._get_label_id(name) for name in profile['labels']]

        app.queue.schedule_profiles(request_json['profiles'], stub)
        count = len(request_json['profiles'])
        message = "{} new profile{} submitted." \
                  .format(count, 's' if count != 1 else '')
        response = jsonify(message=message)
        response.status_code = 202

        return response

    def put(self, id_):
        '''
        Update the profile identified by `id` with submitted data.

        The following attributes are modifiable:

           * is_interesting
           * labels
           * score

        **Example Request**

        .. sourcecode:: json

            {
                "is_interesting": true,
                "labels": [
                    {"name": "male"},
                    {"name": "british"},
                    ...
                ],
                "score": 2323.0,
                ...
            }

        **Example Response**

        .. sourcecode:: json

            {
                "avatar_url": "https://quickpin/api/file/1",
                "avatar_thumb_url": "https://quickpin/api/file/2",
                "description": "A human being.",
                "follower_count": 71,
                "friend_count": 28,
                "id": 1,
                "is_stub": false,
                "is_interesting": true,
                "join_date": "2012-01-30T15:11:35",
                "labels": [
                    {
                        "id": 1,
                        "name": "male"
                    },
                    {
                        "id": 2,
                        "name": "british"
                    },
                ],
                "last_update": "2015-08-18T10:51:16",
                "location": "Washington, DC",
                "name": "John Doe",
                "post_count": 1666,
                "private": false,
                "score": "-2.0621606863",
                "site": "twitter",
                "site_name": "Twitter",
                "time_zone": "Central Time (US & Canada)",
                "upstream_id": "11009418",
                "url": "https://quickpin/api/profile/1",
                "username": "mehaase",
                "usernames": [
                    {
                        "end_date": "2012-06-30T15:00:00",
                        "start_date": "2012-01-01T12:00:00",
                        "username": "mehaase"
                    },
                    ...
                ]
            }

        :<header Content-Type: application/json
        :<header X-Auth: the client's auth token
        :<json bool is_interesting: whether profile is marked as interesting
        :<json list labels: list of profile labels
        :<json float score: profile score

        :>header Content-Type: application/json
        :>json str avatar_url: URL to the user's current avatar
        :>json str avatar_thumb_url: URL to a 32x32px thumbnail of the user's
            current avatar
        :>json str description: profile description
        :>json int follower_count: number of followers
        :>json int friend_count: number of friends (a.k.a. followees)
        :>json int id: unique identifier for profile
        :>json bool is_stub: indicates that this is a stub profile, e.g.
            related to another profile but has not been fully imported
        :>json bool is_interesting: indicates whether this profile has been
            marked as interesting. The value can be null.
        :>json str join_date: the date this profile joined its social network
            (ISO-8601)
        :>json list labels: list of labels for this profile
        :>json int label[n].id: the unique id for this label
        :>json str label[n].name: the label
        :>json str last_update: the last time that information about this
            profile was retrieved from the social media site (ISO-8601)
        :>json str location: geographic location provided by the user, as free
            text
        :>json str name: the full name provided by this user
        :>json int note[n].id: the unique id for this note
        :>json int note[n].category: the user-defined category of this note
        :>json int note[n].body: the user-defined text-body of this note
        :>json int post_count: the number of posts made by this profile
        :>json bool private: true if this is a private account (i.e. not world-
            readable)
        :>json str score: user-defined score for this profile. Can be null.
        :>json str site: machine-readable site name that this profile belongs to
        :>json str site_name: human-readable site name that this profile belongs
            to
        :>json str time_zone: the user's provided time zone as free text
        :>json str upstream_id: the user ID assigned by the social site
        :>json str url: URL endpoint for retriving more data about this profile
        :>json str username: the current username for this profile
        :>json list usernames: list of known usernames for this profile
        :>json str usernames[n].end_date: the last known date this username was
            used for this profile
        :>json str usernames[n].start_date: the first known date this username
            was used for this profile
        :>json str usernames[n].username: a username used for this profile

        :status 202: accepted for background processing
        :status 400: invalid request body
        :status 401: authentication required
        '''

        redis = worker.get_redis()

        # Get profile.
        id_ = get_int_arg('id_', id_)

        profile, avatar = g.db.query(Profile, Avatar) \
                              .outerjoin(Profile.current_avatar) \
                              .filter(Profile.id == id_).first()

        if profile is None:
            raise NotFound("Profile '%s' does not exist." % id_)

        request_json = request.get_json()

        # Validate put data and set attributes
        # Only 'is_interesting', 'score', and 'labels' are modifiable
        if 'is_interesting' in request_json:
            if isinstance(request_json['is_interesting'], bool):
                profile.is_interesting = request_json['is_interesting']
            elif request_json['is_interesting'] is None:
                profile.is_interesting = None
            else:
                raise BadRequest("'is_interesting' is a boolean (true or false.")

        if 'score' in request_json:
            if request_json['score'] is None:
                profile.score = None
            else:
                try:
                    profile.score = float(request_json['score'])
                except:
                    raise BadRequest("'score' must be a decimal number.")


        # labels expects the string 'name' rather than id, to avoid the need to
        # create labels before adding them.
        if 'labels' in request_json:
            labels = []
            if isinstance(request_json['labels'], list):
                for label_json in request_json['labels']:
                    if 'name' in label_json:
                        label = g.db.query(Label) \
                                    .filter(Label.name==label_json['name']) \
                                    .first()
                        if label is None:
                            try:
                                label = Label(
                                    name=label_json['name'].lower().strip()
                                )

                                g.db.add(label)
                                g.db.flush()

                                redis.publish(
                                    'label',
                                    json.dumps(label.as_dict())
                                )
                            except IntegrityError:
                                g.db.rollback()
                                raise BadRequest('Label could not be saved')
                            except AssertionError:
                                g.db.rollback()
                                raise BadRequest(
                                    '"{}" contains non-alphanumeric character'
                                    .format(
                                        label_json['name']
                                    )
                                )

                        labels.append(label)
                    else:
                        raise BadRequest("Label 'name' is required")

                profile.labels = labels
            else:
                raise BadRequest("'labels' must be a list")

        response = profile.as_dict()
        response['url'] = url_for('ProfileView:get', id_=profile.id)

        # Save the profile
        try:
            g.db.commit()
            redis.publish('profile', json.dumps(profile.as_dict()))
        except DBAPIError as e:
            g.db.rollback()
            raise BadRequest('Profile could not be saved')

        # Create usernames list.
        usernames = list()

        for username in profile.usernames:
            if username.end_date is not None:
                end_date = username.end_date.isoformat()
            else:
                end_date = None

            if username.start_date is not None:
                start_date = username.start_date.isoformat()
            else:
                start_date = None

            usernames.append({
                'end_date': end_date,
                'username': username.username,
                'start_date': start_date,
            })

        response['usernames'] = usernames

        # Create avatar attributes.
        if avatar is not None:
            response['avatar_url'] = url_for(
                'FileView:get',
                id_=avatar.file.id
            )
            response['avatar_thumb_url'] = url_for(
                'FileView:get',
                id_=avatar.thumb_file.id
            )
        else:
            response['avatar_url'] = url_for(
                'static',
                filename='img/default_user.png'
            )
            response['avatar_thumb_url'] = url_for(
                'static',
                filename='img/default_user_thumb.png'
            )

        # Send response.
        return jsonify(**response)

    @route('/<id_>/update')
    def update_profile(self, id_):
        '''
        Request new data from social site API for profile identified by `id`.

        **Example Response**

        .. sourcecode:: json

            {
            "message": "Updating profile ID 22 (site: twitter, upstream_id: 20609518, username: dalailama)."
            }


        :<header Content-Type: application/json
        :<header X-Auth: the client's auth token

        :>header Content-Type: application/json
        :>json str message: API request confirmation message

        :status 202: accepted for background processing
        :status 400: invalid argument[s]
        :status 401: authentication required
        :status 404: profile does not exist
        '''
        profile = g.db.query(Profile).filter(Profile.id == id_).first()

        if profile is None:
            raise NotFound('No profile with id={}.'.format(id_))

        app.queue.schedule_profile_id( \
                                      profile.site, \
                                      profile.upstream_id, \
                                      profile.id)

        message = "Updating profile ID {} " \
                  "(site: {}, upstream_id: {}, username: {})." \
                  .format(profile.id, \
                          profile.site, \
                          profile.upstream_id, \
                          profile.username)
        response = jsonify(message=message)
        response.status_code = 200

        return response

    @route('/<id_>/notes')
    def get_notes(self, id_):
        '''
        Return an array of all notes for this profile.

        **Example Response**

        .. sourcecode:: json

            {
                "notes": [
                    {
                        "id": 1,
                        "category": "user annotation",
                        "body": "This is an interesting) profile.",
                        "created_at": "2015-12-15T10:41:55.792492",
                        "url": "https://quickpin/api/note/1",
                    }
                    ...
                ],
                "total_count": 1
                "username: "hyperiongray",
                "sitename": twitter,
            }

        :<header Content-Type: application/json
        :<header X-Auth: the client's auth token
        :query page: the page number to display (default: 1)
        :query rpp: the number of results per page (default: 10)


        :>header Content-Type: application/json
        :>json list notes: list of profile note objects
        :>json int list[n].id: unique identifier for the note
        :>json str list[n].category: the user-defined category of this note
        :>json str list[n].body: the note
        :>json str list[n].created_at: the iso-formatted creation time of the note
        :>json str list[n].url: API endpoint URL for this note object
        :>json str total_count: the total number of notes for this profile
        :>json str username: the username of this profile
        :>json str sitename: the name of the social site the profile belongs to

        :status 200: ok
        :status 400: invalid argument[s]
        :status 401: authentication required
        '''

        # Parse paging arguments
        page, results_per_page = get_paging_arguments(request.args)
        profile = g.db.query(Profile).filter(Profile.id == id_).first()

        if profile is None:
            raise NotFound('No profile exists for id={}.'.format(id_))

        # Store the total result count before paging arguments limit result set
        total_count = len(profile.notes)
        # Add API endpoint URL for each note object
        notes = list()
        for note in profile.notes:
            data = note.as_dict()
            data['url'] = url_for('ProfileNoteView:get', id_=note.id)
            notes.append(data)

        # Apply paging arguments
        start = (page -1) * results_per_page
        end = start + results_per_page
        notes = notes[start:end]

        return jsonify(
            notes=notes,
            total_count=total_count,
            site_name=profile.site_name(),
            username=profile.username,
        )

    def delete(self, id_):
        """
        Delete the proile identified by `id`.

        **Example Response**

        .. sourcecode:: json

            {
                "message": "Profile ID `1234` deleted",
            }

        :<header Content-Type: application/json
        :<header X-Auth: the client's auth token

        :>header Content-Type: application/json
        :>json str message: the API response message

        :status 202: deleted
        :status 400: invalid request body
        :status 401: authentication required
        :status 404: profile does not exist
        """

        # Get profile.
        id_ = get_int_arg('id_', id_)
        profile = g.db.query(Profile).filter(Profile.id == id_).first()

        if profile is None:
            raise NotFound("Profile '%s' does not exist." % id_)

        # Delete profile
        g.db.delete(profile)
        try:
            g.db.commit()
        except DBAPIError as e:
            raise BadRequest('Database error: {}'.format(e))

        # Queue jobs to delete profile and posts from index
        app.queue.schedule_delete_profile_from_index(id_)
        app.queue.schedule_delete_profile_posts_from_index(id_)

        message = 'Profile ID `{}` deleted'.format(profile.id)
        response = jsonify(message=message)
        response.status_code = 202

        return response

    def _get_label_id(self, name):
        """
        Get or create a database label object, return the ID.
        """
        print('Label name to add:{}'.format(name), flush=True)
        db_session = worker.get_session()
        redis = worker.get_redis()
        label = db_session.query(Label).filter_by(name=name.lower().strip()).first()

        if label:
            print('Found Label :{}'.format(label.id), flush=True)
            return label.id
        else:
            label = Label(name=name.lower().strip())
            db_session.add(label)

            try:
                db_session.commit()
            except IntegrityError:
                db_session.rollback()
                raise
            except AssertionError:
                db_session.rollback()
                raise ValueError(
                    'Label "{}" contains non-alphanumeric character'
                    .format(name)
                )

            redis.publish('label', json.dumps(label.as_dict()))
            print('Created label :{}'.format(label.id), flush=True)
            return label.id

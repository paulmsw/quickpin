import base64
import dateutil.parser
import logging
import os
import subprocess
import sys
from textwrap import dedent

from sqlalchemy.engine import reflection
from sqlalchemy.schema import DropConstraint, DropTable, ForeignKeyConstraint, \
                              MetaData, Table

from app.config import get_path
import app.database
import cli
from model import Base, Configuration, File, Post, Profile, \
                  ProfileUsername, User
import model.user


class DatabaseCli(cli.BaseCli):
    ''' A tool for initializing the database. '''

    def _agnostic_bootstrap(self, config):
        ''' Bootstrap the Agnostic migrations system. '''

        env = {
            'AGNOSTIC_TYPE': 'postgres',
            'AGNOSTIC_HOST': config.get('database', 'host'),
            'AGNOSTIC_USER': config.get('database', 'username'),
            'AGNOSTIC_PASSWORD': config.get('database', 'password'),
            'AGNOSTIC_SCHEMA': config.get('database', 'database'),
            'AGNOSTIC_MIGRATIONS_DIR': get_path('migrations'),
            'LANG': os.environ['LANG'], # http://click.pocoo.org/4/python3/
            'PATH': os.environ['PATH'],
        }

        process = subprocess.Popen(
            ['agnostic', 'bootstrap'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env
        )
        process.wait()

        if process.returncode != 0:
            args = (process.returncode, process.stderr.read().decode('ascii'))
            self._logger.error('External process `agnostic bootstrap` failed ' \
                               'with error code (%d):\n%s' % args)
            sys.exit(1)

    def _create_fixtures(self, config):
        ''' Create fixture data. '''

        self._create_fixture_configurations(config)
        self._create_fixture_users(config)

    def _create_fixture_configurations(self, config):
        ''' Create configurations. '''

        session = app.database.get_session(self._db)

        piscina_ui_url = Configuration('piscina_ui_url', 'http://192.168.31.1:8080')
        session.add(piscina_ui_url)

        piscina_proxy_url = Configuration('piscina_proxy_url', 'http://192.168.31.1:8080')
        session.add(piscina_proxy_url)

        session.commit()

    def _create_fixture_users(self, config):
        ''' Create user fixtures. '''

        session = app.database.get_session(self._db)
        hash_algorithm = config.get('password_hash', 'algorithm')

        try:
            hash_rounds = int(config.get('password_hash', 'rounds'))
        except:
            raise ValueError('Configuration value password_hash.rounds must' \
                             ' be an integer: %s' % rounds)

        admin = User('admin')
        admin.agency = 'QuickPin'
        admin.name = 'Administrator'
        admin.is_admin = True
        admin.password_hash = model.user.hash_password(
            'MemexPass1',
            hash_algorithm,
            hash_rounds
        )
        session.add(admin)
        session.commit()

    def _create_samples(self, config):
        ''' Create sample data. '''

        self._create_sample_profiles(config)

    def _create_sample_profiles(self, config):
        ''' Create some sample profiles. '''

        session = app.database.get_session(self._db)
        sample_dir = os.path.join(os.path.dirname(__file__), 'sample-data')

        # Maurice Moss
        moss_twitter = Profile(
            site='twitter',
            upstream_id='12345',
            profile_name=ProfileName('maurice.moss', start_date='2014-04-01')
        )

        moss_twitter.names.append(ProfileName(
            'maurice',
            start_date='2013-06-01',
            end_date='2014-03-31'
        ))

        moss_twitter.names.append(ProfileName(
            'maurie',
            start_date='2013-02-15',
            end_date='2013-05-30'
        ))

        moss_twitter.posts.append(Post(
            content='Going to the grocery store.',
            post_date='2015-02-04 12:34:50',
            post_date_is_exact=True,
        ))

        post = Post(
            content='Love this band!.',
            post_date='2015-03-01',
            post_date_is_exact=False,
        )

        post.attachments.append(File(
            name='helloworld.txt',
            mime='text/plain',
            content='Hello world!\n\n'.encode('utf8')
        ))

        moss_twitter.posts.append(post)

        with open(os.path.join(sample_dir, 'moss.jpg'), 'rb') as moss_jpg:
            moss_twitter.avatars.append(File(
                name='jen-avatar.jpg',
                mime='image/jpeg',
                content=moss_jpg.read()
            ))

        moss_twitter.description = "I do IT at Reynholm Industries."
        moss_twitter.post_count = 1205
        moss_twitter.friend_count = 1
        moss_twitter.follower_count = 3
        moss_twitter.join_date = dateutil.parser.parse('2013-06-01')
        moss_twitter.join_date_is_exact = False

        session.add(moss_twitter)

        # Jen Barber
        jen_twitter = Profile(
            site='twitter',
            upstream_id='23456',
            profile_name=ProfileName('jen.barber', start_date='2013-11-12')
        )

        jen_twitter.names.append(ProfileName(
            'jenb',
            start_date='2013-06-14',
            end_date='2013-11-12'
        ))

        jen_twitter.names.append(ProfileName(
            'jenny',
            start_date='2013-03-15',
            end_date='2013-06-14'
        ))

        with open(os.path.join(sample_dir, 'jen.jpg'), 'rb') as jen_jpg:
            jen_twitter.avatars.append(File(
                name='moss-avatar.jpg',
                mime='image/jpeg',
                content=jen_jpg.read()
            ))

        jen_twitter.description = "Relationship Manager for the IT department."
        jen_twitter.post_count = 1543
        jen_twitter.friend_count = 1
        jen_twitter.follower_count = 1
        jen_twitter.join_date = dateutil.parser.parse('2013-03-15')
        jen_twitter.join_date_is_exact = True

        moss_twitter.followers.append(jen_twitter)

        session.add(jen_twitter)

        # A couple of randos.
        moss_twitter.followers.append(Profile(
            site='twitter',
            upstream_id='345678',
            profile_name='franky'
        ))

        moss_twitter.followers.append(Profile(
            site='twitter',
            upstream_id='456789',
            profile_name='jane'
        ))

        jen_twitter.followers.append(Profile(
            site='twitter',
            upstream_id='567890',
            profile_name='joey'
        ))

        session.commit()

    def _drop_all(self):
        '''
        Drop database tables, foreign keys, etc.

        Unlike SQL Alchemy's built-in drop_all() method, this one shouldn't
        punk out if the Python schema doesn't match the actual database schema
        (a common scenario while developing).

        See: https://bitbucket.org/zzzeek/sqlalchemy/wiki/UsageRecipes/DropEverything
        '''

        tables = list()
        all_fks = list()
        metadata = MetaData()
        inspector = reflection.Inspector.from_engine(self._db)
        session = app.database.get_session(self._db)

        for table_name in inspector.get_table_names():
            fks = list()

            for fk in inspector.get_foreign_keys(table_name):
                if not fk['name']:
                    continue
                fks.append(ForeignKeyConstraint((),(),name=fk['name']))

            tables.append(Table(table_name, metadata, *fks))
            all_fks.extend(fks)

        for fk in all_fks:
            try:
                self._db.execute(DropConstraint(fk))
            except Exception as e:
                self._logger.warn('Not able to drop FK "%s".' % fk.name)
                self._logger.debug(str(e))

        for table in tables:
            try:
                self._db.execute(DropTable(table))
            except Exception as e:
                self._logger.warn('Not able to drop table "%s".' % table.name)
                self._logger.debug(str(e))

        session.commit()

    def _get_args(self, arg_parser):
        ''' Customize arguments. '''

        arg_parser.add_argument(
            'action',
            choices=('build','drop'),
            help='Specify what action to take.'
        )

        arg_parser.add_argument(
            '--debug-db',
            action='store_true',
            help='Print database queries.'
        )

        arg_parser.add_argument(
            '--sample-data',
            action='store_true',
            help='Create sample data.'
        )

    def _run(self, args, config):
        ''' Main entry point. '''

        if args.debug_db:
            # Configure database logging.
            log_level = getattr(logging, args.verbosity.upper())

            db_logger = logging.getLogger('sqlalchemy.engine')
            db_logger.setLevel(log_level)
            db_logger.addHandler(self._log_handler)

        # Connect to database.
        database_config = dict(config.items('database'))
        self._db = app.database.get_engine(database_config)

        # Run build commands.
        if args.action in ('build', 'drop'):
            self._logger.info('Dropping database tables.')
            self._drop_all()

        if args.action == 'build':
            self._logger.info('Running Agnostic\'s bootstrap.')
            self._agnostic_bootstrap(config)

            self._logger.info('Creating database tables.')
            Base.metadata.create_all(self._db)

            self._logger.info('Creating fixture data.')
            self._create_fixtures(config)

        if args.action == 'build' and args.sample_data:
            self._logger.info('Creating sample data.')
            self._create_samples(config)
import base64
from datetime import datetime
import dateutil.parser
import os
import re

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, func, \
                       Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import relationship

import app.config
from model import Base


SOCIAL_SITES = {
    'twitter': 'Twitter',
    'instagram': 'Instagram',
}


file_join_profile = Table(
    'file_join_profile',
    Base.metadata,
    Column('file_id', Integer, ForeignKey('file.id'), primary_key=True),
    Column('profile_id', Integer, ForeignKey('profile.id'), primary_key=True),
)


profile_join_self = Table(
    'profile_join_self',
    Base.metadata,
    Column('follower_id', Integer, ForeignKey('profile.id'), primary_key=True),
    Column('friend_id', Integer, ForeignKey('profile.id'), primary_key=True),
)


class Profile(Base):
    ''' Data model for a profile. '''

    __tablename__ = 'profile'
    __table_args__ = (
        UniqueConstraint('site', 'upstream_id', name='uk_site_upstream_id'),
    )

    id = Column(Integer, primary_key=True)
    site = Column(Enum(*SOCIAL_SITES.keys(), name='social_site'), nullable=False)
    upstream_id = Column(String(255), nullable=False)
    username = Column(String(255), nullable=False)

    description = Column(Text)
    follower_count = Column(Integer)
    friend_count = Column(Integer)
    join_date = Column(DateTime)
    last_update = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp())
    lang = Column(String(255))
    location = Column(Text)
    name = Column(String(255))
    post_count = Column(Integer)
    private = Column(Boolean)
    time_zone = Column(Text)

    # One profile has 1-n usernames.
    usernames = relationship(
        'ProfileUsername',
        backref='profile',
        cascade='all,delete-orphan'
    )

    # One profile has 0-n names.
    posts = relationship(
        'Post',
        backref='author',
        cascade='all,delete-orphan'
    )

    # A profile has 0-n avatar images.
    avatars = relationship(
        'File',
        secondary=file_join_profile
    )

    # A profile can follow other profiles. We use the Twitter nomenclature and
    # call this relationship "friend".
    friends = relationship(
        'Profile',
        secondary=profile_join_self,
        primaryjoin=(id==profile_join_self.c.follower_id),
        secondaryjoin=(id==profile_join_self.c.friend_id)
    )

    # A profile can be followed other profiles.
    followers = relationship(
        'Profile',
        secondary=profile_join_self,
        primaryjoin=(id==profile_join_self.c.friend_id),
        secondaryjoin=(id==profile_join_self.c.follower_id)
    )

    def __init__(self, site, upstream_id, username):
        ''' Constructor. '''

        self.site = site
        self.upstream_id = upstream_id

        if isinstance(username, ProfileUsername):
            self.username = username.username
            self.usernames.append(username)
        else:
            self.username = username
            self.usernames.append(ProfileUsername(username))

    def as_dict(self):
        ''' Return dictionary representation of this profile. '''

        return {
            'description': self.description,
            'follower_count': self.follower_count,
            'friend_count': self.friend_count,
            'id': self.id,
            'join_date': self.join_date and self.join_date.isoformat(),
            'last_update': self.last_update.replace(microsecond=0).isoformat(),
            'location': self.location,
            'name': self.name,
            'post_count': self.post_count,
            'private': self.private,
            'site': self.site,
            'site_name': self.site_name(),
            'upstream_id': self.upstream_id,
            'username': self.username,
            'time_zone': self.time_zone,
        }

    def site_name(self):
        ''' Human readable name for site. '''

        return SOCIAL_SITES[self.site]


class ProfileUsername(Base):
    ''' A profile can have many usernames. '''

    __tablename__ = 'profile_username'
    __table_args__ = (
        UniqueConstraint('username', 'profile_id', name='uk_username_profile_id'),
    )

    id = Column(Integer, primary_key=True)
    username = Column(String(255))
    start_date = Column(DateTime)
    end_date = Column(DateTime)

    profile_id = Column(
        Integer,
        ForeignKey('profile.id', name='fk_profile_username_id'),
        nullable=False
    )

    def __init__(self, username, start_date=None, end_date=None):
        ''' Constructor. '''

        self.username = username

        if start_date is not None:
            if isinstance(start_date, datetime):
                self.start_date = start_date
            else:
                self.start_date = dateutil.parser.parse(start_date)

        if end_date is not None:
            if isinstance(end_date, datetime):
                self.end_date = end_date
            else:
                self.end_date = dateutil.parser.parse(end_date)
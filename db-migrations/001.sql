-- first version of the database

CREATE TABLE messages (
    id integer PRIMARY KEY,
    author integer NOT NULL,
    channelid integer,
    channelname text,
    guildid integer,
    clean_content text,
    created_at timestamp
);
CREATE INDEX timeindex ON messages(created_at);
CREATE INDEX channelname ON messages(channelname);
CREATE INDEX authorcontent ON messages(author,clean_content,channelid);

CREATE TABLE modlogs (
    id integer PRIMARY KEY,
    author integer NOT NULL,
    channelid integer,
    channelname text,
    guildid integer,
    clean_content text,
    created_at timestamp,
    user integer,
    type integer
);
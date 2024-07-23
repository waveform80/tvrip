CREATE TABLE NEW.version (
    version INTEGER NOT NULL
);
INSERT INTO NEW.version (version) VALUES (2);

CREATE TABLE NEW.programs (
        program  VARCHAR(200) NOT NULL,

        CONSTRAINT programs_pk
            PRIMARY KEY (program)
);

CREATE TABLE NEW.seasons (
        program  VARCHAR(200) NOT NULL,
        season   INTEGER NOT NULL,

        CONSTRAINT seasons_pk
            PRIMARY KEY (program, season),
        CONSTRAINT seasons_program_fk
            FOREIGN KEY(program)
            REFERENCES programs (program)
            ON DELETE CASCADE ON UPDATE CASCADE,
        CONSTRAINT seasons_season_ck
            CHECK (season >= 0)
);

CREATE TABLE NEW.episodes (
        program       VARCHAR(200) NOT NULL,
        season        INTEGER NOT NULL,
        episode       INTEGER NOT NULL,
        title         VARCHAR(200) NOT NULL,
        disc_id       VARCHAR(200),
        disc_title    INTEGER DEFAULT NULL,
        start_chapter INTEGER DEFAULT NULL,
        end_chapter   INTEGER DEFAULT NULL,
        CONSTRAINT episodes_pk
            PRIMARY KEY (program, season, episode),
        CONSTRAINT episodes_season_fk
            FOREIGN KEY(program, season)
            REFERENCES seasons (program, season)
            ON DELETE CASCADE ON UPDATE CASCADE,
        CONSTRAINT episodes_episode_ck
            CHECK (episode >= 1),
        CONSTRAINT episodes_chapter_ck
            CHECK (
                (end_chapter IS NULL AND start_chapter IS NULL) OR
                (end_chapter >= start_chapter)
            )
);

CREATE TABLE NEW.config (
        id        VARCHAR(100) DEFAULT 'default' NOT NULL,
        program   VARCHAR(200) DEFAULT NULL,
        season    INTEGER DEFAULT NULL,
        config    TEXT NOT NULL,

        CONSTRAINT config_pk
            PRIMARY KEY (id),
        CONSTRAINT config_program_fk
            FOREIGN KEY(program)
            REFERENCES programs (program)
            ON DELETE SET NULL ON UPDATE CASCADE,
        CONSTRAINT config_season_fk
            FOREIGN KEY(program, season)
            REFERENCES seasons (program, season)
            ON DELETE SET NULL ON UPDATE CASCADE
);

INSERT INTO NEW.config(config) VALUES (
    json('
{
    "source": "/dev/dvd",
    "target": "~/Videos",
    "temp": "/tmp",
    "template": "{program} - {id} - {name}.{ext}",
    "id_template": "{season}x{episode:02d}",
    "duration": [40, 50],
    "audio_all": false,
    "audio_encoding": "av_aac",
    "audio_mix": "dpl2",
    "audio_langs": ["eng"],
    "subtitle_all": false,
    "subtitle_default": false,
    "subtitle_format": "none",
    "subtitle_langs": ["eng"],
    "decomb": "auto",
    "dvdnav": true,
    "video_style": "tv",
    "duplicates": "all",
    "output_format": "mp4",
    "api_key": "",
    "api_url": "https://api.thetvdb.com/",
    "max_resolution": [1920, 1080],
    "paths": {
        "vlc": "/usr/bin/vlc",
        "handbrake": "/usr/bin/HandBrakeCLI",
        "atomicparsley": "/usr/bin/AtomicParsley",
        "mkvpropedit": "/usr/bin/mkvpropedit"
    }
}
'));

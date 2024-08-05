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

INSERT INTO NEW.config(config) VALUES (json('{}'));

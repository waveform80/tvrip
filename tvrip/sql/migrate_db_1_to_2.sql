-- Work around broken foreign keys in old versions
INSERT INTO NEW.programs(program)
    SELECT program_name FROM episodes
    UNION
    SELECT * FROM programs;

-- Work around broken foreign keys in old versions
INSERT INTO NEW.seasons (
    program,
    season
)
    SELECT program_name, season_number FROM episodes
    UNION
    SELECT * FROM seasons;

INSERT INTO NEW.episodes SELECT * FROM episodes;

DELETE FROM NEW.config;

WITH audio AS (
    SELECT
        config_id,
        json_group_array(lang) AS langs
    FROM config_audio
),
subtitles AS (
    SELECT
        config_id,
        json_group_array(lang) AS langs
    FROM config_subtitles
),
paths AS (
    SELECT
        config_id,
        json_group_object(name, path) AS paths
    FROM config_paths
),
config_transform AS (
    SELECT
        'default' AS id,
        c.program_name,
        c.season_number,
        json_object(
            'source', c.source,
            'target', c.target,
            'temp', c."temp",
            'template', c.template,
            'id_template', c.id_template,
            'duration', json_array(c.duration_min, c.duration_max),
            'audio_all', c.audio_all,
            'audio_encoding', 'av_aac',
            'audio_mix', c.audio_mix,
            'audio_langs', json(a.langs),
            'subtitle_all', c.subtitle_all,
            'subtitle_default', c.subtitle_default,
            'subtitle_format', c.subtitle_format,
            'subtitle_langs', json(s.langs),
            'decomb', c.decomb,
            'dvdnav', c.dvdnav,
            'video_style', c.video_style,
            'duplicates', c.duplicates,
            'output_format', c.output_format,
            'max_resolution', json_array(c.width_max, c.height_max),
            'api_url', c.api_url,
            'api_key', c.api_key,
            'paths', json(p.paths)
        ) AS config
    FROM
        config AS c
        JOIN audio AS a ON c.id = a.config_id
        JOIN subtitles AS s ON c.id = s.config_id
        JOIN paths AS p ON c.id = p.config_id
    WHERE c.id = 1
)
INSERT INTO NEW.config
    SELECT * FROM config_transform;

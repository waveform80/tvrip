import pytest

from tvrip import database

@pytest.fixture()
def db(request, tmpdir):
    url = 'sqlite:///{tmpdir!s}/tvrip.db'.format(tmpdir=tmpdir)
    with database.init_session(url) as session:
        yield session


@pytest.fixture()
def with_config(request, db):
    cfg = database.Configuration()
    db.add(cfg)
    db.add(database.AudioLanguage(cfg, 'eng'))
    db.add(database.SubtitleLanguage(cfg, 'eng'))
    db.add(database.ConfigPath(cfg, 'handbrake', 'HandBrakeCLI'))
    db.add(database.ConfigPath(cfg, 'atomicparsley', 'AtomicParsley'))
    db.add(database.ConfigPath(cfg, 'vlc', 'vlc'))
    db.commit()
    yield cfg


@pytest.fixture()
def with_program(request, db, with_config):
    cfg = with_config
    prog = database.Program('Foo & Bar')
    db.add(prog)
    cfg.program = prog
    cfg.season = None
    yield prog


@pytest.fixture()
def with_season(request, db, with_config, with_program):
    cfg = with_config
    prog = with_program
    season = database.Season(prog, 1)
    db.add(season)
    cfg.season = season
    yield season


@pytest.fixture()
def with_episode(request, db, with_config, with_season):
    cfg = with_config
    season = with_season
    ep = database.Episode(season, 1, 'Pilot')
    db.add(ep)
    yield ep

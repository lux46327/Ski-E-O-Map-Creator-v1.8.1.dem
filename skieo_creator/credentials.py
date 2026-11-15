"""Access keys for national elevation services that ask for one (Finland and Sweden).

Everything about a service is plain data in PROVIDERS, so adding another country is one entry here plus its source's
name in dem.SOURCE_PROVIDER; the window in the app is built from `info()`.

Keys are kept in memory for the current session only. They are never written to disk or to the log. Environment
variables named in a field's `env` serve as a default when nothing was entered (handy for scripts and tests).
"""
import threading

import requests

from . import net


class Needed(Exception):
    """raised by dem.load() when a source applies to the window but its key is missing; the app asks for the key"""

    def __init__(self, provider):
        self.provider = provider
        super().__init__('An access key for %s is needed to load this area.' % PROVIDERS[provider]['name'])


# ------------------------------------------------------------------ the services

def _verify_nls(v):
    """soft check of the Finnish key: a refused key (401/403) is invalid, any other trouble is not the key's fault"""
    r = requests.get('https://avoin-karttakuva.maanmittauslaitos.fi/ortokuvat-ja-korkeusmallit/wcs/v2',
                     params={'service': 'WCS', 'version': '2.0.1', 'request': 'GetCapabilities', 'api-key': v['key']},
                     timeout=20)
    if r.status_code in (401, 403):
        return False, 'The National Land Survey of Finland did not accept this key.'
    return True, ''


def _verify_lm(v):
    """soft check of the Swedish consumer key and secret: they must produce an access token"""
    r = requests.post('https://apimanager.lantmateriet.se/oauth2/token', data={'grant_type': 'client_credentials'},
                      auth=(v['key'], v['secret']), timeout=20)
    if r.status_code in (400, 401):
        return False, 'Lantmäteriet did not accept this consumer key and secret.'
    return True, ''


PROVIDERS = {
    'nls': dict(
        name='National Land Survey of Finland',
        country='Finland',
        dataset='Elevation model 2 m (Korkeusmalli)',
        fields=[dict(id='key', label='API key', secret=True, env='MML_API_KEY', placeholder='xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx')],
        verify=_verify_nls,
        steps=[
            dict(text='Open the National Land Survey\'s key page and register in the "My Account" service with your e-mail address (free).',
                 link='nls_key', label='Open the key instructions'),
            dict(text='Log in and create an API key. It is a code like 1a2b3c4d-....'),
            dict(text='Paste the key below and press Use key.'),
        ],
        license=dict(
            text='The data is open data of the National Land Survey of Finland (Maanmittauslaitos), licence CC BY 4.0. '
                 'The Survey uses the key to monitor use and may contact you. The key is personal: do not share it. '
                 'Using it means you accept the Survey\'s terms of use for open interfaces, which can change.',
            link='nls_terms', label='Read the terms of use'),
    ),
    'lantmateriet': dict(
        name='Lantmäteriet (Sweden)',
        country='Sweden',
        dataset='Markhöjdmodell, 1 m',
        fields=[dict(id='key', label='Consumer key', secret=False, env='LM_CLIENT_ID', placeholder='Consumer key'),
                dict(id='secret', label='Consumer secret', secret=True, env='LM_CLIENT_SECRET', placeholder='Consumer secret')],
        verify=_verify_lm,
        steps=[
            dict(text='Create a free Geotorget account (or log in to yours).', link='geotorget', label='Open Geotorget'),
            dict(text='In Geotorget order "Markhöjdmodell Nedladdning" for the production environment. It costs 0 kr and '
                      'becomes active after a few minutes.', link='lm_order', label='Open the order page'),
            dict(text='Log in to the Lantmäteriet API portal with the same account and create an application '
                      '(name it anything). Subscribe it to the API "GeodatakatalogNedladdning".', link='lm_portal',
                 label='Open the API portal'),
            dict(text='Open the application\'s "Production Keys", leave only "Client Credentials" ticked and press '
                      'Generate Keys. Do not use the sandbox keys.'),
            dict(text='Copy the Consumer Key and Consumer Secret into the fields below and press Use key.'),
        ],
        license=dict(
            text='The elevation model is open data of Lantmäteriet, licence CC0, and downloading is free. Using the '
                 'download service means you accept Lantmäteriet\'s terms for valuable datasets ("Användningsvillkor '
                 'för värdefulla datamängder"). The key and secret belong to your account: do not share them.',
            link='lm_terms', label='Read the terms'),
    ),
}

_lock = threading.Lock()
_session = {}          # provider -> {field: value}, this session only
_skipped = set()       # providers the player chose to do without (Terrain Tiles are used there)


# ------------------------------------------------------------------ access

def _env(pid):
    import os
    vals = {f['id']: os.environ.get(f['env'], '').strip() for f in PROVIDERS[pid]['fields'] if f.get('env')}
    return vals if vals and all(vals.values()) else None


def get(pid):
    """{field: value} of the key in use (entered in the app, else from the environment), or None"""
    with _lock:
        vals = dict(_session[pid]) if pid in _session else _env(pid)
    return vals


def has(pid):
    present = get(pid) is not None
    return present


def is_skipped(pid):
    with _lock:
        skipped = pid in _skipped and pid not in _session
    return skipped


def require(pid):
    """the key, or Needed when there is none (and the player has not chosen to skip this service)"""
    v = get(pid)
    if v is None:
        raise Needed(pid)
    return v


def cache_tag():
    """part of the elevation cache key: a window loaded without a service's data must not hide the full result once a key exists"""
    with _lock:
        return ','.join(sorted(p for p in _skipped if p not in _session))


# ------------------------------------------------------------------ what the window does

def info(pid):
    """everything the window needs to describe a service (no secrets)"""
    p = PROVIDERS[pid]
    return dict(id=pid, name=p['name'], country=p['country'], dataset=p['dataset'], steps=p['steps'],
                license=p['license'], has_key=has(pid),
                fields=[dict(id=f['id'], label=f['label'], secret=f['secret'], placeholder=f.get('placeholder', ''))
                        for f in p['fields']])


def set_key(pid, values, check=True):
    """store a key for this session; -> (ok, message). A key the service refuses is not stored."""
    p = PROVIDERS[pid]
    vals = {f['id']: str(values.get(f['id'], '')).strip() for f in p['fields']}
    missing = [f['label'] for f in p['fields'] if not vals[f['id']]]
    if missing:
        return False, 'Please fill in: %s.' % ', '.join(missing)
    note = ''
    if check:
        try:
            ok, msg = p['verify'](vals)
        except (requests.RequestException, net.NetError):
            ok, msg, note = True, '', 'Could not check the key (no connection to the service); it was kept anyway.'
        if not ok:
            return False, msg
    with _lock:
        _session[pid] = vals
        _skipped.discard(pid)
    return True, note


def skip(pid):
    with _lock:
        _skipped.add(pid)
        _session.pop(pid, None)


def forget(pid):
    with _lock:
        _session.pop(pid, None)
        _skipped.discard(pid)

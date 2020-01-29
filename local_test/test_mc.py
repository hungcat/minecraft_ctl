import os
import sys
import urllib.request
import pathlib
import re
import shutil
import traceback
import stat
import datetime

# furl
from furl import furl
# GitPython
import git
# python-digitalocean
import digitalocean
# paramiko
import paramiko
# cryptodomex
from Cryptodome.PublicKey import RSA
# retry
from retry import retry
# emoji
import emoji

import docker

#os.environ['GITHUB_USER'] = 'hungcat'
#os.environ['GITHUB_TOKEN'] = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

GITHUB_USER = os.getenv('GITHUB_USER')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

GITHUB_URL = 'https://github.com'
GITHUB_RAW_URL = 'https://raw.githubusercontent.com'
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
MINECRAFT_PORT = 25565
USAGE = '''
Usage: {0} [create|backup|destroy|destroy_without_backup|help] [target]
    create: Create and serve minecraft server
        {0} create [world_repository] [version|LATEST|SNAPSHOT]
        ex: {0} create hungcat/minecraft_world 1.14.4
    backup: Back up current world to corresponding github repository
        {0} backup [world_repository]
        ex: {0} backup hungcat/minecraft_world
    destroy: Destroy current world with backup
        {0} destroy [world_repository]
        ex: {0} destroy hungcat/minecraft_world
    destroy_without_backup: Destroy current world without backup
        {0} destroy_without_backup [world_repository]
        ex: {0} destroy_without_backup hungcat/minecraft_world
    help: Show this
        {0} help

Required environment variables:
    GITHUB_USER (for backup)
        User ID of github for backup the world.
    GITHUB_TOKEN (for backup)
        Personal access token of github for backup the world.
        ref: https://help.github.com/ja/github/authenticating-to-github/creating-a-personal-access-token-for-the-command-line
'''.format(__file__).strip()


def command_handler(args):
    argc = len(args)
    if argc < 2:
        # show usage
        print(USAGE)
        return
    else:
        world_name = ''
        version = ''
        if argc > 1:
            action = args[1]
        if argc > 2:
            world_name = args[2]
        if argc > 3:
            version = args[3]

    try:
        if action == 'create':
            print(_emoji(':muscle: Creating server...'))
            print(create_server(world_name, version))
        elif action == 'backup':
            print(_emoji(':muscle: Backuping world data...'))
            print(backup_world(world_name))
        elif action == 'destroy':
            print(_emoji(':muscle: Backuping world data...'))
            print(backup_world(world_name))
            print(_emoji(':muscle: Destroying server...'))
            print(destroy_server(world_name))
        elif action == 'destroy_without_backup':
            print(_emoji(':muscle: Destroying server...'))
            print(destroy_server(world_name))
        elif action == 'help':
            print(USAGE)
        elif action == 'ip':
            print(get_ip())
        elif action == 'restart':
            print(_emoji(':muscle: Restarting server...'))
            print(restart())
        elif action == 'rcon':
            print(rcon(world_name))
        else:
            print('Invalid action: {}'.format(action))
            print(USAGE)
    except Exception as e:
        print(_emoji(':no_good: Error: {}'.format(e)))
        #print(traceback.format_exc()) 

    return

def get_ip():
    return furl(docker.from_env().api.base_url).set(port=MINECRAFT_PORT).url

def restart():
    docker.from_env().containers.get('minecraft').restart()
    return _emoji(':information: Server restarted.')

def rcon(cmd):
    status, out = docker.from_env().containers.get('minecraft').exec_run('rcon-cli {}'.format(cmd))
    return out.decode('utf-8')

def create_server(world_name='', version=''):
    data_dir = SCRIPT_DIR / 'data'
    backup_url = _construct_github_url(world_name)
    version_url = _construct_github_url(world_name, path='master/MCCTL_VERSION.txt', is_raw=True)

    data_dir.mkdir(parents=True, exist_ok=True)

    if _test_github_url(backup_url) == True:
        git.Repo.clone_from(backup_url, data_dir)

        v = ''
        try:
            v = (data_dir / 'MCCTL_VERSION.txt').read_text()
        except Exception as e:
            print(_emoji(':information: MCCTL_VERSION.txt may not exists: {}'.format(e)))
        if v != '':
            if version == '':
                version = v
            else:
                if _yes_no_input('Last run version is {}. Run version {} now?'.format(v, version)) == False:
                    return _emoji(':no_good: Exit: Disagreed with version setting')

    if version == '':
        version = 'LATEST'

    try:
        docker.from_env().containers.run('itzg/minecraft-server',
                detach=True,
                environment={ 'EULA': 'TRUE', 'VERSION': version, 'WORLD': '/data/world', 'TZ': 'Asia/Tokyo' },
                volumes={ re.sub(r'^([a-zA-Z]):/', lambda m: '/{}/'.format(m.group(1).lower()), data_dir.resolve().as_posix()): { 'bind': '/data', 'mode': 'rw' } },
                name='minecraft',
                ports={ '{}/tcp'.format(MINECRAFT_PORT): MINECRAFT_PORT },
                restart_policy={ "Name": "always" })
        # host port is left hand (corresponding to below message)

        print(_emoji(':muscle: Minecraft is waking up!'))
        message = _emoji(':hammer_and_pick: Created minecraft {} instance: `{}`'.format(version, get_ip()))
    except Exception as e:
        print(_emoji(':cry: Minecraft couldn\'t wake up. Please destroy this server yourself IF it waked up...'))
        #message = _emoji(':cry: Failed to create server...')
        raise e

    return message


def backup_world(world_name=''):
    backup_url = _construct_github_url(world_name)
    output_url = '{}/{}'.format(GITHUB_URL, world_name)

    repo_path = SCRIPT_DIR / 'data'
    set_remote = False

    try:
        repo = git.Repo(repo_path)
        origin = repo.remote(name='origin')
        o_pathes = [ furl(url).path for url in origin.urls ]
        if world_name != '' and furl(backup_url).path not in o_pathes:
            set_remote = True
        elif len(o_pathes) == 1:
            output_url = '{}{}'.format(GITHUB_URL, o_pathes[0])
    except git.exc.NoSuchPathError:
        return _emoji(':cry: No files to backup in {}'.format(repo_path))
    except git.exc.InvalidGitRepositoryError:
        set_remote = True

    if set_remote:
        if world_name == '':
            raise Exception(_emoji('backup_url didn\'t set.'))
        if _test_github_url(backup_url) == False:
            raise Exception(_emoji('Unavailable repository: {}'.format(output_url)))

        repo = git.Repo.init(repo_path)
        origin = repo.create_remote('origin', backup_url)
        repo.create_head('master', origin.refs.master).set_tracking_branch(origin.refs.master)

    gitignore = repo_path / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('/minecraft_server*.jar')

    jars = list(repo_path.glob('*.jar'))
    version = ''
    if len(jars) == 1:
        version = re.sub(r'^[^.]*\.([0-9.]*)\.jar$', r'\1', jars[0].name)
        (repo_path / 'MCCTL_VERSION.txt').write_text(version)

    repo.git.add('--all')
    repo.index.commit('world {} update [{}]'.format(version, datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y/%m/%d %H:%M:%S%z')))
    origin.push('master')

    return _emoji(':rocket: Backuped world: {}'.format(output_url))

def destroy_server(world_name=''):
    docker.from_env().containers.get('minecraft').remove(force=True)

    data_dir = SCRIPT_DIR / 'data'
    if data_dir.exists():
        def del_rw(func, path, _):
            try:
                if not os.access(path, os.W_OK):
                    os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception as e:
                print(_emoji(':cry: Failed to delete {}: {}'.format(path, e)))
        shutil.rmtree(data_dir, onerror=del_rw)

    return _emoji(':boom: Destroyed instance: `minecraft`')

def _construct_github_url(world_name, path='', is_raw=False):
    if is_raw:
        url = furl(GITHUB_RAW_URL)
    else:
        url = furl(GITHUB_URL)
    #parsed.scheme = 'https'
    url.path = '{}/{}'.format(url.path, world_name)
    if path != '':
        url.path = '{}/{}'.format(url.path, path)
    url.username = GITHUB_USER
    url.password = GITHUB_TOKEN
    return url.tostr()

def _test_github_url(github_url):
    try:
        git.cmd.Git().ls_remote(github_url)
    except git.GitCommandError as e:
        return False
    return True

def _yes_no_input(message):
    while True:
        choice = input("{} [y[es]/n[o]]: ".format(message)).lower()
        if choice in ['y', 'ye', 'yes']:
            return True
        elif choice in ['n', 'no']:
            return False

def _emoji(mes):
    return emoji.emojize(mes, use_aliases=True)

if __name__ == '__main__':
    command_handler(sys.argv)

